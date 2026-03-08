# Architecture Overview

hermes-lite is a local-first coding agent CLI for macOS. This document describes how the major subsystems fit together.

## Repository Layout

```
hermes-lite/
├── run_agent.py              # AIAgent class — conversation loop, LLM calls, tool dispatch (~4900 lines)
├── cli.py                    # HermesCLI — interactive REPL with prompt_toolkit (~3500 lines)
├── model_tools.py            # Tool schema generation and function call dispatch
├── toolsets.py               # Named tool groupings (terminal, file, todo, clarify)
├── hermes_state.py           # Python SessionDB — SQLite session persistence (fallback)
├── hermes_constants.py       # Shared constants
├── utils.py                  # Atomic JSON write
│
├── agent/                    # Agent internals (extracted from run_agent.py)
│   ├── loop_driver.py        # Rust FSM Python bridge — drives the agent loop
│   ├── prompt_builder.py     # System prompt assembly, AGENTS.md/SOUL.md scanning
│   ├── context_compressor.py # Auto context compression at 85% capacity
│   ├── prompt_caching.py     # Anthropic prompt caching (system_and_3 strategy)
│   ├── model_capabilities.py # Model feature detection
│   ├── model_metadata.py     # Context lengths, token estimation
│   ├── display.py            # KawaiiSpinner, tool preview formatting
│   ├── tool_call_parser.py   # Tool call extraction from LLM responses
│   ├── tool_prompt_injector.py # Tool schema injection into prompts
│   ├── tool_response_adapter.py # Response normalization
│   ├── auxiliary_client.py   # Side-channel client for compression
│   ├── redact.py             # API key redaction
│   └── trajectory.py         # Trajectory saving helpers
│
├── hermes_cli/               # CLI commands and configuration
│   ├── main.py               # Entry point, argparse command dispatcher
│   ├── config.py             # Config management and migration
│   ├── runtime_provider.py   # Provider resolution (anthropic/local)
│   ├── models.py             # Model choices
│   ├── setup.py              # Interactive setup wizard
│   ├── status.py             # Status display
│   ├── doctor.py             # Diagnostics
│   ├── commands.py           # Slash command definitions
│   ├── callbacks.py          # Interactive prompt callbacks
│   ├── banner.py             # Welcome banner
│   ├── clipboard.py          # Clipboard helpers
│   ├── colors.py             # Terminal colors
│   └── color_scheme.py       # Color scheme definitions
│
├── tools/                    # Tool implementations
│   ├── registry.py           # Central tool registry (no deps)
│   ├── terminal_tool.py      # Shell execution orchestration
│   ├── file_tools.py         # File read/write/search
│   ├── file_operations.py    # File operation helpers
│   ├── patch_parser.py       # Unified diff patch parsing
│   ├── fuzzy_match.py        # Fuzzy file matching
│   ├── todo_tool.py          # Task planning
│   ├── clarify_tool.py       # Interactive questions
│   ├── process_registry.py   # Background process management
│   ├── approval.py           # Dangerous command detection
│   ├── interrupt.py          # Interrupt handling
│   └── environments/         # Terminal execution backends
│       ├── base.py           # BaseEnvironment ABC
│       ├── local.py          # Local subprocess (default)
│       ├── docker.py         # Docker container
│       ├── ssh.py            # SSH remote
│       ├── singularity.py    # Singularity/Apptainer
│       ├── modal.py          # Modal cloud
│       └── daytona.py        # Daytona workspace
│
├── hermes_rs/                # Rust PyO3 extension (workspace member)
│   └── src/
│       ├── lib.rs            # FSM states, transitions, utility functions
│       └── session_db.rs     # RustSessionDB — high-performance SQLite replacement
│
├── hermes_tui/               # Rust TUI binary (workspace member)
│   └── src/
│       ├── main.rs           # Entry point
│       ├── app.rs            # Application state
│       ├── ui.rs             # Ratatui rendering
│       ├── subprocess.rs     # Python agent subprocess management
│       ├── protocol.rs       # JSON message types (ToAgent/FromAgent)
│       ├── colors.rs         # Color definitions
│       ├── mention.rs        # @-mention handling
│       └── multi.rs          # Multi-agent support
│
├── local_models/             # Optional local model server (MLX-VLM)
├── mini-swe-agent/           # Vendored terminal execution backend (v2.2.6)
├── tests/                    # Test suite (~10,000 lines across 39 modules)
├── docs/                     # Design documents
│   ├── AGENTS.md             # Development guide for AI assistants and humans
│   ├── ARCHITECTURE.md       # This file
│   ├── MULTI_AGENT_DESIGN.md # Multi-agent tmux mode design
│   └── SKILL_API_DESIGN.md   # Model-as-a-skill API design
└── README.md                 # User-facing documentation
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

The conversation loop lives in `AIAgent.chat()`. The Rust FSM in `hermes_rs` defines 12 loop states and 4 actions; `agent/loop_driver.py` bridges the Rust state machine to Python, calling back into `AIAgent` methods for LLM calls, tool execution, and context compression.

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
