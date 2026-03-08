"""
Production push test harness — drives hermes-lite via the subprocess JSON protocol.

Spawns run_agent.py --subprocess-mode as a child process, sends ToAgent JSON
messages on stdin, and collects FromAgent JSON messages from stdout. This is
the same protocol the Rust TUI uses, so prodpush tests exercise the exact
same code path as a real user session.

Usage in tests:

    async with AgentSession() as agent:
        events = await agent.send("list files in /tmp", timeout=30)
        assert any(e["type"] == "Done" for e in events)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# Resolve paths relative to repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python"
_RUN_AGENT = _REPO_ROOT / "run_agent.py"


@dataclass
class CollectedEvents:
    """All events received from a single user message until Done/Error."""
    events: list[dict[str, Any]] = field(default_factory=list)
    tokens: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    done: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None

    @property
    def response_text(self) -> str:
        """Concatenated non-thinking tokens — the visible assistant reply."""
        return "".join(
            e["content"] for e in self.events
            if e["type"] == "Token" and not e.get("is_thinking")
        )

    @property
    def thinking_text(self) -> str:
        return "".join(
            e["content"] for e in self.events
            if e["type"] == "Token" and e.get("is_thinking")
        )

    @property
    def tool_names(self) -> list[str]:
        return [e["tool_name"] for e in self.events if e["type"] == "ToolCallStart"]

    @property
    def succeeded(self) -> bool:
        return self.done is not None and self.done.get("reason") == "completed"

    @property
    def was_interrupted(self) -> bool:
        return self.done is not None and self.done.get("reason") == "interrupted"

    def has_tool(self, name: str) -> bool:
        return name in self.tool_names

    def tool_output(self, name: str) -> Optional[str]:
        """Get the output of the first tool call matching `name`."""
        for start in self.events:
            if start["type"] == "ToolCallStart" and start["tool_name"] == name:
                tid = start["tool_id"]
                for result in self.events:
                    if result["type"] == "ToolCallResult" and result["tool_id"] == tid:
                        return result["output"]
        return None


class AgentSession:
    """
    Async context manager that manages a live agent subprocess.

    Sends/receives JSON messages over the subprocess protocol, exactly
    like the Rust TUI does. Tests can call send() multiple times for
    multi-turn conversations.
    """

    def __init__(
        self,
        model: str | None = None,
        max_iterations: int = 10,
        env_overrides: dict[str, str] | None = None,
        timeout: float = 120,
    ):
        self.model = model or os.getenv("LLM_MODEL", "claude-sonnet-4-5-20250929")
        self.max_iterations = max_iterations
        self.timeout = timeout
        self._env = {**os.environ, **(env_overrides or {})}
        self._env["HERMES_QUIET"] = "1"
        self._proc: Optional[asyncio.subprocess.Process] = None
        self.session_id: str = ""
        self.session_info: Optional[dict] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._event_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._closed = False

    async def __aenter__(self) -> "AgentSession":
        self._proc = await asyncio.create_subprocess_exec(
            str(_VENV_PYTHON), str(_RUN_AGENT), "--subprocess-mode",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        # Wait for Ready + SessionInfo
        await self._wait_for_ready()
        return self

    async def __aexit__(self, *exc):
        if not self._closed:
            await self.shutdown()

    async def _read_stdout(self):
        """Background task: read JSON lines from subprocess stdout."""
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                # EOF — subprocess has closed stdout
                await self._event_queue.put({"type": "_EOF"})
                break
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                await self._event_queue.put(msg)
            except json.JSONDecodeError:
                # Non-JSON output (shouldn't happen in subprocess mode)
                continue

    async def _wait_for_ready(self):
        deadline = asyncio.get_event_loop().time() + 30
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(self._event_queue.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if msg["type"] == "SessionInfo":
                self.session_info = msg
                self.session_id = msg.get("session_id", "")
            elif msg["type"] == "Ready":
                return
        raise TimeoutError("Agent subprocess did not emit Ready within 30s")

    async def _write_async(self, msg: dict):
        """Send a JSON message to the subprocess stdin (async, with flush)."""
        assert self._proc and self._proc.stdin
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

    def _write(self, msg: dict):
        """Send a JSON message to the subprocess stdin (sync, best-effort flush)."""
        assert self._proc and self._proc.stdin
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        # Drain must be awaited; schedule if we're in an event loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._proc.stdin.drain())
        except RuntimeError:
            pass

    async def send(
        self,
        message: str,
        *,
        timeout: float | None = None,
        model: str | None = None,
        max_iterations: int | None = None,
        auto_clarify: str | None = None,
    ) -> CollectedEvents:
        """
        Send a user message and collect all events until Done or Error.

        Args:
            message: The user prompt
            timeout: Override default timeout for this message
            model: Override model for this message
            max_iterations: Override max iterations
            auto_clarify: If set, automatically respond to ClarifyRequest with this string
        """
        timeout = timeout or self.timeout
        sid = self.session_id or f"prodpush-{uuid.uuid4().hex[:8]}"
        await self._write_async({
            "type": "UserInput",
            "session_id": sid,
            "message": message,
            "model": model or self.model,
            "max_iterations": max_iterations or self.max_iterations,
        })

        collected = CollectedEvents()
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                msg = await asyncio.wait_for(
                    self._event_queue.get(), timeout=min(remaining, 5)
                )
            except asyncio.TimeoutError:
                continue

            t = msg["type"]
            if t == "_EOF":
                collected.error = {"type": "Error", "message": "Subprocess exited", "code": "EOF"}
                return collected

            collected.events.append(msg)

            if t == "ClarifyRequest" and auto_clarify is not None:
                await self._write_async({
                    "type": "ClarifyResponse",
                    "response": auto_clarify,
                })

            if t == "Done":
                collected.done = msg
                return collected
            if t == "Error":
                collected.error = msg
                # Error is usually followed by Done, keep collecting
                continue

        # Timeout — interrupt and return what we have
        await self.async_interrupt()
        collected.error = {"type": "Error", "message": "Test timeout", "code": "TIMEOUT"}
        return collected

    async def async_interrupt(self):
        """Send an interrupt signal (async)."""
        await self._write_async({"type": "Interrupt"})

    def interrupt(self):
        """Send an interrupt signal (sync, for use in non-async contexts)."""
        self._write({"type": "Interrupt"})

    async def shutdown(self):
        """Gracefully shut down the subprocess."""
        self._closed = True
        try:
            await self._write_async({"type": "Shutdown"})
        except Exception:
            pass
        if self._proc:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

    async def get_stderr(self) -> str:
        """Read any stderr output from the subprocess."""
        if self._proc and self._proc.stderr:
            try:
                data = await asyncio.wait_for(self._proc.stderr.read(), timeout=1)
                return data.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                return ""
        return ""


class Recipe:
    """
    A scripted sequence of interactions for automated testing.

    Recipes define a series of user messages, expected behaviors,
    and validation checks that run against a live agent session.
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.steps: list[RecipeStep] = []

    def add_step(
        self,
        message: str,
        *,
        expect_tools: list[str] | None = None,
        expect_in_response: list[str] | None = None,
        expect_no_error: bool = True,
        expect_completed: bool = True,
        timeout: float = 60,
        auto_clarify: str | None = None,
        validate: Any = None,  # callable(CollectedEvents) -> None
    ) -> "Recipe":
        self.steps.append(RecipeStep(
            message=message,
            expect_tools=expect_tools or [],
            expect_in_response=expect_in_response or [],
            expect_no_error=expect_no_error,
            expect_completed=expect_completed,
            timeout=timeout,
            auto_clarify=auto_clarify,
            validate=validate,
        ))
        return self

    async def run(self, session: AgentSession) -> list[CollectedEvents]:
        """Execute all steps sequentially against the given session."""
        results = []
        for i, step in enumerate(self.steps):
            events = await session.send(
                step.message,
                timeout=step.timeout,
                auto_clarify=step.auto_clarify,
            )
            results.append(events)

            # Built-in assertions
            step_label = f"[{self.name} step {i}: {step.message[:50]}]"

            if step.expect_no_error and events.error:
                raise AssertionError(
                    f"{step_label} unexpected error: {events.error}"
                )

            if step.expect_completed and not events.succeeded:
                raise AssertionError(
                    f"{step_label} expected completed, got: "
                    f"{events.done or events.error or 'no Done event'}"
                )

            for tool in step.expect_tools:
                if not events.has_tool(tool):
                    raise AssertionError(
                        f"{step_label} expected tool '{tool}' but got: {events.tool_names}"
                    )

            for text in step.expect_in_response:
                if text.lower() not in events.response_text.lower():
                    raise AssertionError(
                        f"{step_label} expected '{text}' in response, got:\n"
                        f"{events.response_text[:500]}"
                    )

            if step.validate:
                step.validate(events)

        return results


@dataclass
class RecipeStep:
    message: str
    expect_tools: list[str] = field(default_factory=list)
    expect_in_response: list[str] = field(default_factory=list)
    expect_no_error: bool = True
    expect_completed: bool = True
    timeout: float = 60
    auto_clarify: str | None = None
    validate: Any = None
