# hermes-lite

A local-first coding agent for macOS. Built on [Hermes](https://github.com/NousResearch) by **Nous Research**, extended with Rust-accelerated internals and a native TUI.

---

## Origins and Attribution

hermes-lite is a fork of the **Hermes Agent** project by [Nous Research](https://nousresearch.com). The original Hermes is a full-featured AI agent platform supporting web search, browser automation, vision, messaging integrations (Slack/Discord/Telegram/WhatsApp), reinforcement learning, and more.

hermes-lite strips that down to a focused Mac coding agent: terminal execution, file operations, and a planning loop — driven by Anthropic's API or an on-device Qwen model via MLX-VLM.

### What came from where

| Component | Origin | Notes |
|-----------|--------|-------|
| Agent conversation loop (`run_agent.py`) | Nous Research / Hermes | Core agent engine — tool dispatch, streaming, context compression |
| Interactive CLI (`cli.py`) | Nous Research / Hermes | prompt_toolkit REPL, slash commands, session management |
| Tool system (`tools/`) | Nous Research / Hermes | Terminal, file ops, todo, clarify, approval, process management |
| System prompt & identity | Nous Research / Hermes | "You are Hermes Agent, created by Nous Research" |
| Prompt caching (`agent/prompt_caching.py`) | Nous Research / Hermes | Anthropic cache_control strategy |
| Context compression (`agent/context_compressor.py`) | Nous Research / Hermes | Auto-summarization at 85% context window |
| Session persistence (`hermes_state.py`) | Nous Research / Hermes | SQLite schema, FTS5 search |
| Config system (`hermes_cli/`) | Nous Research / Hermes | YAML config, setup wizard, doctor diagnostics |
| Terminal backends | [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) v2.2.6 | MIT license, by Kilian Lieret & Carlos Jimenez |
| Rust FSM (`hermes_rs/src/lib.rs`) | hermes-lite (new) | PyO3 state machine replacing Python loop |
| Rust SessionDB (`hermes_rs/src/session_db.rs`) | hermes-lite (new) | rusqlite replacement for Python SessionDB |
| Rust TUI (`hermes_tui/`) | hermes-lite (new) | ratatui native terminal UI with subprocess protocol |
| Subprocess protocol (`SubprocessProtocol`) | hermes-lite (new) | JSON-over-pipes between Rust TUI and Python agent |
| Loop driver (`agent/loop_driver.py`) | hermes-lite (new) | Python bridge for Rust FSM |
| Prodpush test suite (`tests/prodpush/`) | hermes-lite (new) | Live integration tests via subprocess protocol |

---

## Feature Comparison

| Feature | Hermes (Nous) | hermes-lite | Claude Code |
|---------|:---:|:---:|:---:|
| **Terminal execution** | Local, Docker, SSH, Singularity, Modal, Daytona | Local, Docker, SSH, Singularity, Modal, Daytona | Local only |
| **File read/write/patch** | Yes | Yes | Yes |
| **File search (ripgrep)** | Yes | Yes | Yes |
| **Background processes** | Yes — spawn, poll, kill, stdin | Yes — spawn, poll, kill, stdin | No |
| **Dangerous command approval** | Yes | Yes | Yes (permissions model) |
| **Todo/task planning** | Yes | Yes | Yes (TodoWrite) |
| **Clarify (ask user mid-task)** | Yes | Yes | No |
| **Session persistence** | SQLite | SQLite + Rust SessionDB (FTS5, WAL) | Conversation memory |
| **Session resume** | Yes | Yes | Yes |
| **Context compression** | Yes — auto at 85% | Yes — auto at 85% | Yes — auto |
| **Prompt caching** | Anthropic cache_control | Anthropic cache_control | Built-in |
| **Streaming** | Yes | Yes (subprocess protocol) | Yes |
| **Local models (on-device)** | Yes (MLX-VLM) | Yes (Qwen3.5-9B via MLX-VLM) | No |
| **Rust-accelerated internals** | No | Yes — FSM, SessionDB | No (Node.js) |
| **Native TUI** | No | Yes — ratatui with subprocess protocol | Yes (Node.js TUI) |
| **Multi-agent mode** | Yes | Designed, not yet active | Yes (Agent tool) |
| **Web search** | Yes | No (removed) | Yes |
| **Browser automation** | Yes | No (removed) | Yes (via MCP) |
| **Vision/image analysis** | Yes | No (removed) | Yes |
| **Messaging (Slack, etc.)** | Yes | No (removed) | No |
| **MCP server support** | No | No | Yes |
| **IDE integration** | No | No | Yes (VS Code, JetBrains) |
| **API provider** | Anthropic, OpenRouter, Nous Portal | Anthropic, local MLX-VLM | Anthropic only |
| **Platform** | Cross-platform | macOS (Apple Silicon) | Cross-platform |
| **Prodpush live test suite** | No | Yes — 26 integration tests | No |

---

## What's Included

- Interactive Claude-style CLI with slash commands and rich formatting
- Shell execution with dangerous-command approval (6 backends)
- Background process management with crash recovery
- File read / write / patch / search tools
- Todo-based task planning
- Clarify prompts — agent asks you questions mid-task
- SQLite session persistence with FTS5 full-text search
- Auto context compression at 85% of context window
- Anthropic prompt caching (~75% input token cost reduction)
- Rust-accelerated FSM for the conversation loop
- Rust SessionDB replacing Python SQLite layer
- Native ratatui TUI connected via JSON subprocess protocol
- Optional on-device Qwen3.5-9B via MLX-VLM
- 1062 unit tests + 26 live prodpush integration tests

---

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For the Rust extensions (FSM + SessionDB):

```bash
pip install maturin
maturin develop --release -m hermes_rs/Cargo.toml
```

For the Rust TUI:

```bash
cargo build --release -p hermes_tui
```

For local model support (MLX-VLM on Apple Silicon):

```bash
pip install -e ".[local]"
```

Requires Python 3.11+ and Rust 1.75+.

---

## Setup

```bash
hermes-lite setup
```

This writes configuration to `~/.hermes-lite/`. Then export your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

For local models, select **Local** during setup. The CLI targets MLX-VLM at `http://127.0.0.1:8800/v1`.

---

## Usage

### Entry Points

| Command | Description |
|---------|-------------|
| `hermes-lite` | Interactive REPL |
| `hermes-lite chat` | Conversational agent (interactive or single-shot with `-q`) |
| `hermes-lite-agent` | Headless agent runner |
| `hermes-lite-serve` | Local model server (MLX-VLM) |
| `./target/release/hermes-tui` | Native Rust TUI |

### Interactive REPL

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

Spawns the Python agent as a subprocess, communicates via JSON protocol. Features: streaming token display, tool call progress, clarify dialog, interrupt handling.

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation context |
| `/model` | Switch model mid-session |
| `/personality` | Change assistant personality |
| `/verbose` | Toggle verbose output |
| `/context` | Show context window usage |
| `/compact` | Compact history to save context |
| `/tools` | List enabled tools |
| `/save` | Save current session |
| `/history` | Browse past sessions |

---

## Tools

8 tools, all enabled by default:

| Tool | Description |
|------|-------------|
| `terminal` | Shell commands with dangerous-command approval |
| `process` | Background process lifecycle — spawn, poll, read, kill, stdin; 200KB rolling buffer; crash recovery |
| `read_file` | Read with line numbers, pagination, fuzzy filename suggestions |
| `write_file` | Create/overwrite files; auto-creates dirs; write-deny list for sensitive paths |
| `patch` | Find-replace with 9 fuzzy strategies or unified V4A diff; syntax check after edit |
| `search_files` | ripgrep-backed; regex content search or glob find; output: `content`, `files_only`, `count` |
| `todo` | Task list with `pending`/`in_progress`/`completed`/`cancelled`; compression-aware |
| `clarify` | Ask the user multiple-choice or open-ended questions mid-task |

### Toolsets

| Toolset | Tools |
|---------|-------|
| `terminal` | `terminal`, `process` |
| `file` | `read_file`, `write_file`, `patch`, `search_files` |
| `todo` | `todo` |
| `clarify` | `clarify` |
| `hermes-lite-cli` | All of the above (default) |

```bash
hermes-lite chat -t "terminal,file"
```

---

## Terminal Backends

Set `TERMINAL_ENV` to select. Default is `local`.

| Backend | Required Config |
|---------|-----------------|
| `local` | — |
| `docker` | `TERMINAL_DOCKER_IMAGE` |
| `ssh` | `TERMINAL_SSH_HOST`, `_USER`, `_PORT`, `_KEY` |
| `singularity` | `TERMINAL_SINGULARITY_IMAGE` |
| `modal` | `modal setup` |
| `daytona` | — |

```bash
TERMINAL_ENV=docker TERMINAL_DOCKER_IMAGE=ubuntu:24.04 hermes-lite chat
```

Powered by a vendored copy of [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) v2.2.6 (MIT, by Kilian Lieret & Carlos Jimenez).

---

## Architecture

```
run_agent.py                  AIAgent — conversation loop, tool dispatch, streaming
cli.py                        HermesCLI — interactive REPL, prompt_toolkit
hermes_state.py               Python SessionDB (fallback)
model_tools.py                Tool schema generation, function call dispatch
toolsets.py                   Named tool groupings

agent/                        Agent internals (14 modules)
  loop_driver.py              Rust FSM Python bridge
  context_compressor.py       Auto compression at 85%
  prompt_builder.py           System prompt assembly
  prompt_caching.py           Anthropic cache_control
  model_capabilities.py       Model feature detection
  model_metadata.py           Context lengths, token estimation
  tool_call_parser.py         Tool call extraction
  tool_prompt_injector.py     Schema injection into prompts
  tool_response_adapter.py    Response format normalization
  auxiliary_client.py         Side-channel model for compression
  display.py                  Spinners, tool preview formatting
  trajectory.py               Conversation saving (JSONL/ShareGPT)
  redact.py                   API key redaction

hermes_cli/                   CLI layer (14 modules)
  main.py                     Entry point, argparse dispatcher
  config.py                   YAML config management
  runtime_provider.py         Provider resolution (anthropic/local)
  setup.py                    Interactive setup wizard
  doctor.py                   Diagnostics
  status.py                   Runtime status display
  models.py, commands.py, banner.py, callbacks.py,
  clipboard.py, colors.py, color_scheme.py

tools/                        Tool implementations
  registry.py                 Central tool registry
  terminal_tool.py            Shell execution orchestration
  file_tools.py               read_file, write_file, search_files
  file_operations.py          File operation helpers
  patch_parser.py             Unified diff patching (9 fuzzy strategies)
  fuzzy_match.py              Fuzzy filename matching
  process_registry.py         Background process management
  todo_tool.py                Task planning
  clarify_tool.py             Interactive user questions
  approval.py                 Dangerous command detection
  interrupt.py                Ctrl+C handling
  environments/               6 terminal backends (local, docker, ssh, ...)

hermes_rs/                    Rust PyO3 extension
  src/lib.rs                  FSM: LoopState(12), Action(4), ResponseKind(10)
  src/session_db.rs           RustSessionDB: rusqlite, FTS5, WAL mode

hermes_tui/                   Rust TUI binary (ratatui)
  src/main.rs                 Entry point, subprocess management
  src/app.rs                  App state, conversation history
  src/ui.rs                   Rendering, clarify dialog overlay
  src/protocol.rs             ToAgent/FromAgent JSON message types
  src/subprocess.rs           Python subprocess spawning
  src/colors.rs               Color scheme
  src/mention.rs              Multi-agent @mentions (future)
  src/multi.rs                Multi-agent pane splitting (future)

local_models/                 MLX-VLM server wrapper
mini-swe-agent/               Vendored terminal backend (MIT)
tests/                        1062 unit + 26 prodpush integration tests
docs/                         Design documents
```

### Subprocess Protocol

The Rust TUI communicates with the Python agent via JSON lines over stdin/stdout:

**TUI to Agent (`ToAgent`):**
```
UserInput { session_id, message, model, max_iterations }
ClarifyResponse { response }
Interrupt
Shutdown
```

**Agent to TUI (`FromAgent`):**
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

---

## Rust Extensions

### FSM (`hermes_rs/src/lib.rs`)

The agent conversation loop is driven by a Rust state machine exposed to Python via PyO3:

- **12 loop states**: `Init`, `BuildPrompt`, `ApiCall`, `ParseResponse`, `CheckScratchpad`, `AdaptToolCalls`, `ExecuteTools`, `CheckInterrupt`, `CheckContext`, `HandleError`, `Summarize`, `Done`
- **4 actions**: `Continue`, `Break`, `Retry`, `Fail`, `Nudge`
- **10 response kinds**: `Text`, `ToolCall`, `TruncatedToolCall`, `Empty`, `Invalid`, `IncompleteScratchpad`, `PlanningAck`, `ContextOverflow`, `MaxIterations`, `Interrupted`

Build: `maturin develop --release -m hermes_rs/Cargo.toml`

### SessionDB (`hermes_rs/src/session_db.rs`)

Drop-in replacement for the Python `SessionDB`:
- ~900 lines rusqlite with FTS5 full-text search
- WAL mode, mmap, synchronous=NORMAL
- All 19 original methods + `reopen_session()` + `append_messages` batch
- Auto-fallback: `try: from hermes_rs import RustSessionDB except: from hermes_state import SessionDB`

### TUI (`hermes_tui/`)

Native terminal UI built with ratatui 0.29 + crossterm 0.28:
- Spawns Python agent with `--subprocess-mode`
- Real-time token streaming display
- Tool call progress with timing
- Interactive clarify dialog (modal overlay)
- Interrupt handling (Ctrl+C)
- Session info, token counters, status bar

Build: `cargo build --release -p hermes_tui`
Run: `./target/release/hermes-tui`

---

## Safety

**Dangerous command detection** — commands involving `rm`, `chmod`, `kill`, `dd`, `iptables`, etc. require explicit approval. Approvals persist for the session.

**Write protection** — `write_file` and `patch` block writes to:
- `~/.ssh/`, `~/.aws/`, `~/.kube/`
- `/etc/sudoers`, `/etc/passwd`, `/etc/shadow`
- Shell rc files (`.bashrc`, `.zshrc`, etc.)

---

## Configuration

All config lives under `~/.hermes-lite/`:

| Path | Purpose |
|------|---------|
| `config.yaml` | Model, provider, compression settings |
| `.env` | API keys, terminal backend config |
| `state.db` | SQLite session history |
| `logs/` | Error logs and trajectory files |

**Key config fields:**

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

**Environment variables:**

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

# Prodpush integration tests (26 tests, requires API key, ~5min)
python3 -m pytest tests/prodpush/ -v -m prodpush --timeout=180

# Specific test category
python3 -m pytest tests/agent/ -v
python3 -m pytest tests/tools/ -v
python3 -m pytest tests/hermes_cli/ -v
```

| Category | Tests | Coverage |
|----------|-------|----------|
| `tests/agent/` | 12 modules | FSM, compression, prompt caching, tool parsing, model metadata |
| `tests/tools/` | 15 modules | All tools, approval, file ops, fuzzy match, process registry |
| `tests/hermes_cli/` | 3 modules | Config, models, CLI behavior |
| Core | 9 modules | SessionDB, headless CLI, run_agent, toolsets |
| `tests/prodpush/` | 26 tests | Live agent via subprocess protocol — file CRUD, terminal, workflows, interrupts, recipes |

---

## License

hermes-lite builds on:
- **Hermes** by [Nous Research](https://nousresearch.com)
- **mini-swe-agent** v2.2.6 by Kilian Lieret & Carlos Jimenez (MIT)

The Rust extensions (`hermes_rs/`, `hermes_tui/`), subprocess protocol, loop driver, and prodpush test suite are original to hermes-lite.
