# hermes-lite — Development Guide

Instructions for AI coding assistants and human developers.

hermes-lite is a stripped-down local coding agent CLI with Anthropic-first runtime and optional local model support.

## Project Structure

```
hermes-lite/
├── src/                     # Python source (package root)
│   ├── run_agent.py         # AIAgent class (core conversation loop)
│   ├── cli.py               # Interactive CLI (HermesCLI class)
│   ├── model_tools.py       # Tool orchestration layer
│   ├── toolsets.py          # Tool groupings
│   ├── hermes_state.py      # SQLite session state
│   ├── hermes_constants.py  # Shared constants
│   ├── utils.py             # Atomic JSON write
│   ├── agent/               # Agent internals
│   ├── hermes_cli/          # CLI commands and configuration
│   ├── tools/               # Tool implementations + terminal backends
│   └── local_models/        # Optional local model server (MLX)
├── hermes_rs/               # Rust PyO3 extension (FSM + SessionDB)
├── hermes_tui/              # Rust TUI binary (ratatui)
├── vendor/
│   └── mini-swe-agent/      # Vendored terminal execution backend (v2.2.6)
├── tests/                   # Test suite (1065 unit + 26 integration)
├── docs/                    # Design documents
└── demo/                    # Demo scenarios and recording scripts
```

**User configuration** (stored in `~/.hermes-lite/`):
- `~/.hermes-lite/config.yaml` — Settings (model, terminal, toolsets, etc.)
- `~/.hermes-lite/.env` — API keys and secrets

## File Dependency Chain

```
tools/registry.py  (no deps — imported by all tool files)
       ↑
tools/*.py  (each calls registry.register() at import time)
       ↑
model_tools.py  (imports tools/registry + triggers tool discovery)
       ↑
run_agent.py, cli.py
```

## AIAgent Class

The main agent is in `run_agent.py`:

```python
class AIAgent:
    def __init__(
        self,
        model: str = "claude-sonnet-4-5-20250929",
        api_key: str = None,
        base_url: str = None,
        max_iterations: int = 60,
        enabled_toolsets: list = None,
        quiet_mode: bool = False,
    ):
        ...

    def chat(self, user_message: str) -> str:
        ...
```

### Agent Loop

```
1. Add user message to conversation
2. Call LLM with tools
3. If LLM returns tool calls:
   - Execute each tool
   - Add tool results to conversation
   - Go to step 2
4. If LLM returns text response:
   - Return response to user
```

## CLI Architecture (cli.py)

The interactive CLI uses:
- **Rich** — Welcome banner and styled panels
- **prompt_toolkit** — Fixed input area with history and slash command autocomplete
- **KawaiiSpinner** — Animated spinners during API calls

Key slash commands: `/help`, `/clear`, `/model`, `/personality`, `/verbose`, `/context`, `/compact`

## Runtime Providers

Two providers are supported:

1. **Anthropic** (default) — Direct API via `ANTHROPIC_API_KEY`
2. **Local** — OpenAI-compatible endpoint at `http://127.0.0.1:8800/v1` (e.g. MLX-VLM serving Qwen)

Provider resolution order: CLI flag → `HERMES_INFERENCE_PROVIDER` env → `config.yaml model.provider` → default (anthropic)

## Toolsets

The lite build exposes one default toolset (`hermes-lite-cli`):

| Tool | Description |
|------|-------------|
| `terminal` | Local shell execution |
| `process` | Background process management |
| `read_file` | Read file contents |
| `write_file` | Write/create files |
| `patch` | Apply unified diffs |
| `search_files` | Grep/glob file search |
| `todo` | Task planning |
| `memory` | Persistent cross-session memory (global + project, shared across swarm) |
| `skills_list` | Browse available skill modules |
| `skill_view` | Load skill instructions for specialized tasks |
| `clarify` | Ask user a question |

## Configuration System

Config in `~/.hermes-lite/config.yaml`, secrets in `~/.hermes-lite/.env`.

### Adding config options

1. Add to `DEFAULT_CONFIG` in `hermes_cli/config.py`
2. Bump `_config_version` for required fields
3. Migration runs automatically on `hermes-lite config migrate`

### Adding .env variables

Add to `OPTIONAL_ENV_VARS` in `hermes_cli/config.py` with metadata.

## Testing

```bash
python3 -m pytest tests/ -v
python3 -m pytest tests/ -v -m integration  # integration tests (require services)
```

Tests are in `tests/` mirroring the source layout. The `conftest.py` redirects `HERMES_HOME` to a temp directory.
