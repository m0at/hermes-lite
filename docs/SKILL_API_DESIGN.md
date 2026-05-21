# Model-as-a-Skill API Design for Hermes-Lite

## Core Principle

The LLM is not special. It is a skill like any other: it accepts typed inputs,
executes asynchronously, and returns typed outputs. The state machine calls it
via the same `SkillRegistry.invoke()` path it uses for `read_file` or `memory_search`.
This means the model can be swapped, mocked, batched, or rate-limited using the
same machinery as every other skill.

---

## 1. The Skill Protocol (Python)

```python
# skills/base.py

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Protocol, TypeVar, Generic

# ── Cost envelope ────────────────────────────────────────────────────────────

class RiskLevel(Enum):
    NONE   = "none"    # pure read, zero side-effects
    LOW    = "low"     # writes to local state only (DB, todo list)
    MEDIUM = "medium"  # touches the filesystem or spawns a process
    HIGH   = "high"    # network call, irreversible action, money

@dataclass(frozen=True)
class CostEstimate:
    tokens_in:  int        = 0      # prompt tokens consumed
    tokens_out: int        = 0      # completion tokens generated
    latency_ms: int        = 0      # expected wall-clock latency
    risk:       RiskLevel  = RiskLevel.NONE
    cacheable:  bool       = True   # result can be memoised

# ── Typed envelope for skill I/O ─────────────────────────────────────────────

I = TypeVar("I")   # input type
O = TypeVar("O")   # output type

@dataclass
class SkillInput(Generic[I]):
    params:     I
    session_id: str
    task_id:    str
    trace_id:   str   # propagated for distributed tracing / replay

@dataclass
class SkillOutput(Generic[O]):
    result:    O
    cost:      CostEstimate
    cached:    bool = False
    error:     str | None = None   # non-None → skill failed gracefully

# ── The Skill protocol ───────────────────────────────────────────────────────

class Skill(Protocol[I, O]):
    """Every skill — including the LLM itself — implements this interface."""

    name:        str
    description: str
    input_schema:  dict   # JSON Schema for I (used to generate tool definitions)
    output_schema: dict   # JSON Schema for O (used for output validation)

    def cost_estimate(self, params: I) -> CostEstimate:
        """Return an estimate *before* execution (no I/O allowed here)."""
        ...

    async def execute(self, inp: SkillInput[I]) -> SkillOutput[O]:
        """Execute the skill. Must not raise; encode errors in SkillOutput.error."""
        ...

    async def stream(self, inp: SkillInput[I]) -> AsyncIterator[bytes]:
        """Optional streaming variant. Default: buffer execute() and yield once."""
        result = await self.execute(inp)
        yield result.result if isinstance(result.result, bytes) else str(result.result).encode()
```

---

## 2. The Skill Registry

```python
# skills/registry.py

from __future__ import annotations
import asyncio
import time
from typing import Any, Dict, List, Optional, Type
from skills.base import Skill, SkillInput, SkillOutput, CostEstimate, RiskLevel


class SkillEntry:
    """Wrapper stored in the registry. Holds the skill instance plus metadata."""

    __slots__ = ("skill", "tags", "enabled")

    def __init__(self, skill: Skill, tags: list[str], enabled: bool = True):
        self.skill   = skill
        self.tags    = tags
        self.enabled = enabled


class SkillRegistry:
    """
    Central, process-wide skill registry.

    Responsibilities:
    - Register / deregister skills
    - Resolve tool call names → skill instances
    - Expose OpenAI-format function schemas for the model
    - Dispatch skill invocations with tracing + cost tracking
    - Support skill composition (chain execution)
    """

    def __init__(self):
        self._skills: Dict[str, SkillEntry] = {}
        self._invoke_count: Dict[str, int] = {}
        self._total_cost: Dict[str, CostEstimate] = {}

    # ── Registration ─────────────────────────────────────────────────────────

    def register(
        self,
        skill: Skill,
        tags: list[str] | None = None,
        enabled: bool = True,
    ) -> None:
        self._skills[skill.name] = SkillEntry(skill, tags or [], enabled)

    def enable(self, name: str)  -> None: self._skills[name].enabled = True
    def disable(self, name: str) -> None: self._skills[name].enabled = False

    # ── Schema exposure (for LLM tool definitions) ───────────────────────────

    def tool_definitions(self, tags: list[str] | None = None) -> list[dict]:
        """Return OpenAI-format tool definitions, optionally filtered by tag."""
        out = []
        for entry in self._skills.values():
            if not entry.enabled:
                continue
            if tags and not any(t in entry.tags for t in tags):
                continue
            out.append({
                "type": "function",
                "function": {
                    "name":        entry.skill.name,
                    "description": entry.skill.description,
                    "parameters":  entry.skill.input_schema,
                },
            })
        return out

    def cost_summary(self, name: str) -> dict:
        """Aggregate cost for a skill across all invocations in this session."""
        c = self._total_cost.get(name)
        if not c:
            return {"invocations": 0}
        return {
            "invocations": self._invoke_count.get(name, 0),
            "tokens_in":   c.tokens_in,
            "tokens_out":  c.tokens_out,
        }

    # ── Invocation ───────────────────────────────────────────────────────────

    async def invoke(
        self,
        name: str,
        params: Any,
        session_id: str,
        task_id: str = "default",
        trace_id: str | None = None,
    ) -> SkillOutput:
        entry = self._skills.get(name)
        if entry is None:
            return SkillOutput(result=None, cost=CostEstimate(),
                               error=f"Unknown skill: {name}")
        if not entry.enabled:
            return SkillOutput(result=None, cost=CostEstimate(),
                               error=f"Skill disabled: {name}")

        import uuid
        inp = SkillInput(
            params=params,
            session_id=session_id,
            task_id=task_id,
            trace_id=trace_id or str(uuid.uuid4()),
        )

        t0 = time.monotonic()
        out = await entry.skill.execute(inp)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # Accumulate cost
        n = self._invoke_count.get(name, 0) + 1
        self._invoke_count[name] = n
        prev = self._total_cost.get(name, CostEstimate())
        self._total_cost[name] = CostEstimate(
            tokens_in  = prev.tokens_in  + out.cost.tokens_in,
            tokens_out = prev.tokens_out + out.cost.tokens_out,
            latency_ms = elapsed_ms,
        )
        return out

    # ── Composition: sequential chain ────────────────────────────────────────

    async def chain(
        self,
        steps: list[tuple[str, Any]],   # [(skill_name, params), ...]
        session_id: str,
        task_id: str = "default",
    ) -> list[SkillOutput]:
        """
        Execute skills sequentially.  Each step receives the previous step's
        result injected into its params under the key "previous_result".
        """
        results = []
        previous = None
        for name, params in steps:
            if previous is not None and isinstance(params, dict):
                params = {**params, "previous_result": previous}
            out = await self.invoke(name, params, session_id, task_id)
            results.append(out)
            if out.error:
                break   # abort chain on first error
            previous = out.result
        return results

    # ── Composition: parallel fan-out ────────────────────────────────────────

    async def fan_out(
        self,
        calls: list[tuple[str, Any]],   # [(skill_name, params), ...]
        session_id: str,
        task_id: str = "default",
    ) -> list[SkillOutput]:
        """Execute multiple independent skills concurrently."""
        tasks = [
            self.invoke(name, params, session_id, task_id)
            for name, params in calls
        ]
        return list(await asyncio.gather(*tasks))


# Module-level singleton — mirrors the pattern in tools/registry.py
skill_registry = SkillRegistry()
```

---

## 3. The Model Skill (LLM as a Skill)

```python
# skills/model_skill.py

from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from skills.base import Skill, SkillInput, SkillOutput, CostEstimate, RiskLevel


# ── Input / Output types ─────────────────────────────────────────────────────

@dataclass
class ModelParams:
    """Input parameters for a model invocation."""
    messages:        list[dict]           # OpenAI-format conversation history
    tools:           list[dict] | None    # tool definitions to expose (None = all)
    model:           str = ""             # override; empty = use agent's default
    temperature:     float = 0.6
    max_tokens:      int = 8192
    # Pre-call skill declaration (see §4): model asserts which skills it will need
    declared_skills: list[str] = field(default_factory=list)

@dataclass
class ModelOutput:
    """Output from a model invocation."""
    text:          str | None          # final text response (if any)
    tool_calls:    list[dict]          # [{id, name, arguments}, ...]
    finish_reason: str                 # "stop" | "tool_calls" | "length"
    usage:         dict                # {prompt_tokens, completion_tokens, total_tokens}


# ── Skill implementation ─────────────────────────────────────────────────────

class ModelSkill:
    """
    The LLM is a skill.

    Wraps an OpenAI-compatible client. The state machine invokes this skill
    exactly like it invokes read_file or memory_search — no special casing.
    """

    name        = "model"
    description = (
        "Invoke the primary language model with a conversation history and "
        "tool definitions. Returns either a text response or a list of tool "
        "calls to dispatch."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "messages":        {"type": "array"},
            "tools":           {"type": ["array", "null"]},
            "model":           {"type": "string"},
            "temperature":     {"type": "number"},
            "max_tokens":      {"type": "integer"},
            "declared_skills": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["messages"],
    }

    output_schema = {
        "type": "object",
        "properties": {
            "text":          {"type": ["string", "null"]},
            "tool_calls":    {"type": "array"},
            "finish_reason": {"type": "string"},
            "usage":         {"type": "object"},
        },
    }

    def __init__(self, client, default_model: str):
        self._client        = client
        self._default_model = default_model

    def cost_estimate(self, params: ModelParams) -> CostEstimate:
        # Rough pre-call estimate only — actual usage comes from API response
        total_chars = sum(len(str(m)) for m in params.messages)
        est_in = total_chars // 4
        return CostEstimate(
            tokens_in  = est_in,
            tokens_out = params.max_tokens // 4,  # conservative
            latency_ms = 5000,
            risk       = RiskLevel.LOW,
            cacheable  = False,
        )

    async def execute(self, inp: SkillInput[ModelParams]) -> SkillOutput[ModelOutput]:
        p = inp.params
        model = p.model or self._default_model

        kwargs = dict(
            model       = model,
            messages    = p.messages,
            temperature = p.temperature,
            max_tokens  = p.max_tokens,
        )
        if p.tools:
            kwargs["tools"] = p.tools

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            return SkillOutput(
                result = ModelOutput(text=None, tool_calls=[], finish_reason="error", usage={}),
                cost   = CostEstimate(),
                error  = str(exc),
            )

        choice  = response.choices[0]
        message = choice.message
        usage   = response.usage.__dict__ if hasattr(response, "usage") else {}

        # Normalise tool calls to {id, name, arguments} dicts
        raw_calls = getattr(message, "tool_calls", None) or []
        tool_calls = [
            {
                "id":        tc.id,
                "name":      tc.function.name,
                "arguments": json.loads(tc.function.arguments or "{}"),
            }
            for tc in raw_calls
        ]

        result = ModelOutput(
            text          = message.content,
            tool_calls    = tool_calls,
            finish_reason = choice.finish_reason or "stop",
            usage         = usage,
        )

        cost = CostEstimate(
            tokens_in  = usage.get("prompt_tokens", 0),
            tokens_out = usage.get("completion_tokens", 0),
            latency_ms = 0,    # filled in by registry
            risk       = RiskLevel.NONE,
            cacheable  = False,
        )

        return SkillOutput(result=result, cost=cost)

    async def stream(self, inp: SkillInput[ModelParams]) -> AsyncIterator[bytes]:
        """
        Streaming variant.  Yields raw token bytes.  Tool calls are buffered
        and emitted as a single JSON chunk with key "tool_calls" at the end.
        """
        p = inp.params
        model = p.model or self._default_model

        kwargs = dict(
            model=model, messages=p.messages, temperature=p.temperature,
            max_tokens=p.max_tokens, stream=True,
        )
        if p.tools:
            kwargs["tools"] = p.tools

        response = await self._client.chat.completions.create(**kwargs)

        tool_call_acc: dict[int, dict] = {}
        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue
            if delta.content:
                yield delta.content.encode()
            for tc_chunk in (delta.tool_calls or []):
                idx = tc_chunk.index
                if idx not in tool_call_acc:
                    tool_call_acc[idx] = {"id": tc_chunk.id or "", "name": "", "arguments": ""}
                if tc_chunk.function:
                    tool_call_acc[idx]["name"]      += tc_chunk.function.name or ""
                    tool_call_acc[idx]["arguments"] += tc_chunk.function.arguments or ""

        if tool_call_acc:
            calls = []
            for tc in tool_call_acc.values():
                try:
                    tc["arguments"] = json.loads(tc["arguments"])
                except json.JSONDecodeError:
                    pass
                calls.append(tc)
            yield json.dumps({"tool_calls": calls}).encode()
```

---

## 4. Memory Skill

```python
# skills/memory_skill.py

from __future__ import annotations
import json
import time
from dataclasses import dataclass
from typing import Any

from skills.base import Skill, SkillInput, SkillOutput, CostEstimate, RiskLevel
from hermes_state import SessionDB


# ── Working memory record ────────────────────────────────────────────────────

@dataclass
class WorkingMemory:
    """Ephemeral, in-process working memory for a single session."""
    open_files:      list[str]   = None   # files read/written this turn
    recent_commands: list[str]   = None   # last N terminal commands
    todo_snapshot:   list[dict]  = None   # current todo list
    context_usage:   dict        = None   # {used_tokens, limit, pct}

    def __post_init__(self):
        self.open_files      = self.open_files or []
        self.recent_commands = self.recent_commands or []
        self.todo_snapshot   = self.todo_snapshot or []
        self.context_usage   = self.context_usage or {}


# ── Input types ──────────────────────────────────────────────────────────────

@dataclass
class MemoryReadParams:
    query:        str | None = None   # FTS5 query; None → return working memory only
    role_filter:  list[str]  = None   # e.g. ["assistant", "tool"]
    limit:        int        = 10
    include_working: bool    = True

@dataclass
class MemoryWriteParams:
    content:  str             # text to store
    role:     str = "system"  # stored role label (e.g. "memory", "system")

@dataclass
class MemoryResult:
    working_memory:   WorkingMemory
    search_hits:      list[dict]    # FTS5 result rows


# ── The Memory Skill ─────────────────────────────────────────────────────────

class MemorySkill:
    """
    Read/write access to the session DB and working memory.

    Read path:  FTS5 search over all past messages + current working memory
    Write path: Persist a note into the current session's message history
                (role="memory") so it survives context compression.
    """

    name        = "memory"
    description = (
        "Access persistent memory. "
        "Read: FTS5 search over all past sessions + current working memory "
        "(open files, recent commands, todo list). "
        "Write: store a note that persists across context compression."
    )

    input_schema = {
        "type": "object",
        "oneOf": [
            {
                "properties": {
                    "action":        {"const": "read"},
                    "query":         {"type": "string"},
                    "role_filter":   {"type": "array", "items": {"type": "string"}},
                    "limit":         {"type": "integer", "default": 10},
                    "include_working": {"type": "boolean", "default": True},
                },
                "required": ["action"],
            },
            {
                "properties": {
                    "action":  {"const": "write"},
                    "content": {"type": "string"},
                    "role":    {"type": "string", "default": "memory"},
                },
                "required": ["action", "content"],
            },
        ],
    }

    output_schema = {
        "type": "object",
        "properties": {
            "working_memory": {"type": "object"},
            "search_hits":    {"type": "array"},
            "stored":         {"type": "boolean"},
        },
    }

    def __init__(self, db: SessionDB, working_mem: WorkingMemory):
        self._db  = db
        self._wm  = working_mem

    def cost_estimate(self, params) -> CostEstimate:
        return CostEstimate(
            tokens_in=0, tokens_out=300, latency_ms=20,
            risk=RiskLevel.NONE if params.get("action") == "read" else RiskLevel.LOW,
        )

    async def execute(self, inp: SkillInput) -> SkillOutput:
        params = inp.params
        action = params.get("action", "read")

        if action == "write":
            content = params.get("content", "")
            role    = params.get("role", "memory")
            self._db.append_message(
                session_id = inp.session_id,
                role       = role,
                content    = content,
            )
            return SkillOutput(
                result = {"stored": True, "content": content[:80] + "..."},
                cost   = CostEstimate(risk=RiskLevel.LOW),
            )

        # action == "read"
        hits = []
        query = params.get("query")
        if query:
            hits = self._db.search_messages(
                query       = query,
                role_filter = params.get("role_filter"),
                limit       = params.get("limit", 10),
            )

        result = MemoryResult(
            working_memory = self._wm if params.get("include_working", True) else WorkingMemory(),
            search_hits    = hits,
        )

        return SkillOutput(
            result = {
                "working_memory": {
                    "open_files":      result.working_memory.open_files,
                    "recent_commands": result.working_memory.recent_commands[-5:],
                    "todo_snapshot":   result.working_memory.todo_snapshot,
                    "context_usage":   result.working_memory.context_usage,
                },
                "search_hits": hits,
            },
            cost = CostEstimate(tokens_out=len(hits) * 50),
        )
```

---

## 5. Context Skill

```python
# skills/context_skill.py

from __future__ import annotations
from dataclasses import dataclass
from skills.base import Skill, SkillInput, SkillOutput, CostEstimate, RiskLevel


@dataclass
class ContextParams:
    action: str = "status"   # "status" | "compress"

class ContextSkill:
    """
    Expose context window usage to the model and let it trigger compression.
    """

    name        = "context"
    description = (
        "Inspect or manage the context window. "
        "action='status': returns token usage, limit, and compression count. "
        "action='compress': triggers immediate context compression."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "compress"]},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "used_tokens":       {"type": "integer"},
            "context_length":    {"type": "integer"},
            "usage_pct":         {"type": "number"},
            "compression_count": {"type": "integer"},
            "compressed":        {"type": "boolean"},
        },
    }

    def __init__(self, compressor):
        self._compressor = compressor

    def cost_estimate(self, params) -> CostEstimate:
        if params.get("action") == "compress":
            return CostEstimate(tokens_in=500, tokens_out=2500, latency_ms=3000, risk=RiskLevel.LOW)
        return CostEstimate()

    async def execute(self, inp: SkillInput) -> SkillOutput:
        action = inp.params.get("action", "status")
        status = self._compressor.get_status()

        if action == "compress":
            # Compression is synchronous in the current impl; wrap in executor
            import asyncio
            loop = asyncio.get_event_loop()
            # compressor.compress() is called by the state machine after this
            # returns — we signal intent here, execution happens in the loop
            return SkillOutput(
                result = {**status, "compressed": True, "note": "compression queued"},
                cost   = CostEstimate(tokens_in=500, tokens_out=2500, risk=RiskLevel.LOW),
            )

        return SkillOutput(
            result = {**status, "compressed": False},
            cost   = CostEstimate(),
        )
```

---

## 6. Session Skill

```python
# skills/session_skill.py

from __future__ import annotations
from dataclasses import dataclass
from skills.base import Skill, SkillInput, SkillOutput, CostEstimate
from hermes_state import SessionDB


class SessionSkill:
    """
    Give the model read-only access to session metadata.
    Useful for multi-session orchestration and resume logic.
    """

    name        = "session"
    description = (
        "Get current session metadata (id, start time, token counts) or "
        "list recent sessions for cross-session context."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["current", "list"]},
            "limit":  {"type": "integer", "default": 5},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "session_id":    {"type": "string"},
            "model":         {"type": "string"},
            "started_at":    {"type": "number"},
            "input_tokens":  {"type": "integer"},
            "output_tokens": {"type": "integer"},
            "sessions":      {"type": "array"},
        },
    }

    def __init__(self, db: SessionDB, session_id: str):
        self._db         = db
        self._session_id = session_id

    def cost_estimate(self, params) -> CostEstimate:
        return CostEstimate(tokens_out=100)

    async def execute(self, inp: SkillInput) -> SkillOutput:
        action = inp.params.get("action", "current")

        if action == "list":
            sessions = self._db.search_sessions(limit=inp.params.get("limit", 5))
            return SkillOutput(result={"sessions": sessions}, cost=CostEstimate())

        session = self._db.get_session(self._session_id) or {}
        return SkillOutput(result=session, cost=CostEstimate())
```

---

## 7. Pre-Call Skill Declaration & Context Injection

When the model declares `declared_skills` in its `ModelParams`, the state machine
performs pre-emptive context injection *before* the model call:

```python
# agent/skill_prefetch.py

from __future__ import annotations
import json
from skills.registry import SkillRegistry
from skills.memory_skill import WorkingMemory


PREFETCH_MAP = {
    # declared_skill name   → (registry_skill, params)
    "memory":   ("memory",  {"action": "read", "include_working": True}),
    "file":     None,   # no prefetch; file paths aren't known yet
    "terminal": None,
    "todo":     ("memory",  {"action": "read", "include_working": True}),
    "context":  ("context", {"action": "status"}),
    "session":  ("session", {"action": "current"}),
}


async def build_prefetch_context(
    declared: list[str],
    registry: SkillRegistry,
    session_id: str,
    task_id: str,
) -> str:
    """
    Run pre-emptive skill reads based on the model's declared intent.
    Returns a formatted context block to prepend to the next user turn.
    """
    blocks = []
    seen   = set()

    for decl in declared:
        mapping = PREFETCH_MAP.get(decl)
        if mapping is None or decl in seen:
            continue
        seen.add(decl)

        skill_name, params = mapping
        out = await registry.invoke(skill_name, params, session_id, task_id)
        if out.error:
            continue

        blocks.append(f"<{decl}_context>\n{json.dumps(out.result, indent=2)}\n</{decl}_context>")

    if not blocks:
        return ""
    return "\n\n[Pre-fetched context for declared skills]\n" + "\n".join(blocks)
```

---

## 8. State Machine Integration

The agent loop becomes a flat dispatch table. Nothing is special-cased.

```python
# agent/loop.py  (conceptual replacement for the inner loop in run_agent.py)

from __future__ import annotations
import asyncio
import json
from skills.registry  import skill_registry
from skills.model_skill import ModelParams, ModelOutput


class AgentLoop:
    """
    State machine over skill invocations.

    States:
        IDLE      → waiting for user input
        THINKING  → model skill running
        ACTING    → one or more tool skills running (parallel fan-out)
        DONE      → model returned stop, no pending tool calls
    """

    def __init__(
        self,
        session_id: str,
        task_id: str,
        max_iterations: int = 60,
    ):
        self.session_id     = session_id
        self.task_id        = task_id
        self.max_iterations = max_iterations
        self.messages: list[dict] = []
        self._iteration = 0

    async def run(self, user_message: str) -> str:
        self.messages.append({"role": "user", "content": user_message})

        while self._iteration < self.max_iterations:
            self._iteration += 1

            # ── THINKING ─────────────────────────────────────────────────────
            model_out = await skill_registry.invoke(
                name       = "model",
                params     = ModelParams(
                    messages = self.messages,
                    tools    = skill_registry.tool_definitions(tags=["agent"]),
                ),
                session_id = self.session_id,
                task_id    = self.task_id,
            )
            if model_out.error:
                return f"[model error] {model_out.error}"

            result: ModelOutput = model_out.result
            self._append_assistant(result)

            if result.finish_reason == "stop":
                return result.text or ""

            if not result.tool_calls:
                return result.text or ""

            # ── ACTING (parallel fan-out) ─────────────────────────────────────
            skill_calls = [
                (tc["name"], tc["arguments"])
                for tc in result.tool_calls
            ]
            outcomes = await skill_registry.fan_out(
                skill_calls, self.session_id, self.task_id
            )

            for tc, out in zip(result.tool_calls, outcomes):
                content = json.dumps(out.result) if out.result is not None else out.error or ""
                self.messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "name":         tc["name"],
                    "content":      content,
                })

        return "[max iterations reached]"

    def _append_assistant(self, result: ModelOutput):
        msg: dict = {"role": "assistant"}
        if result.text:
            msg["content"] = result.text
        if result.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                }
                for tc in result.tool_calls
            ]
        self.messages.append(msg)
```

---

## 9. Skill Composition Patterns

### 9.1 Sequential Chain (model-directed)

The model emits a `chain` tool call listing skills in order:

```json
{
  "name": "chain",
  "arguments": {
    "steps": [
      {"skill": "memory", "params": {"action": "read", "query": "docker deployment"}},
      {"skill": "read_file", "params": {"path": "Dockerfile"}},
      {"skill": "terminal", "params": {"command": "docker build -t app ."}}
    ]
  }
}
```

The `ChainSkill` wraps `SkillRegistry.chain()`:

```python
# skills/chain_skill.py

from skills.base import Skill, SkillInput, SkillOutput, CostEstimate
from skills.registry import skill_registry


class ChainSkill:
    name        = "chain"
    description = (
        "Execute multiple skills in sequence, passing each result to the next. "
        "Use when skills have a strict dependency order."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "skill":  {"type": "string"},
                        "params": {"type": "object"},
                    },
                    "required": ["skill"],
                },
            },
        },
        "required": ["steps"],
    }

    output_schema = {
        "type": "array",
        "items": {"type": "object"},
    }

    def cost_estimate(self, params) -> CostEstimate:
        return CostEstimate(latency_ms=len(params.get("steps", [])) * 200)

    async def execute(self, inp: SkillInput) -> SkillOutput:
        steps = [(s["skill"], s.get("params", {})) for s in inp.params.get("steps", [])]
        results = await skill_registry.chain(steps, inp.session_id, inp.task_id)
        return SkillOutput(
            result = [{"skill": s[0], "result": r.result, "error": r.error}
                      for s, r in zip(steps, results)],
            cost   = CostEstimate(),
        )
```

### 9.2 Parallel Fan-Out (model-directed)

The model emits a `fan_out` tool call when steps are independent:

```json
{
  "name": "fan_out",
  "arguments": {
    "calls": [
      {"skill": "search_files", "params": {"pattern": "TODO", "target": "content"}},
      {"skill": "memory",       "params": {"action": "read", "query": "known issues"}},
      {"skill": "todo",         "params": {}}
    ]
  }
}
```

### 9.3 Skill-of-Skills (meta-skill)

The model can invoke `model` as a sub-skill to run a cheaper/faster model for a
sub-task and inject the result back into its own context:

```json
{
  "name": "model",
  "arguments": {
    "model": "qwen/qwen3.5-4b",
    "messages": [
      {"role": "user", "content": "Summarise this diff in 3 bullet points:\n<diff>..."}
    ],
    "declared_skills": []
  }
}
```

The outer (large) model delegates to the inner (small) model, which is just
another `skill_registry.invoke("model", ...)` call.

---

## 10. Hypereffective Context Injection

The richest possible context the model receives is assembled from:

| Source | When injected | Format |
|--------|--------------|--------|
| `WorkingMemory.open_files` | Every turn | `<open_files>` XML block |
| `WorkingMemory.recent_commands` | Every turn | `<recent_commands>` block |
| `WorkingMemory.todo_snapshot` | Every turn (if non-empty) | `<todos>` block |
| `WorkingMemory.context_usage` | Every turn | `<context>` block |
| FTS5 search hits | When model declares "memory" | `<memory_hits>` block |
| Session metadata | When model declares "session" | `<session>` block |
| AGENTS.md / SOUL.md | System prompt, once | Already in `prompt_builder.py` |
| Skills index | System prompt, once | `<available_skills>` block |

The format is compact, XML-tagged, and injected as a system turn prepended to the
last user message — never as a separate system message (which breaks caching):

```python
# agent/context_injector.py

def build_rich_context(wm: WorkingMemory, prefetch: str) -> str:
    """
    Build the <hermes_context> block injected before every model call.
    Keeps each section only when non-empty to avoid token waste.
    """
    parts = ["<hermes_context>"]

    if wm.context_usage:
        u = wm.context_usage
        pct = u.get("usage_pct", 0)
        parts.append(
            f"<context_window used='{u.get('used_tokens', 0)}' "
            f"limit='{u.get('context_length', 0)}' pct='{pct:.1f}'/>"
        )

    if wm.todo_snapshot:
        lines = "\n".join(
            f"  [{t['status'][0].upper()}] {t['id']}: {t['content']}"
            for t in wm.todo_snapshot
        )
        parts.append(f"<todos>\n{lines}\n</todos>")

    if wm.open_files:
        parts.append(f"<open_files>{', '.join(wm.open_files[-8:])}</open_files>")

    if wm.recent_commands:
        cmds = "\n".join(f"  $ {c}" for c in wm.recent_commands[-5:])
        parts.append(f"<recent_commands>\n{cmds}\n</recent_commands>")

    parts.append("</hermes_context>")

    block = "\n".join(parts)
    if prefetch:
        block = block + "\n" + prefetch
    return block
```

---

## 11. Mapping Existing Tools to Skills

Every existing `registry.register()` call maps 1-to-1 to a `skill_registry.register()`.
The migration is mechanical and preserves the JSON schema:

```python
# Migration shim in model_tools.py (no changes to tool files needed)

from skills.registry  import skill_registry
from skills.base      import CostEstimate, RiskLevel
from tools.registry   import registry as tool_registry
import asyncio, json


def _wrap_tool_as_skill(entry):
    """Wrap a legacy ToolEntry as a Skill-compatible object."""

    class WrappedSkill:
        name         = entry.name
        description  = entry.description
        input_schema = entry.schema.get("parameters", {})
        output_schema = {"type": "object"}

        def cost_estimate(self, params):
            risk = RiskLevel.MEDIUM if entry.name == "terminal" else RiskLevel.NONE
            return CostEstimate(risk=risk, latency_ms=100)

        async def execute(self, inp):
            args = inp.params if isinstance(inp.params, dict) else {}
            if entry.is_async:
                result = await entry.handler(args, task_id=inp.task_id)
            else:
                result = entry.handler(args, task_id=inp.task_id)
            return __import__("skills.base", fromlist=["SkillOutput"]).SkillOutput(
                result=result, cost=CostEstimate(),
            )

    return WrappedSkill()


def migrate_tool_registry_to_skill_registry():
    for name, entry in tool_registry._tools.items():
        skill = _wrap_tool_as_skill(entry)
        tags  = ["agent", entry.toolset]
        skill_registry.register(skill, tags=tags)
```

---

## 12. Example: Model Calling Each Skill Type

### Memory read before answering

```python
# Model turn 1 — declares memory intent
ModelParams(
    messages=[{"role": "user", "content": "How did we set up the Nginx reverse proxy last week?"}],
    declared_skills=["memory"],   # triggers pre-fetch
)
# → prefetch injects FTS5 hits for "nginx reverse proxy" into next user turn

# Model sees:
# <memory_hits>
#   [session 2026-02-28] [assistant] We set AllowEncodedSlashes NoDecode and
#   proxy_pass http://127.0.0.1:8080 for the FastAPI backend...
# </memory_hits>
```

### Parallel file + search + memory

```json
{
  "name": "fan_out",
  "arguments": {
    "calls": [
      {"skill": "read_file",    "params": {"path": "/app/config.yaml"}},
      {"skill": "search_files", "params": {"pattern": "REDIS_URL", "target": "content"}},
      {"skill": "memory",       "params": {"action": "read", "query": "redis config"}}
    ]
  }
}
```

### Sub-model for cheap summarisation

```json
{
  "name": "model",
  "arguments": {
    "model": "local/qwen3.5-9b",
    "temperature": 0.2,
    "messages": [
      {"role": "user", "content": "Summarise this test output in one sentence:\n<output>...</output>"}
    ]
  }
}
```

### Context check before large operation

```json
{"name": "context", "arguments": {"action": "status"}}
// → {"used_tokens": 145000, "context_length": 200000, "usage_pct": 72.5, ...}
// Model decides: safe to proceed without compressing
```

### Session resume

```json
{"name": "session", "arguments": {"action": "list", "limit": 3}}
// → [{id, started_at, model, input_tokens, output_tokens}, ...]
// Model picks the relevant session_id and calls:
{"name": "memory", "arguments": {"action": "read", "query": "refactor", "limit": 20}}
```

### Writing a memory note

```json
{
  "name": "memory",
  "arguments": {
    "action": "write",
    "content": "User prefers pytest over unittest. Uses Poetry for dependency management.",
    "role": "memory"
  }
}
```

---

## 13. Integration Path (no flag-day rewrite)

The design is additive. The existing `ToolRegistry` continues to work unchanged.
The migration is three steps:

1. **Add `skills/` package** alongside `tools/` — pure new code, no changes to existing files.
2. **Run migration shim** in `model_tools.py` — wraps every `ToolEntry` as a `Skill` object and registers it in `skill_registry`. Zero changes to individual tool files.
3. **Swap the agent loop** in `run_agent.py` — replace the inner `while` loop with `AgentLoop.run()`. The outer class, CLI, config, and prompt assembly are all untouched.

The model skill (`ModelSkill`) wraps the same `agent.llm_client.completion` entry point already used in `run_agent.py` (Anthropic SDK for Claude, OpenAI SDK for OpenAI-compatible endpoints). The `ContextCompressor`, `SessionDB`, `TodoStore`, and `WorkingMemory` instances become constructor arguments to the skill classes — dependency injection, no globals beyond the registry singleton.
