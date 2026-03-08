# hermes-lite

A stripped-down Mac coding agent that wraps [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) (v2.2.6) for terminal execution and supports either Anthropic's API or a local Qwen model via MLX-VLM.

## What it is

hermes-lite is a minimal coding agent CLI for macOS, forked from Hermes and cut down to a local-first workflow. It uses mini-swe-agent as its terminal execution backend and runs tasks against your codebase via shell commands, file tools, and a planning loop. You can drive it with Anthropic's API or entirely on-device with a 4-bit quantized Qwen3.5-9B model served by MLX-VLM.

## What's included

- Interactive Claude-style CLI built with `prompt_toolkit` and slash commands
- Shell execution with dangerous-command approval (local, Docker, SSH, Singularity, Modal, and Daytona backends)
- Background process management
- File read / write / patch / search tools
- Todo-based task planning
- Clarify prompts — agent can ask you a question mid-task before proceeding
- SQLite session persistence and resume (`~/.hermes-lite/state.db`)
- Auto context compression when approaching the context limit
- Anthropic prompt caching — auto-enabled, typically ~75% reduction in input token costs
- Optional local Qwen3.5-9B via MLX-VLM (`pip install -e ".[local]"`)

## What's not included by default

The following capabilities were removed from the default product surface. Config stubs may still appear in `.env.example` but the features are not active:

- Web search and web content extraction
- Browser automation
- Image and vision analysis
- Messaging integrations (Slack, WhatsApp, Discord, Telegram)
- Reinforcement learning tooling
- Home Assistant integration

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

For local model support (MLX-VLM, Starlette, Uvicorn):

```bash
pip install -e ".[local]"
```

Requires Python 3.10+.

## Setup

```bash
hermes-lite setup
```

This writes your configuration to `~/.hermes-lite/` (separate from `~/.hermes`). Then export your Anthropic key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

To use a local model instead, select **Local** during setup. hermes-lite will target the MLX-VLM server at `http://127.0.0.1:8800/v1` serving `mlx-community/Qwen3.5-9B-4bit`.

Logs are written to `~/.hermes-lite/logs/errors.log`.

---

## Usage

### Entry points

| Command | Description |
|---------|-------------|
| `hermes-lite` | Main CLI — interactive REPL or subcommands |
| `hermes-lite-agent` | Headless agent runner (non-interactive) |
| `hermes-lite-serve` | Local model server |

---

### `hermes-lite` — interactive REPL

Running `hermes-lite` with no subcommand opens an interactive REPL session.

```bash
hermes-lite
```

Resume the most recent session directly from your shell:

```bash
hermes-lite --continue
hermes-lite -c
```

---

### `hermes-lite chat` — conversational agent

```
hermes-lite chat [OPTIONS]
```

| Flag | Short | Description |
|------|-------|-------------|
| `--query TEXT` | `-q` | Single-shot query (non-interactive) |
| `--model TEXT` | `-m` | Override the active model |
| `--toolsets TEXT` | `-t` | Comma-separated list of toolsets to enable |
| `--provider {anthropic,local}` | | Model provider |
| `--verbose` | `-v` | Enable verbose output |
| `--resume SESSION_ID` | `-r` | Resume a specific session by ID |
| `--continue` | `-c` | Resume the most recent session |

**Examples**

```bash
hermes-lite chat -q "summarize this repo"
hermes-lite chat --provider anthropic --model claude-opus-4-6
hermes-lite chat -t "terminal,file"
hermes-lite chat --resume abc123
hermes-lite chat --continue
```

---

### `hermes-lite setup` — setup wizard

Interactive wizard that configures your API keys and preferences. Config is stored in `~/.hermes-lite/`.

```bash
hermes-lite setup
```

---

### `hermes-lite model` — model switcher

Interactive picker to switch between Anthropic models or the local model.

```bash
hermes-lite model
```

---

### `hermes-lite status` — runtime status

Show the active configuration and local server health.

```bash
hermes-lite status
hermes-lite status --all   # include all registered providers and models
```

---

### `hermes-lite doctor` — diagnostics

Checks API key validity, local server reachability on port 8800, and other prerequisites.

```bash
hermes-lite doctor
```

---

### `hermes-lite config` — configuration management

| Subcommand | Description |
|------------|-------------|
| `edit` | Open the config file in `$EDITOR` |
| `set KEY VALUE` | Set a single config key |
| `check` | Validate the current config |
| `migrate` | Migrate config to the latest schema version |

```bash
hermes-lite config edit
hermes-lite config set default_model claude-sonnet-4-6
hermes-lite config check
hermes-lite config migrate
```

---

### `hermes-lite version`

```bash
hermes-lite version
hermes-lite -V
hermes-lite --version
```

---

### `hermes-lite serve` — local model server

Alias for `hermes-lite-serve`. Launches an MLX-VLM server (default port 8800).

```bash
hermes-lite serve qwen
hermes-lite-serve qwen --port 8800
```

---

### `hermes-lite-agent` — headless agent

Non-interactive agent runner for scripting and automation.

| Flag | Short | Description |
|------|-------|-------------|
| `--model TEXT` | `-m` | Override the active model |
| `--provider {anthropic,local}` | | Model provider |
| `--toolsets TEXT` | `-t` | Comma-separated list of toolsets |
| `--resume SESSION_ID` | `-r` | Resume a session by ID |

```bash
hermes-lite-agent --model claude-sonnet-4-6 --toolsets terminal,file
```

---

### Interactive slash commands

Available inside the REPL (`hermes-lite` or `hermes-lite chat`):

| Command | Description |
|---------|-------------|
| `/help` | Show available slash commands |
| `/clear` | Clear the current conversation context |
| `/model` | Switch model mid-session |
| `/personality` | Change the assistant personality/system prompt |
| `/verbose` | Toggle verbose output |
| `/context` | Show current context window usage |
| `/compact` | Compact conversation history to save context |
| `/tools` | List enabled tools and toolsets |
| `/save` | Save the current session |
| `/history` | Browse past sessions |

---

## Tools

hermes-lite ships 8 tools, all included in the default toolset.

| Tool | Description |
|------|-------------|
| `terminal` | Execute shell commands in foreground or background; dangerous commands trigger an approval prompt |
| `process` | Full lifecycle management for background processes — spawn, poll, read logs, wait, kill, write to stdin; 200 KB rolling output buffer; crash recovery via JSON checkpoint |
| `read_file` | Read file contents with line numbers and pagination; suggests similar filenames on a miss |
| `write_file` | Write or create files; automatically creates parent directories; enforces a write-deny list for sensitive paths |
| `patch` | Apply find-replace patches using 9 fuzzy-matching strategies or unified V4A diff format; runs a syntax check after each edit |
| `search_files` | ripgrep-backed search; supports regex content search or glob file find; output modes: `content`, `files_only`, `count` |
| `todo` | In-memory task list with statuses `pending`, `in_progress`, `completed`, `cancelled`; context-compression-aware |
| `clarify` | Ask the user a multiple-choice (up to 4 options) or open-ended question mid-task |

## Toolsets

Tools are grouped into named toolsets. Pass one or more comma-separated toolset names with `-t`.

| Toolset | Tools included |
|---------|---------------|
| `terminal` | `terminal`, `process` |
| `file` | `read_file`, `write_file`, `patch`, `search_files` |
| `todo` | `todo` |
| `clarify` | `clarify` |
| `hermes-lite-cli` | All of the above (default) |

```bash
hermes-lite chat -t "terminal,file"
hermes-lite chat -t "todo,clarify"
```

## Terminal backends

The `terminal` and `process` tools delegate execution to a configurable backend. Set `TERMINAL_ENV` to select one. Default is `local`.

| Backend | Description | Required config |
|---------|-------------|-----------------|
| `local` | Subprocess on the current machine (default) | — |
| `docker` | Isolated Docker container | `TERMINAL_DOCKER_IMAGE` |
| `ssh` | Remote machine over SSH | `TERMINAL_SSH_HOST`, `TERMINAL_SSH_USER`, `TERMINAL_SSH_PORT`, `TERMINAL_SSH_KEY` |
| `singularity` | Singularity/Apptainer container | `TERMINAL_SINGULARITY_IMAGE` |
| `modal` | Modal cloud compute | Run `modal setup` first |
| `daytona` | Daytona workspace | — |

```bash
# Docker
TERMINAL_ENV=docker TERMINAL_DOCKER_IMAGE=ubuntu:24.04 hermes-lite chat

# SSH
TERMINAL_ENV=ssh TERMINAL_SSH_HOST=myserver.example.com TERMINAL_SSH_USER=ubuntu hermes-lite chat
```

The terminal backend is powered by a vendored copy of [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) (v2.2.6) in `mini-swe-agent/`. hermes-lite sets `MSWEA_GLOBAL_CONFIG_DIR=~/.hermes-lite` so configuration is shared automatically — no separate installation required.

## Safety

**Dangerous command detection** — commands involving destructive or privileged operations (`rm`, `chmod`, `kill`, `dd`, `iptables`, and others) are intercepted and require explicit approval. Approvals can be permanently allowed for the session.

**Write protection** — `write_file` and `patch` enforce a deny list that blocks writes to sensitive paths:

- `~/.ssh/`, `~/.aws/`, `~/.kube/`
- `/etc/sudoers`, `/etc/passwd`, `/etc/shadow`
- Shell rc files (`.bashrc`, `.zshrc`, etc.)

**Sudo prompting** — commands requiring elevated privileges trigger a password prompt; the credential is cached for the session.

---

## Runtime providers

hermes-lite supports two runtime providers: **Anthropic** (default) and **Local**. Switch interactively with `hermes-lite model` or pass `--provider local` to any command.

### Anthropic

Requires `ANTHROPIC_API_KEY`. Calls the Anthropic API directly at `https://api.anthropic.com`.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
hermes-lite chat
```

Prompt caching is enabled automatically using the `system_and_3` strategy, which inserts `cache_control` breakpoints on the system prompt and the three most recent eligible turns. This typically reduces input token costs by ~75% on repeated or resumed sessions.

### Local

Routes requests to an OpenAI-compatible endpoint at `http://127.0.0.1:8800/v1`. No API key required. Default model is `local/qwen3.5-9b`.

```bash
hermes-lite chat --provider local
# or select Local via: hermes-lite model
```

## Local Qwen model

Runs [mlx-community/Qwen3.5-9B-4bit](https://huggingface.co/mlx-community/Qwen3.5-9B-4bit) — 4-bit quantized, accelerated on Apple Silicon GPU via MLX.

**Requirement:** Apple Silicon Mac with local extras installed:

```bash
pip install -e ".[local]"
```

**Start the server manually:**

```bash
hermes-lite-serve qwen            # default port 8800
hermes-lite-serve qwen --port 9000
```

**Auto-start:** If you select the local provider and the server isn't running, the CLI spawns it automatically and waits up to 120 seconds for it to become ready.

## Context compression

When a conversation approaches the model's context limit, compression triggers automatically at 85% of the context window.

When triggered:
1. The head and tail of the conversation are preserved intact.
2. Middle turns are summarized by a fast auxiliary model.
3. A new session is created with a `parent_session_id` chain linking it to the original.

Configure in `~/.hermes-lite/config.yaml`:

```yaml
compression:
  enabled: true
  threshold: 0.85
```

## Session persistence and resume

All conversations are stored in `~/.hermes-lite/state.db` (SQLite, schema v2, WAL mode, FTS5 full-text search). Every message is recorded with role, content, tool calls, finish reason, and token counts.

```bash
hermes-lite --continue                      # resume last session
hermes-lite chat --resume SESSION_ID        # resume specific session
```

Search message history from within the REPL with `/history`.

Every agent run also writes the full conversation to `~/.hermes-lite/logs/session_YYYYMMDD_HHMMSS_UUID.json` in JSONL/ShareGPT format.

---

## Configuration

All configuration lives under `~/.hermes-lite/`.

| Path | Purpose |
|------|---------|
| `~/.hermes-lite/config.yaml` | Main configuration (model, provider, compression) |
| `~/.hermes-lite/.env` | Secrets — API keys and terminal backend variables |
| `~/.hermes-lite/state.db` | SQLite session history |
| `~/.hermes-lite/logs/` | Error logs and trajectory JSONL files |

**Key `config.yaml` fields:**

```yaml
model:
  default: "local/qwen3.5-9b"
  provider: "local"                          # or "anthropic"
  base_url: "http://127.0.0.1:8800/v1"      # or https://api.anthropic.com

compression:
  enabled: true
  threshold: 0.85
```

## Environment variables

Place these in `~/.hermes-lite/.env`:

**Core**

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Required for the Anthropic provider |
| `OPENAI_API_KEY` | Set to `"local"` for the local provider (litellm compatibility) |
| `OPENAI_BASE_URL` | Set to `http://127.0.0.1:8800/v1` for local inference |

**Terminal backend**

| Variable | Description |
|----------|-------------|
| `TERMINAL_ENV` | `local` (default), `docker`, `ssh`, `singularity`, `modal`, `daytona` |
| `TERMINAL_DOCKER_IMAGE` | Docker image for the `docker` backend |
| `TERMINAL_SSH_HOST` / `_USER` / `_PORT` / `_KEY` | SSH backend connection settings |
| `TERMINAL_SINGULARITY_IMAGE` | Singularity image path |
| `TERMINAL_CWD` | Working directory for terminal commands |
| `TERMINAL_TIMEOUT` | Per-command timeout in seconds (default: `60`) |
| `TERMINAL_LIFETIME_SECONDS` | Auto-cleanup idle environments (default: `300`) |
| `SUDO_PASSWORD` | Sudo password — use only on trusted machines |

---

## Architecture

```
tools/registry.py          # no dependencies — tool registration
    ↑
tools/*.py                 # register tools at import time
    ↑
model_tools.py             # lazy imports, schema generation, function call dispatch
    ↑
run_agent.py / cli.py      # AIAgent class, HermesCLI class, conversation loop
    ↑
hermes_cli/main.py         # argparse entry point
```

Key modules:

- `run_agent.py` — `AIAgent`: conversation loop, tool dispatch, LLM API calls
- `cli.py` — `HermesCLI`: interactive REPL, prompt_toolkit integration
- `hermes_state.py` — `SessionDB`: SQLite-backed session persistence
- `model_tools.py` — tool schema generation and function call dispatch
- `agent/` — 14 focused modules: `context_compressor`, `prompt_builder`, `prompt_caching`, `tool_call_parser`, `trajectory`, `loop_driver`, and others
- `hermes_cli/` — 14 modules: config, setup, status, doctor, commands, display, color schemes
- `tools/` — 12 tool modules + 6 environment backend implementations
- `local_models/` — MLX-VLM server wrapper (`serve.py`)
- `mini-swe-agent/` — vendored terminal execution backend

## Development

```bash
# Full test suite
python3 -m pytest tests/ -v

# Integration tests only
python3 -m pytest tests/ -v -m integration

# Skip integration tests (CI default)
python3 -m pytest tests/ -q --ignore=tests/integration
```

39 test modules (~10,000 lines) in four categories:

| Category | Modules |
|----------|---------|
| `tests/agent/` | 12 — agent internals |
| `tests/tools/` | 15 — tool implementations |
| `tests/hermes_cli/` | 3 — CLI behavior |
| Core | 9 — shared utilities |

CI runs on every push and PR to `main` via `.github/workflows/tests.yml` (Python 3.11, ubuntu-latest, integration tests excluded).
