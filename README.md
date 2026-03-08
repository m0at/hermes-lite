# hermes-lite

A local-first coding agent CLI for macOS, built on top of [Hermes](https://github.com/NousResearch) by **Nous Research**.

hermes-lite takes the open-source Hermes Agent, strips it down to a focused Mac coding tool, then extends it with Rust-accelerated internals, a native TUI, and a live integration test suite.

---

**Demo:** Hands-on scenarios, sample project, and automation scripts in [`demo/`](demo/README.md).

---

## What This Is

hermes-lite is a **fork** of the Hermes Agent project by [Nous Research](https://nousresearch.com). The original Hermes is a full-featured AI agent platform with web search, browser automation, vision, messaging integrations, and reinforcement learning.

hermes-lite removes all of that and keeps only what matters for a local coding agent: terminal execution, file operations, and a planning loop. On top of that inherited base, we added:

- A **Rust FSM** replacing the Python conversation loop
- A **Rust SessionDB** replacing the Python SQLite layer
- A **native ratatui TUI** with multi-agent panes, @mentions, and inter-agent routing
- A **prodpush integration test suite** that drives the agent end-to-end with real LLM calls

---

## Inherited vs New

This table is the ground truth for what came from where.

### Inherited from Nous Research / Hermes

| Component | File(s) | What it does |
|-----------|---------|--------------|
| Agent conversation loop | `run_agent.py` (~4900 lines) | Core engine — LLM calls via litellm, tool dispatch, streaming, parallel tool execution |
| Interactive CLI | `cli.py` (~3500 lines) | prompt_toolkit REPL, 23 slash commands, session management |
| Tool system | `tools/` (12 modules) | Terminal execution, file ops, todo planning, clarify prompts, approval, process management |
| Tool dispatch | `model_tools.py` | Schema generation (OpenAI format), function call routing |
| Toolset groupings | `toolsets.py` | Named tool bundles (terminal, file, todo, clarify) |
| System prompt assembly | `agent/prompt_builder.py` | AGENTS.md/SOUL.md/.cursorrules scanning, prompt injection detection |
| Prompt caching | `agent/prompt_caching.py` | Anthropic cache_control (system_and_3 strategy) |
| Context compression | `agent/context_compressor.py` | Auto-summarization at 85% of context window |
| Model capabilities | `agent/model_capabilities.py` | Feature detection per model |
| Model metadata | `agent/model_metadata.py` | Context lengths for 26 models, hourly Anthropic metadata fetch |
| Session persistence | `hermes_state.py` | Python SQLite backend with FTS5 search |
| Config system | `hermes_cli/` (14 modules) | YAML config, setup wizard, doctor diagnostics, provider resolution |
| Terminal backends | `tools/environments/` (6 backends) | Local, Docker, SSH, Singularity, Modal, Daytona |
| Terminal execution engine | `mini-swe-agent/` (vendored) | MIT license, by Kilian Lieret & Carlos Jimenez (v2.2.6) |
| Trajectory saving | `agent/trajectory.py` | JSONL + ShareGPT format conversation logs |
| Display formatting | `agent/display.py` | KawaiiSpinner, tool preview formatting |
| Tool call parsing | `agent/tool_call_parser.py` | LLM response extraction |
| API key redaction | `agent/redact.py` | Scrubs keys from logs |
| Local model server | `local_models/serve.py` | MLX-VLM wrapper serving Qwen3.5-9B on port 8800 |

### Built new for hermes-lite

| Component | File(s) | What it does |
|-----------|---------|--------------|
| Rust FSM | `hermes_rs/src/lib.rs` | PyO3 state machine — 12 states, 5 actions, 10 response kinds |
| Rust SessionDB | `hermes_rs/src/session_db.rs` | ~900 lines rusqlite, FTS5, WAL mode, mmap — drop-in replacement for Python backend |
| Rust TUI | `hermes_tui/` (8 modules) | ratatui 0.29 native terminal UI with streaming, tool progress, clarify dialog |
| Subprocess protocol | `run_agent.py` SubprocessProtocol class | JSON-over-pipes (11 event types) connecting TUI ↔ Python agent |
| Loop driver | `agent/loop_driver.py` | Python bridge translating Rust FSM states to AIAgent method calls |
| Multi-agent TUI wiring | `main.rs`, `multi.rs` | Per-pane subprocesses, @mentions, /split, /broadcast, inter-agent routing |
| Prodpush test suite | `tests/prodpush/` | 26 live integration tests driving the agent via subprocess protocol |
| Streaming fixes | `run_agent.py` `_skip_stream` flag | Fixed streaming that was silently broken (never worked in subprocess mode) |
| Interrupt re-queuing | `run_agent.py` interrupt watcher | Fixed multi-turn conversations (messages were being silently dropped) |

---

## Current Feature List

Everything below is implemented and tested. No vaporware.

### Agent Engine

- **LLM calls via litellm** — any litellm-compatible provider works (Anthropic, OpenAI, OpenRouter, local, etc.)
- **Streaming token output** — real-time in both CLI and TUI
- **Parallel tool execution** — non-inline tools run via ThreadPoolExecutor
- **Inline tools** run sequentially (todo, clarify — they need conversation state or user interaction)
- **Context compression** — auto-triggers at 85% of model's context window, preserves head+tail, summarizes middle
- **Prompt caching** — Anthropic-only, system_and_3 strategy (up to 4 cache breakpoints)
- **Context file scanning** — discovers and injects AGENTS.md, SOUL.md, .cursorrules, .cursor/rules/*.mdc from working directory
- **Prompt injection detection** — scans context files via `hermes_rs.scan_context_content()`
- **Trajectory saving** — JSONL and ShareGPT formats to `~/.hermes-lite/logs/`
- **Max 60 turns** per conversation (configurable)

### Tools (8 total)

| Tool | What it does |
|------|--------------|
| `terminal` | Shell commands with dangerous-command approval. 30 regex patterns trigger approval (rm -rf, chmod 777, dd, DROP TABLE, fork bombs, etc.) |
| `process` | Background process lifecycle — spawn, poll, read, kill, stdin. 200KB rolling buffer. PTY support. Crash recovery via JSON checkpoint. 64 process limit with LRU pruning |
| `read_file` | Read with line numbers, pagination, fuzzy filename suggestions on typos |
| `write_file` | Create/overwrite files. Auto-creates parent dirs. Write-deny list blocks sensitive paths (19 specific + 6 prefix patterns: ~/.ssh/, ~/.aws/, /etc/sudoers, shell rc files, etc.) |
| `patch` | Find-replace with 8 fuzzy matching strategies (exact → line-trimmed → whitespace-normalized → indentation-flexible → escape-normalized → trimmed-boundary → block-anchor → context-aware). Also supports unified V4A diff |
| `search_files` | ripgrep-backed. Regex content search or glob file find. Output modes: content, files_only, count |
| `todo` | Task list with pending/in_progress/completed/cancelled states. Compression-aware (survives context compression) |
| `clarify` | Ask the user multiple-choice or open-ended questions mid-task. TUI renders as modal dialog overlay |

### Terminal Backends (6)

All inherited from the original Hermes, powered by vendored mini-swe-agent v2.2.6.

| Backend | Config |
|---------|--------|
| `local` | Default, no config needed |
| `docker` | `TERMINAL_DOCKER_IMAGE` |
| `ssh` | `TERMINAL_SSH_HOST`, `_USER`, `_PORT`, `_KEY` |
| `singularity` | `TERMINAL_SINGULARITY_IMAGE` |
| `modal` | `modal setup` |
| `daytona` | — |

### CLI (23 slash commands)

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/tools` | List available tools |
| `/toolsets` | List available toolsets |
| `/model` | Switch model mid-session |
| `/prompt` | View/set custom system prompt |
| `/personality` | Set a predefined personality |
| `/clear` | Clear screen and reset conversation |
| `/history` | Show conversation history |
| `/new` | Start a new conversation |
| `/reset` | Reset conversation only (keep screen) |
| `/retry` | Retry the last message |
| `/undo` | Remove last user/assistant exchange |
| `/save` | Save current conversation |
| `/config` | Show current configuration |
| `/verbose` | Cycle tool display: off → new → all → verbose |
| `/thinkon` | Show model thinking/reasoning blocks |
| `/thinkoff` | Hide thinking blocks |
| `/compress` | Manually compress conversation context |
| `/usage` | Show token usage for current session |
| `/context` | Show remaining context window (ASCII bar) |
| `/jobs` | List background agent tasks |
| `/fg` | Bring background task to foreground |
| `/quit` | Exit (also: /exit, /q) |

### Rust FSM

12 loop states driven by a PyO3 state machine:

`Init` → `BuildPrompt` → `ApiCall` → `ParseResponse` → `CheckScratchpad` → `AdaptToolCalls` → `ExecuteTools` → `CheckInterrupt` → `CheckContext` → `HandleError` → `Summarize` → `Done`

5 actions: `Continue`, `Break`, `Retry`, `Nudge`, `Fail`

10 response kinds: `Text`, `ToolCalls`, `Truncated`, `TruncatedToolCall`, `Invalid`, `EmptyAfterThink`, `IncompleteScratchpad`, `InvalidToolNames`, `InvalidToolJson`, `CodexIncomplete`

### Rust SessionDB

Drop-in replacement for the Python SQLite layer:
- ~900 lines rusqlite with FTS5 full-text search
- WAL mode, mmap, synchronous=NORMAL
- All 19 original methods + `reopen_session()` + `append_messages` batch insert
- Auto-fallback: tries Rust first, falls back to Python if import fails

### Rust TUI

Native terminal UI (ratatui 0.29 + crossterm 0.28):
- Spawns Python agent with `--subprocess-mode` (one subprocess per pane)
- Real-time token streaming
- Tool call progress with timing
- Interactive clarify dialog (modal overlay with text input + choice navigation)
- Multi-agent: split/tab layouts, per-pane subprocesses, @mentions, /broadcast, inter-agent routing
- Pane navigation: Ctrl+Left/Right, Alt+1-9
- Interrupt handling (Ctrl+C)
- Session info, token counters, status bar
- 2 color schemes: cyber (green/blue), synthwave (pink/purple)

### Subprocess Protocol

JSON lines over stdin/stdout between Rust TUI and Python agent.

**TUI → Agent:**
```
UserInput { session_id, message, model, max_iterations }
ClarifyResponse { response }
Interrupt
Shutdown
```

**Agent → TUI:**
```
Ready
SessionInfo { session_id, model, context_length }
Token { content, is_thinking }
ToolCallStart { tool_id, tool_name, args_preview }
ToolCallResult { tool_id, success, output, duration_ms }
ResponseComplete { finish_reason, input_tokens, output_tokens }
LoopStateChange { state, iteration, action, message }
ClarifyRequest { question, choices, timeout_secs }
ContextCompressed { old_tokens, new_tokens }
Done { reason, iterations }
Error { message, code }
```

### Session Persistence

Two interchangeable backends (Rust default, Python fallback):
- SQLite with FTS5 full-text search across all sessions
- WAL mode for concurrent reads
- Session resume, branching via `parent_session_id`
- All stored at `~/.hermes-lite/state.db`

### Model Support

26 models configured with context lengths:

| Provider | Models | Context |
|----------|--------|---------|
| Anthropic | Claude Opus 4/4.5/4.6, Sonnet 4, Haiku 4.5 | 200K |
| OpenAI | GPT-4o, GPT-4-turbo, GPT-4o-mini | 128K |
| Google | Gemini 2.0-flash, Gemini 2.5-pro | 1M |
| Meta | Llama 3.3 70B | 131K |
| DeepSeek | DeepSeek Chat v3 | 65K |
| Qwen | Qwen 2.5 72B, Qwen3-coder, Qwen3.5 variants | 32-262K |
| Local | Qwen3.5-9B via MLX-VLM | 32K |

Unknown models are probed at descending context tiers (2M → 1M → 512K → 200K → 128K → 64K → 32K).

### Safety

**Dangerous command approval** — 30 regex patterns covering rm -rf, chmod 777, chown -R root, mkfs, dd, DROP TABLE, DELETE without WHERE, systemctl stop, fork bombs, pipe-to-shell, xargs rm, find -delete. Approvals persist per session, can be permanently allowlisted in config.

**Write protection** — blocks writes to:
- `~/.ssh/`, `~/.aws/`, `~/.gnupg/`, `~/.kube/` (entire directories)
- `/etc/sudoers`, `/etc/passwd`, `/etc/shadow`, `/etc/sudoers.d/`, `/etc/systemd/`
- Shell rc files: `.bashrc`, `.zshrc`, `.profile`, `.bash_profile`, `.zprofile`
- Credentials: `.netrc`, `.pgpass`, `.npmrc`, `.pypirc`
- Hermes config: `~/.hermes/.env`, `~/.hermes-lite/.env`

---

### Multi-Agent Mode

The Rust TUI supports multiple agent panes, each with its own independent agent subprocess:

**Commands:**
- `/split` — spawn a new agent in a vertical split
- `/hsplit` — spawn in a horizontal split
- `/tabs` — switch to tab layout (one pane full-width, tab bar at top)
- `/close` — close the focused pane
- `/name <n>` — rename the focused agent
- `/focus <n>` — focus by name or 1-based index
- `/broadcast <msg>` — send a message to all agents
- `/ask <target> <msg>` — send to a named agent, pull the response back to your pane
- `/agents` — list all agents with status, model, and token count
- `/zoom` — toggle between split and tab layouts

**@mentions:**
- `@a2 refactor this` — route message to agent "a2"
- `@researcher! summarize docs` — route to "researcher", pull response back when done
- `@all run tests` — broadcast to all agents

**Navigation:**
- `Ctrl+Left/Right` — switch focus between panes
- `Alt+1-9` — jump to pane by number

Each pane runs its own agent subprocess with independent session, model, tokens, and conversation history. Agents can route inter-agent queries and task delegations through the TUI.

### Image Support

The CLI supports pasting images from clipboard into conversations:
- **Alt+V** (primary), **Ctrl+V/Cmd+V** (bracketed paste), **`/paste`** (manual)
- macOS (osascript/pngpaste), WSL2, Wayland (wl-paste), X11 (xclip)
- Base64-encoded into OpenAI vision format, sent directly to the LLM
- PNG, JPEG, GIF, WebP supported

---

## Not Implemented

- **Web search** — removed from Hermes
- **Browser automation** — removed from Hermes
- **Vision analysis tools** — standalone tools like `vision_analyze` were removed; image paste into conversations works (see above)
- **Messaging integrations** (Slack, Discord, Telegram, WhatsApp) — removed from Hermes
- **MCP server support** — not implemented
- **IDE integration** — not implemented

---

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Rust extensions (FSM + SessionDB):

```bash
pip install maturin
maturin develop --release -m hermes_rs/Cargo.toml
```

Rust TUI:

```bash
cargo build --release -p hermes_tui
```

Local model support (Apple Silicon only):

```bash
pip install -e ".[local]"
```

Requires Python 3.11+ and Rust 1.75+.

---

## Setup

```bash
hermes-lite setup
```

Writes configuration to `~/.hermes-lite/`. Then export your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

For local models, select **Local** during setup. Serves Qwen3.5-9B (4-bit quantized) via MLX-VLM at `http://127.0.0.1:8800/v1`.

Run `hermes-lite doctor` to validate your setup (checks Python version, venv, packages, API keys, ripgrep, local server connectivity).

---

## Usage

### Entry Points

| Command | Description |
|---------|-------------|
| `hermes-lite` | Interactive REPL |
| `hermes-lite chat` | Conversational agent (interactive or single-shot with `-q`) |
| `hermes-lite doctor` | Run diagnostics (8 checks) |
| `hermes-lite setup` | Interactive setup wizard |
| `hermes-lite-agent` | Headless agent runner |
| `hermes-lite-serve` | Local model server (MLX-VLM) |
| `./target/release/hermes-tui` | Native Rust TUI |

### Interactive

```bash
hermes-lite                            # new session
hermes-lite --continue                 # resume last session
hermes-lite -c                         # same
```

### Single-shot

```bash
hermes-lite chat -q "summarize this repo"
hermes-lite chat --model claude-opus-4-6 -q "refactor main.py"
```

### Rust TUI

```bash
./target/release/hermes-tui
```

### Select tools

```bash
hermes-lite chat -t "terminal,file"    # only terminal + file tools
```

### Select terminal backend

```bash
TERMINAL_ENV=docker TERMINAL_DOCKER_IMAGE=ubuntu:24.04 hermes-lite chat
```

---

## Configuration

All config lives under `~/.hermes-lite/`:

| Path | Purpose |
|------|---------|
| `config.yaml` | Model, provider, compression settings |
| `.env` | API keys, terminal backend config |
| `state.db` | SQLite session history |
| `logs/` | Error logs, trajectory files (JSONL + ShareGPT) |

### Key config fields

```yaml
model:
  default: "claude-sonnet-4-5-20250929"
  provider: "anthropic"

compression:
  enabled: true
  threshold: 0.85

agent:
  max_turns: 60
```

### Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Required for Anthropic provider |
| `TERMINAL_ENV` | `local`, `docker`, `ssh`, `singularity`, `modal`, `daytona` |
| `TERMINAL_DOCKER_IMAGE` | Docker image for docker backend |
| `TERMINAL_SSH_HOST` / `_USER` / `_PORT` / `_KEY` | SSH connection |
| `TERMINAL_CWD` | Working directory (default: `.`) |
| `TERMINAL_TIMEOUT` | Per-command timeout in seconds (default: 60) |

---

## Testing

```bash
# Unit tests (1062 tests, ~47s)
python3 -m pytest tests/ -q

# Prodpush integration tests (26 tests, requires API key, ~4min)
python3 -m pytest tests/prodpush/ -v -m prodpush --timeout=180

# Specific categories
python3 -m pytest tests/agent/ -v
python3 -m pytest tests/tools/ -v
python3 -m pytest tests/hermes_cli/ -v
```

### Test coverage

| Category | Tests | What's tested |
|----------|-------|---------------|
| `tests/agent/` | 12 modules | FSM, compression, prompt caching, tool parsing, model metadata |
| `tests/tools/` | 15 modules | All 8 tools, approval patterns, file ops, fuzzy matching, process registry |
| `tests/hermes_cli/` | 3 modules | Config management, model choices, CLI behavior |
| Core | 9 modules | SessionDB (both backends), headless CLI, run_agent, toolsets |
| `tests/prodpush/` | 26 tests | Live agent via subprocess — startup, file CRUD, terminal, workflows, interrupts, recipes, edge cases |

The prodpush suite uses the same subprocess protocol as the Rust TUI, so it tests the exact code path a real user exercises.

---

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full breakdown. The short version:

```
tools/registry.py        → tool registration (no deps)
tools/*.py               → tool implementations (register at import)
model_tools.py           → schema generation + dispatch
run_agent.py             → AIAgent conversation loop
cli.py                   → interactive REPL
hermes_cli/main.py       → entry point
```

The Rust FSM (`hermes_rs`) drives the loop, with `agent/loop_driver.py` bridging Rust states to Python method calls. The Rust TUI (`hermes_tui`) spawns the Python agent as a subprocess and communicates via the JSON protocol.

---

## License

hermes-lite builds on:
- **Hermes** by [Nous Research](https://nousresearch.com) — the agent engine, CLI, tools, and config system
- **mini-swe-agent** v2.2.6 by Kilian Lieret & Carlos Jimenez (MIT) — terminal execution backends

The Rust extensions (`hermes_rs/`, `hermes_tui/`), subprocess protocol, loop driver, streaming fixes, and prodpush test suite are original to hermes-lite.
