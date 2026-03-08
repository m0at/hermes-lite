# Architecture Overview

hermes-lite is a local-first coding agent CLI for macOS. This document describes how the major subsystems fit together.

## Repository Layout

```
hermes-lite/
├── src/                         # Python source
│   ├── run_agent.py             # AIAgent class — conversation loop, LLM calls, tool dispatch
│   ├── cli.py                   # HermesCLI — interactive REPL with prompt_toolkit
│   ├── model_tools.py           # Tool schema generation and function call dispatch
│   ├── toolsets.py              # Named tool groupings (terminal, file, todo, clarify)
│   ├── hermes_state.py          # Python SessionDB — SQLite session persistence (fallback)
│   ├── hermes_constants.py      # Shared constants
│   ├── utils.py                 # Atomic JSON write
│   │
│   ├── agent/                   # Agent internals
│   │   ├── loop_driver.py       # Rust FSM Python bridge — drives the agent loop
│   │   ├── prompt_builder.py    # System prompt assembly, AGENTS.md/SOUL.md scanning
│   │   ├── context_compressor.py # Auto context compression at 85% capacity
│   │   ├── prompt_caching.py    # Anthropic prompt caching (system_and_3 strategy)
│   │   ├── model_metadata.py    # Context lengths, token estimation
│   │   ├── display.py           # KawaiiSpinner, tool preview formatting
│   │   ├── redact.py            # API key redaction
│   │   └── trajectory.py        # Trajectory saving helpers
│   │
│   ├── hermes_cli/              # CLI commands and configuration
│   │   ├── main.py              # Entry point, argparse command dispatcher
│   │   ├── config.py            # Config management and migration
│   │   ├── setup.py             # Interactive setup wizard
│   │   ├── doctor.py            # Diagnostics
│   │   └── clipboard.py         # Clipboard helpers
│   │
│   ├── tools/                   # Tool implementations
│   │   ├── registry.py          # Central tool registry (no deps)
│   │   ├── terminal_tool.py     # Shell execution orchestration
│   │   ├── file_tools.py        # File read/write/search
│   │   ├── todo_tool.py         # Task planning
│   │   ├── memory_tool.py       # Persistent memory (global + project, swarm-shared)
│   │   ├── skill_tools.py       # Browse and load reusable skill definitions
│   │   ├── clarify_tool.py      # Interactive questions
│   │   ├── delegate_tool.py     # Inter-agent task delegation
│   │   ├── process_registry.py  # Background process management
│   │   ├── approval.py          # Dangerous command detection
│   │   └── environments/        # Terminal execution backends
│   │       ├── local.py, docker.py, ssh.py, singularity.py, modal.py, daytona.py
│   │
│   └── local_models/            # Optional local model server (MLX-VLM)
│
├── hermes_rs/                   # Rust PyO3 extension (workspace member)
│   └── src/
│       ├── lib.rs               # FSM states, transitions, utility functions
│       └── session_db.rs        # RustSessionDB — high-performance SQLite replacement
│
├── hermes_tui/                  # Rust TUI binary (workspace member)
│   └── src/
│       ├── main.rs              # Entry point, app loop, subprocess management
│       ├── ui.rs                # Ratatui rendering (single pane)
│       ├── multi.rs             # Multi-agent pane rendering
│       ├── app.rs               # Application state
│       ├── protocol.rs          # JSON message types (ToAgent/FromAgent)
│       └── mention.rs           # @-mention parsing and routing
│
├── vendor/
│   └── mini-swe-agent/          # Vendored terminal execution backend (v2.2.6, MIT)
│
├── tests/                       # Test suite (1065 unit + 26 integration tests)
├── docs/                        # Design documents
├── demo/                        # Demo scenarios and recording scripts
└── README.md
```

## Dependency Chain

```
tools/registry.py             (no deps — imported by all tool files)
       ^
tools/*.py                    (each calls registry.register() at import time)
       ^
model_tools.py                (imports tools/registry, triggers tool discovery)
       ^
run_agent.py                  (AIAgent — owns the conversation loop)
       ^
cli.py                        (HermesCLI — interactive REPL wrapping AIAgent)
       ^
hermes_cli/main.py            (argparse entry point)
```

## Core Subsystems

### Agent Loop (run_agent.py + agent/loop_driver.py)

The conversation loop lives in `AIAgent.chat()`. The Rust FSM in `hermes_rs` defines 12 loop states and 5 actions; `agent/loop_driver.py` bridges the Rust state machine to Python, calling back into `AIAgent` methods for LLM calls, tool execution, and context compression.

The loop:
1. Add user message to conversation
2. Call LLM with tool definitions
3. If the LLM returns tool calls, execute them (parallel where safe) and loop back to step 2
4. If the LLM returns a text response, return it

Streaming is enabled when the display is active and no timeout is set. Tool calls are accumulated from stream deltas and reassembled into the standard response shape.

### Tool Dispatch (model_tools.py + tools/)

Tools register themselves via `tools/registry.py` at import time. `model_tools.py` lazily imports all tool modules, generates OpenAI-format tool schemas, and dispatches function calls by name.

Parallel tool execution: consecutive non-inline tool calls run via `ThreadPoolExecutor`. Inline tools (`todo`, `session_search`, `memory`, `clarify`, `delegate_task`) always run sequentially because they depend on conversation state or require user interaction.

### Session Persistence (hermes_state.py / hermes_rs/src/session_db.rs)

Two interchangeable backends:
- **RustSessionDB** (default) -- PyO3 class backed by rusqlite. WAL mode, mmap, FTS5 with content-sync triggers.
- **Python SessionDB** (fallback) -- pure Python sqlite3 implementation.

Both are imported via try/except in `cli.py` and `hermes_cli/main.py`. The agent receives the DB instance as a parameter and is backend-agnostic.

### TUI (hermes_tui/)

A ratatui terminal UI that spawns the Python agent as a subprocess (`run_agent.py --subprocess-mode`). Communication uses a JSON protocol defined in `protocol.rs` with `ToAgent` (user input, interrupt, shutdown) and `FromAgent` (tokens, tool calls, responses, status) message types.

### Prompt Assembly (agent/prompt_builder.py)

Builds the system prompt from:
- Base personality/instructions
- Project context files (`AGENTS.md`, `.cursorrules`, `.cursor/rules/*.mdc`) discovered recursively from the working directory
- Prompt injection detection via `scan_context_content`

### Context Compression (agent/context_compressor.py)

Triggers at 85% of the model's context window. Preserves head and tail turns, summarizes the middle using a fast auxiliary model. Creates a new session linked via `parent_session_id`.

## Build System

The repo is a Cargo workspace with two members:
- `hermes_rs` -- built with `maturin develop --release -m hermes_rs/Cargo.toml` (installs into the Python venv)
- `hermes_tui` -- built with `cargo build --release -p hermes_tui`

Python packaging uses `pyproject.toml` with setuptools.

## Entry Points (pyproject.toml)

| Console script | Target |
|----------------|--------|
| `hermes-lite` | `hermes_cli.main:main` |
| `hermes-lite-agent` | `run_agent:main` |
| `hermes-lite-serve` | `local_models.serve:main` |

## Configuration

All user config lives under `~/.hermes-lite/`:

| Path | Purpose |
|------|---------|
| `config.yaml` | Model, provider, compression settings |
| `.env` | API keys and terminal backend variables |
| `state.db` | SQLite session history |
| `logs/` | Error logs and trajectory JSONL files |
