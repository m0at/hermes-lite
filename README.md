# hermes-lite

A local-first coding agent for macOS with a native Rust TUI, multi-agent swarms, and Rust-accelerated internals. Built on [Hermes](https://github.com/NousResearch) by Nous Research.

https://github.com/user-attachments/assets/placeholder-demo-video

## What is this

hermes-lite takes the open-source Hermes Agent, strips it to a focused local coding tool, then extends it with:

- **Rust FSM** — PyO3 state machine replacing the Python conversation loop (12 states, 5 actions)
- **Rust SessionDB** — rusqlite + FTS5 + WAL replacing the Python SQLite layer
- **Native TUI** — ratatui terminal UI with multi-agent panes, @mentions, delegation, and inter-agent routing
- **Subprocess protocol** — JSON-over-pipes connecting TUI to Python agent processes
- **Integration test suite** — 26 live end-to-end tests driving the agent via subprocess protocol

## Quick start

```bash
# Python agent + CLI
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Rust extensions (FSM + SessionDB)
pip install maturin
maturin develop --release -m hermes_rs/Cargo.toml

# Rust TUI
cargo build --release -p hermes_tui

# Configure
cp .env.example .env  # add your API key
export ANTHROPIC_API_KEY=sk-ant-...
```

Requires Python 3.11+ and Rust 1.75+.

## Usage

```bash
hermes-lite                              # interactive REPL
hermes-lite chat -q "summarize this"     # single-shot
hermes-lite --continue                   # resume last session
./target/release/hermes-tui              # native TUI
```

## Multi-agent mode

The Rust TUI supports multiple agent panes, each running an independent subprocess with its own session, model, and conversation.

```
/split              vertical split — spawn new agent
/hsplit             horizontal split
/tabs               switch to tab layout
/close              close focused pane
/name <n>           rename agent
/broadcast <msg>    send to all agents
/agents             list all agents
```

**@mentions:** `@frontend refactor this` routes to a named agent. `@frontend! do X` routes and pulls the response back. `@all run tests` broadcasts.

**Navigation:** `Ctrl+Left/Right` switches panes, `Alt+1-9` jumps by number.

**Delegation:** Agents can programmatically delegate tasks to other agents in the swarm via the `delegate_task` tool. Results are routed back automatically.

## Agent tools

| Tool | Description |
|------|-------------|
| `terminal` | Shell execution with dangerous-command approval (30 patterns) |
| `process` | Background process management (spawn, poll, kill, stdin) |
| `read_file` | Read files with line numbers, pagination, fuzzy filename suggestions |
| `write_file` | Create/overwrite with auto-mkdir and write-deny list |
| `patch` | Find-replace with 8 fuzzy matching strategies + unified diff |
| `search_files` | ripgrep-backed regex search and glob file find |
| `todo` | Task planning with status tracking (survives context compression) |
| `clarify` | Ask user questions mid-task (rendered as modal dialog in TUI) |
| `delegate_task` | Delegate work to another named agent in the swarm |

## Architecture

```
hermes_tui/     Rust TUI (ratatui) — multi-pane, subprocess management
hermes_rs/      Rust extensions (PyO3) — FSM + SessionDB
run_agent.py    Python agent loop — LLM calls, tool dispatch, streaming
cli.py          Interactive REPL — 23 slash commands, session management
agent/          Agent internals — prompt builder, compression, loop driver
tools/          Tool implementations + 6 terminal backends
```

The Rust FSM drives the conversation loop. `agent/loop_driver.py` bridges Rust states to Python. The TUI spawns Python agents as subprocesses communicating via JSON protocol (11 event types each direction).

**Terminal backends:** local (default), Docker, SSH, Singularity, Modal, Daytona.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full breakdown.

## Subprocess protocol

JSON lines over stdin/stdout between Rust TUI and Python agent:

**TUI → Agent:** `UserInput`, `ClarifyResponse`, `DelegatedTask`, `CrossAgentContext`, `Interrupt`, `Shutdown`

**Agent → TUI:** `Ready`, `SessionInfo`, `Token`, `ToolCallStart`, `ToolCallResult`, `ResponseComplete`, `LoopStateChange`, `ClarifyRequest`, `DelegateTask`, `DelegationResult`, `ContextCompressed`, `Done`, `Error`

## Rust FSM

12 loop states: `Init` → `BuildPrompt` → `ApiCall` → `ParseResponse` → `CheckScratchpad` → `AdaptToolCalls` → `ExecuteTools` → `CheckInterrupt` → `CheckContext` → `HandleError` → `Summarize` → `Done`

5 actions: `Continue`, `Break`, `Retry`, `Nudge`, `Fail`

## Testing

```bash
# Unit tests (1062 tests)
python3 -m pytest tests/ -q

# Live integration tests (26 tests, requires API key)
python3 -m pytest tests/prodpush/ -v -m prodpush --timeout=180
```

| Suite | Tests | Coverage |
|-------|-------|----------|
| `tests/agent/` | 12 modules | FSM, compression, prompt caching, tool parsing |
| `tests/tools/` | 15 modules | All tools, approval patterns, fuzzy matching |
| `tests/hermes_cli/` | 3 modules | Config, model choices, CLI behavior |
| `tests/prodpush/` | 26 tests | End-to-end via subprocess protocol |

## Safety

**Command approval** — 30 regex patterns trigger user confirmation: `rm -rf`, `chmod 777`, `dd`, `DROP TABLE`, fork bombs, pipe-to-shell, etc.

**Write protection** — blocks writes to `~/.ssh/`, `~/.aws/`, `/etc/sudoers`, shell rc files, credentials, and 19 other sensitive paths.

**API key redaction** — scrubs keys from logs (sk-*, ghp_*, xoxb-*, etc).

## Documentation

| Doc | Description |
|-----|-------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full architecture reference |
| [docs/AGENTS.md](docs/AGENTS.md) | Development guide |
| [docs/MULTI_AGENT_DESIGN.md](docs/MULTI_AGENT_DESIGN.md) | Multi-agent design decisions |
| [demo/README.md](demo/README.md) | Demo scenarios and scripts |
| [demo/QUICKSTART.md](demo/QUICKSTART.md) | Quick start guide |

## License

Built on **Hermes** by [Nous Research](https://nousresearch.com) and **mini-swe-agent** v2.2.6 by Kilian Lieret & Carlos Jimenez (MIT). The Rust extensions, TUI, subprocess protocol, delegation system, and test suite are original to hermes-lite.
