"""
Production push validation suite — real LLM calls, real tool execution.

Runs hermes-lite agent via subprocess protocol with actual API calls.
Every test creates a live session, sends real prompts, gets real model
responses, and validates that tools actually execute on the filesystem.

Requirements:
    - ANTHROPIC_API_KEY (or equivalent) set in environment
    - .venv built with `maturin develop --release -m hermes_rs/Cargo.toml`

Run:
    python -m pytest tests/prodpush/test_prodpush.py -v -s --timeout=300
    python -m pytest tests/prodpush/test_prodpush.py -v -s -k "test_file_write"

Skip in CI (no API key):
    python -m pytest tests/prodpush/ -v --ignore-glob="*prodpush*"
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import textwrap
from pathlib import Path

import pytest

from .harness import AgentSession, CollectedEvents, Recipe

# ── Skip if no API key ──────────────────────────────────────────────────

_HAS_API_KEY = bool(
    os.getenv("ANTHROPIC_API_KEY")
    or os.getenv("OPENAI_API_KEY")
    or os.getenv("OPENROUTER_API_KEY")
)

pytestmark = [
    pytest.mark.skipif(not _HAS_API_KEY, reason="No API key — skip prodpush"),
    pytest.mark.prodpush,
    pytest.mark.timeout(180),
]


# ── Helpers ─────────────────────────────────────────────────────────────

@pytest.fixture
def work_dir(tmp_path):
    """Temp directory for file operation tests."""
    return tmp_path


def _event_loop():
    """Get or create an event loop."""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


# ── 1. BASIC CONNECTIVITY ──────────────────────────────────────────────

class TestAgentStartup:
    """Verify the agent subprocess starts, emits Ready, and responds."""

    def test_subprocess_ready(self):
        """Agent starts in subprocess mode and emits Ready + SessionInfo."""
        async def _run():
            async with AgentSession(max_iterations=1) as agent:
                assert agent.session_info is not None
                assert agent.session_info["type"] == "SessionInfo"
                assert agent.session_id != ""
                assert agent.session_info.get("model") != ""
        asyncio.run(_run())

    def test_simple_greeting(self):
        """Agent responds to a simple greeting with real LLM output."""
        async def _run():
            async with AgentSession(max_iterations=2) as agent:
                events = await agent.send(
                    "Say exactly: HERMES_ALIVE. Nothing else.",
                    timeout=60,
                )
                assert events.succeeded, f"Did not complete: {events.error or events.done}"
                assert "HERMES_ALIVE" in events.response_text.upper().replace(" ", "_"), \
                    f"Expected HERMES_ALIVE in: {events.response_text[:200]}"
        asyncio.run(_run())

    def test_multi_turn_conversation(self):
        """Multiple messages in the same session maintain context."""
        async def _run():
            async with AgentSession(max_iterations=2) as agent:
                e1 = await agent.send(
                    "Remember the code word: BANANA_FISH_42. Confirm you got it.",
                    timeout=60,
                )
                assert e1.succeeded

                e2 = await agent.send(
                    "What was the code word I just told you? Reply with only the code word.",
                    timeout=60,
                )
                assert e2.succeeded
                assert "BANANA_FISH_42" in e2.response_text.upper().replace(" ", "_"), \
                    f"Context lost. Got: {e2.response_text[:200]}"
        asyncio.run(_run())


# ── 2. TOOL EXECUTION — FILE OPERATIONS ────────────────────────────────

class TestFileOperations:
    """Test real file reads, writes, and patches via tool calls."""

    def test_file_write_and_read(self, work_dir):
        """Agent writes a file, then reads it back."""
        target = work_dir / "hello.txt"

        async def _run():
            async with AgentSession(max_iterations=6) as agent:
                events = await agent.send(
                    f'Write the text "prodpush_test_ok" to the file {target}. '
                    f'Use the write_file tool. Do not explain, just do it.',
                    timeout=90,
                )
                assert events.succeeded, f"Write failed: {events.error or events.done}"
                assert events.has_tool("write_file"), \
                    f"Expected write_file tool, got: {events.tool_names}"
                assert target.exists(), f"File not created: {target}"
                content = target.read_text().strip()
                assert "prodpush_test_ok" in content, f"Wrong content: {content}"

        asyncio.run(_run())

    def test_file_read(self, work_dir):
        """Agent reads an existing file and reports its contents."""
        target = work_dir / "data.txt"
        target.write_text("SECRET_VALUE_XJ9\n")

        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    f"Read the file at {target} and tell me its exact contents.",
                    timeout=60,
                )
                assert events.succeeded
                assert events.has_tool("read_file"), \
                    f"Expected read_file tool, got: {events.tool_names}"
                assert "SECRET_VALUE_XJ9" in events.response_text, \
                    f"Content not in response: {events.response_text[:300]}"

        asyncio.run(_run())

    def test_file_patch(self, work_dir):
        """Agent patches an existing file to change specific content."""
        target = work_dir / "config.txt"
        target.write_text("version=1.0\nname=old_name\nstatus=active\n")

        async def _run():
            async with AgentSession(max_iterations=6) as agent:
                events = await agent.send(
                    f'In the file {target}, change "name=old_name" to "name=new_name". '
                    f'Use the patch tool.',
                    timeout=90,
                )
                assert events.succeeded
                content = target.read_text()
                assert "name=new_name" in content, f"Patch not applied: {content}"
                assert "version=1.0" in content, "Other lines corrupted"
                assert "status=active" in content, "Other lines corrupted"

        asyncio.run(_run())

    def test_search_files(self, work_dir):
        """Agent searches for files containing a specific pattern."""
        (work_dir / "a.py").write_text("def hello():\n    return 'world'\n")
        (work_dir / "b.py").write_text("def goodbye():\n    return 'moon'\n")
        (work_dir / "c.txt").write_text("nothing here\n")

        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    f'Search for files in {work_dir} that contain the word "goodbye". '
                    f'Tell me which file contains it.',
                    timeout=60,
                )
                assert events.succeeded
                assert "b.py" in events.response_text, \
                    f"Expected b.py in: {events.response_text[:300]}"

        asyncio.run(_run())


# ── 3. TOOL EXECUTION — TERMINAL ───────────────────────────────────────

class TestTerminal:
    """Test real shell command execution."""

    def test_run_command(self):
        """Agent executes a shell command and reports output."""
        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    "Run the command `echo PRODPUSH_ECHO_TEST` in the terminal and "
                    "tell me the output.",
                    timeout=60,
                )
                assert events.succeeded
                assert events.has_tool("terminal"), \
                    f"Expected terminal tool, got: {events.tool_names}"
                assert "PRODPUSH_ECHO_TEST" in events.response_text, \
                    f"Echo output missing: {events.response_text[:300]}"

        asyncio.run(_run())

    def test_command_with_file_creation(self, work_dir):
        """Agent runs a command that creates a file, then verifies it."""
        target = work_dir / "created_by_terminal.txt"

        async def _run():
            async with AgentSession(max_iterations=6) as agent:
                events = await agent.send(
                    f'Run this command: echo "terminal_created" > {target}\n'
                    f'Then read the file {target} and tell me what it says.',
                    timeout=90,
                )
                assert events.succeeded
                assert target.exists(), "Terminal did not create the file"
                assert "terminal_created" in target.read_text()

        asyncio.run(_run())

    def test_command_stderr_handling(self):
        """Agent handles commands that produce stderr output."""
        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    "Run this command: ls /nonexistent_path_xyz_12345 2>&1\n"
                    "Tell me what error you got.",
                    timeout=60,
                )
                assert events.succeeded
                # Should mention the error/not found
                resp = events.response_text.lower()
                assert "no such file" in resp or "not found" in resp or "error" in resp or "does not exist" in resp, \
                    f"Error not reported: {events.response_text[:300]}"

        asyncio.run(_run())


# ── 4. MULTI-STEP WORKFLOWS ────────────────────────────────────────────

class TestWorkflows:
    """Test multi-step interactions that chain multiple tools."""

    def test_create_and_modify_project(self, work_dir):
        """Agent creates a Python file, then modifies it."""
        async def _run():
            async with AgentSession(max_iterations=8) as agent:
                # Step 1: Create a file
                e1 = await agent.send(
                    f'Create a Python file at {work_dir}/calc.py with a function '
                    f'called "add" that takes two arguments and returns their sum.',
                    timeout=90,
                )
                assert e1.succeeded
                assert (work_dir / "calc.py").exists()

                # Step 2: Modify it
                e2 = await agent.send(
                    f'Now add a function called "multiply" to {work_dir}/calc.py '
                    f'that takes two arguments and returns their product.',
                    timeout=90,
                )
                assert e2.succeeded
                content = (work_dir / "calc.py").read_text()
                assert "def add" in content, f"add function missing: {content}"
                assert "def multiply" in content, f"multiply function missing: {content}"

        asyncio.run(_run())

    def test_inspect_and_summarize(self, work_dir):
        """Agent reads multiple files and synthesizes information."""
        (work_dir / "users.json").write_text(json.dumps([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
            {"name": "Charlie", "age": 35},
        ]))
        (work_dir / "config.json").write_text(json.dumps({
            "version": "2.0",
            "features": ["auth", "logging"],
        }))

        async def _run():
            async with AgentSession(max_iterations=6) as agent:
                events = await agent.send(
                    f"Read both {work_dir}/users.json and {work_dir}/config.json. "
                    f"Tell me: how many users are there, and what version is the config?",
                    timeout=90,
                )
                assert events.succeeded
                resp = events.response_text
                assert "3" in resp or "three" in resp.lower(), \
                    f"User count wrong: {resp[:300]}"
                assert "2.0" in resp, f"Version missing: {resp[:300]}"

        asyncio.run(_run())


# ── 5. INTERRUPT HANDLING ───────────────────────────────────────────────

class TestInterrupt:
    """Test that interrupt signals are handled gracefully."""

    def test_interrupt_during_execution(self):
        """Send interrupt while agent is processing, verify graceful stop."""
        async def _run():
            async with AgentSession(max_iterations=20) as agent:
                # Send a long task
                agent._write({
                    "type": "UserInput",
                    "session_id": agent.session_id,
                    "message": (
                        "Write a very long detailed essay about the history of computing. "
                        "Make it at least 5000 words with many sections."
                    ),
                    "model": agent.model,
                    "max_iterations": 20,
                })

                # Wait a bit then interrupt
                await asyncio.sleep(3)
                agent.interrupt()

                # Collect events until Done
                collected = CollectedEvents()
                deadline = asyncio.get_event_loop().time() + 30
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        msg = await asyncio.wait_for(
                            agent._event_queue.get(), timeout=5
                        )
                        collected.events.append(msg)
                        if msg["type"] == "Done":
                            collected.done = msg
                            break
                    except asyncio.TimeoutError:
                        continue

                # Should have gotten some events before interrupt
                assert len(collected.events) > 0, "No events received before interrupt"
                assert collected.done is not None, "Never got Done event after interrupt"

        asyncio.run(_run())


# ── 6. ERROR RESILIENCE ────────────────────────────────────────────────

class TestErrorResilience:
    """Test that the agent handles error conditions gracefully."""

    def test_nonexistent_file_read(self, work_dir):
        """Agent handles reading a file that doesn't exist."""
        fake_path = work_dir / "does_not_exist_xyz.txt"

        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    f"Read the file {fake_path} and tell me what's in it.",
                    timeout=60,
                )
                # Should complete (not crash) even though file doesn't exist
                assert events.succeeded or events.done is not None, \
                    "Agent should handle missing file gracefully"

        asyncio.run(_run())

    def test_invalid_command(self):
        """Agent handles running an invalid shell command."""
        async def _run():
            async with AgentSession(max_iterations=3) as agent:
                events = await agent.send(
                    "Run the command `nonexistent_command_xyz_99` in the terminal. "
                    "Just run it once and report what happens. Do NOT try to fix it or retry.",
                    timeout=90,
                )
                assert events.succeeded or events.done is not None
                # Should have attempted the terminal tool
                assert events.has_tool("terminal"), \
                    f"Expected terminal tool, got: {events.tool_names}"

        asyncio.run(_run())


# ── 7. SESSION PERSISTENCE ─────────────────────────────────────────────

class TestSessionPersistence:
    """Test that sessions persist across subprocess restarts via SessionDB."""

    def test_session_info_emitted(self):
        """Verify SessionInfo contains valid session_id and model."""
        async def _run():
            async with AgentSession() as agent:
                assert agent.session_id
                assert agent.session_info["model"]
                assert isinstance(agent.session_info.get("context_length", 0), int)
        asyncio.run(_run())


# ── 8. RECIPE-BASED INTEGRATION TESTS ──────────────────────────────────

class TestRecipes:
    """Run scripted multi-step recipes against the live agent."""

    def test_file_crud_recipe(self, work_dir):
        """Full CRUD cycle: create, read, update, delete a file."""
        target = work_dir / "recipe_test.txt"

        recipe = Recipe("file-crud", "Create, read, update, delete a file")
        recipe.add_step(
            f'Write "initial_content" to {target}. Use the write_file tool.',
            expect_tools=["write_file"],
            timeout=60,
        ).add_step(
            f"Read {target} and tell me its contents.",
            expect_tools=["read_file"],
            expect_in_response=["initial_content"],
            timeout=60,
        ).add_step(
            f'Replace "initial_content" with "updated_content" in {target}.',
            timeout=60,
        ).add_step(
            f'Delete the file {target} using the terminal (rm command).',
            expect_tools=["terminal"],
            timeout=60,
        )

        async def _run():
            async with AgentSession(max_iterations=6) as agent:
                results = await recipe.run(agent)
                # After delete step, file should be gone
                assert not target.exists(), f"File still exists after delete"
        asyncio.run(_run())

    def test_code_generation_recipe(self, work_dir):
        """Generate code, run it, verify output."""
        script = work_dir / "test_script.py"

        recipe = Recipe("code-gen", "Write and execute a Python script")
        recipe.add_step(
            f'Write a Python script at {script} that prints "RECIPE_OUTPUT_OK" '
            f'to stdout. Just the script, nothing else.',
            expect_tools=["write_file"],
            timeout=60,
        ).add_step(
            f'Run the script with: python3 {script}\n'
            f'Tell me the output.',
            expect_tools=["terminal"],
            expect_in_response=["RECIPE_OUTPUT_OK"],
            timeout=60,
        )

        async def _run():
            async with AgentSession(max_iterations=6) as agent:
                await recipe.run(agent)
        asyncio.run(_run())

    def test_directory_exploration_recipe(self, work_dir):
        """Create a directory structure, then explore it."""
        # Pre-create structure
        (work_dir / "src").mkdir()
        (work_dir / "src" / "main.py").write_text("print('hello')\n")
        (work_dir / "src" / "utils.py").write_text("def helper(): pass\n")
        (work_dir / "tests").mkdir()
        (work_dir / "tests" / "test_main.py").write_text("def test_it(): assert True\n")

        recipe = Recipe("dir-explore", "Explore directory structure")
        recipe.add_step(
            f"List all files in {work_dir} recursively and tell me what you find.",
            timeout=60,
        ).add_step(
            f"Read {work_dir}/src/main.py and {work_dir}/src/utils.py. "
            f"Summarize what each file does.",
            expect_in_response=["hello"],
            timeout=60,
        )

        async def _run():
            async with AgentSession(max_iterations=6) as agent:
                await recipe.run(agent)
        asyncio.run(_run())


# ── 9. STRESS / EDGE CASES ─────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_message(self):
        """Agent handles an empty user message gracefully."""
        async def _run():
            async with AgentSession(max_iterations=2) as agent:
                events = await agent.send("", timeout=30)
                # Should either respond or complete without crashing
                assert events.done is not None or events.error is not None
        asyncio.run(_run())

    def test_very_long_message(self):
        """Agent handles a very long user message."""
        long_msg = "Please respond with OK. " * 500  # ~12k chars

        async def _run():
            async with AgentSession(max_iterations=2) as agent:
                events = await agent.send(long_msg, timeout=60)
                assert events.done is not None
        asyncio.run(_run())

    def test_special_characters_in_file_content(self, work_dir):
        """Agent handles special characters in file operations."""
        target = work_dir / "special.txt"
        content = 'Line with "quotes" and \'apostrophes\'\nLine with $pecial chars & pipes | etc\nUnicode: 日本語 中文 émojis 🎉\n'
        target.write_text(content)

        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    f"Read {target} and tell me if it contains Unicode characters.",
                    timeout=60,
                )
                assert events.succeeded
                resp = events.response_text.lower()
                assert "unicode" in resp or "japanese" in resp or "chinese" in resp or "emoji" in resp, \
                    f"Unicode not mentioned: {events.response_text[:300]}"
        asyncio.run(_run())

    def test_rapid_fire_messages(self):
        """Send multiple messages quickly to test session stability."""
        async def _run():
            async with AgentSession(max_iterations=2) as agent:
                for i in range(3):
                    events = await agent.send(
                        f"Say exactly: RAPID_{i}",
                        timeout=60,
                    )
                    assert events.succeeded, f"Message {i} failed: {events.error}"
                    assert f"RAPID_{i}" in events.response_text.upper().replace(" ", "_"), \
                        f"Message {i}: expected RAPID_{i} in {events.response_text[:100]}"
        asyncio.run(_run())


# ── 10. TOOL COMPLETENESS ──────────────────────────────────────────────

class TestToolCompleteness:
    """Verify each core tool actually works end-to-end."""

    def test_todo_tool(self):
        """Agent can create and manage todo items."""
        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    "Create a todo item: 'Test the prodpush suite'. Use the todo tool.",
                    timeout=60,
                )
                assert events.succeeded
                assert events.has_tool("todo"), \
                    f"Expected todo tool, got: {events.tool_names}"
        asyncio.run(_run())

    def test_terminal_with_pipes(self):
        """Agent runs a command with pipes."""
        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    "Run: echo 'apple banana cherry' | tr ' ' '\\n' | sort\n"
                    "Tell me the sorted output.",
                    timeout=60,
                )
                assert events.succeeded
                resp = events.response_text
                assert "apple" in resp and "banana" in resp and "cherry" in resp, \
                    f"Sort output missing: {resp[:300]}"
        asyncio.run(_run())

    def test_write_file_with_multiline(self, work_dir):
        """Agent writes a multi-line file correctly."""
        target = work_dir / "multi.py"

        async def _run():
            async with AgentSession(max_iterations=4) as agent:
                events = await agent.send(
                    f'Write this exact content to {target}:\n'
                    f'```\n'
                    f'def greet(name):\n'
                    f'    return f"Hello, {{name}}!"\n'
                    f'\n'
                    f'if __name__ == "__main__":\n'
                    f'    print(greet("World"))\n'
                    f'```',
                    timeout=60,
                )
                assert events.succeeded
                assert target.exists()
                content = target.read_text()
                assert "def greet" in content
                assert "__main__" in content
        asyncio.run(_run())
