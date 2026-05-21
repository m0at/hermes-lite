# Litellm removal spec

litellm is being removed from every codepath. Replacement is the official
`anthropic` Python SDK (already in requirements). Only Claude models are
served via this path — no multi-provider routing.

## Shim contract

A single module, `agent/anthropic_shim.py`, exposes one entry point:

```python
def completion(*, model, messages, tools=None, tool_choice=None,
               temperature=None, max_tokens=None, stream=False,
               api_key=None, base_url=None, extra_headers=None,
               on_token=None, on_tool_call_delta=None,
               thinking=None, **_ignored) -> ModelResponse
```

It accepts OpenAI-shaped `messages` and `tools` (the shape callers already
build) and returns an object whose attribute access is the same shape callers
already consume from litellm:

- `.choices[0].message.role`
- `.choices[0].message.content` (str | None)
- `.choices[0].message.tool_calls` (list[ToolCall] | None)
- `.choices[0].finish_reason` (str)
- `.usage` (object with prompt_tokens / completion_tokens / total_tokens)
- `.model` (str)

Each `ToolCall` exposes `.id`, `.type == "function"`,
`.function.name`, `.function.arguments` (JSON string).

## Input mapping

OpenAI → Anthropic translation done inside the shim:

- Strip leading `{"role":"system", ...}` into top-level `system=...`.
- `{"role":"user","content": str|list}` → user message (list content
  passes through; str wraps to `[{"type":"text","text":...}]`).
- `{"role":"assistant", "content": str, "tool_calls": [...]}` → assistant
  message with mixed `text` and `tool_use` blocks. Each tool_call becomes
  `{"type":"tool_use","id":id,"name":fn.name,"input":json.loads(fn.arguments)}`.
- `{"role":"tool","tool_call_id":id,"content":...}` → user message with a
  single `{"type":"tool_result","tool_use_id":id,"content":...}` block.
  Adjacent tool messages are merged into one user turn.
- `tools=[{"type":"function","function":{"name","description","parameters"}}]`
  → `tools=[{"name","description","input_schema":parameters}]`.
- `tool_choice="auto" | "required" | {"type":"function","function":{"name":N}}`
  → `tool_choice={"type":"auto"|"any"|"tool", "name":...}`.
- `max_tokens` defaults to a sane bound (8192) if caller passes None — the
  Anthropic API requires it.

## Streaming

When `stream=True`, the shim uses `client.messages.stream(...)`. It iterates
events and:
- emits text deltas via `on_token(token)` callback,
- emits tool-call deltas via `on_tool_call_delta(index, name_delta, args_delta)`,
- accumulates final content and returns the same `ModelResponse` shape as
  the non-streaming path. Callers don't branch.

## Prompt caching

The existing runtime detects Claude models and enables prompt caching. The
shim sets `cache_control={"type":"ephemeral"}` on the system block and on the
last two user blocks (Anthropic's documented pattern) when the caller passes
`enable_prompt_caching=True` via `**kwargs`. No change to caller logic.

## Extended thinking

If `thinking={"type":"enabled","budget_tokens":N}` is passed, it's forwarded
unchanged. Reasoning content arrives as `thinking` blocks; the shim drops
them from `.content` (text only) but exposes them via
`.choices[0].message.reasoning_content` for callers that read it.

## What's gone

- `import litellm` — every call site.
- `litellm.completion(**kwargs)` — replaced by `anthropic_shim.completion(...)`.
- `litellm.drop_params / modify_params / suppress_debug_info` — irrelevant.
- All references in `requirements.txt`, `pyproject.toml`, docs, Dockerfile.
- `vendor/mini-swe-agent/src/minisweagent/models/litellm*.py` and
  related tests/docs (kept env classes only — they're imported by
  hermes-lite tools).

## Failure mode

If `ANTHROPIC_API_KEY` is missing or invalid, the shim raises
`anthropic.AuthenticationError` immediately. No silent fallback. No retry
to a different provider. (Per project policy: no fallbacks in agent paths.)
