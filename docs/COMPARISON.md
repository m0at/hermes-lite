# hermes-lite vs hermes-agent

hermes-lite is a focused fork of [hermes-agent](https://github.com/NousResearch/hermes-agent) by Nous Research. The original Hermes Agent is an impressive full-featured AI agent platform — 40+ tools, 5 messaging integrations, browser automation, vision, TTS, RL training, and a skills marketplace. It inspired us to ask: what would a purpose-built local coding agent look like if you started from that foundation, stripped it to the essentials, and rebuilt the critical path in Rust?

hermes-lite is that deep dive. A special-purpose system agent for local coding — model-agnostic, so you can swap in any LLM provider you want.

---

## Philosophy

hermes-agent is a **platform** — it connects to Slack, Discord, Telegram, WhatsApp, browses the web, generates images, transcribes voice, trains RL models, and manages a skills marketplace. It's designed to be everything to everyone.

hermes-lite is a **tool** — it reads files, writes code, runs commands, and coordinates multiple agents. That's it. The narrower scope allowed us to go deep on performance, reliability, and multi-agent coordination in ways that aren't practical in a general-purpose platform.

Both approaches are valid. hermes-agent gives you breadth; hermes-lite gives you depth for local coding specifically.

---

## What We Kept

The core agent engine from Hermes is excellent and we built on top of it:

- **LLM calls via the Anthropic SDK (Claude) or OpenAI SDK (OpenAI/OpenRouter/local) directly** — no litellm
- **Terminal execution** with dangerous-command approval (30 safety patterns)
- **File operations** — read, write, patch (8 fuzzy matching strategies), search (ripgrep-backed)
- **Context compression** — auto-summarization at 85% of context window
- **Prompt caching** — Anthropic cache_control support
- **Session persistence** — SQLite with FTS5 full-text search
- **6 terminal backends** — local, Docker, SSH, Singularity, Modal, Daytona
- **Config system** — YAML config, setup wizard, diagnostics
- **API key redaction** — scrubs secrets from logs

## What We Focused Elsewhere

Features outside the local coding use case were removed to keep the surface area tight:

| Feature | Status | Notes |
|---------|--------|-------|
| Web search | Removed | Not needed for local coding |
| Browser automation | Removed | Cloud dependency (Browserbase) |
| Vision tools | Removed | Image paste into chat still works |
| Image generation | Removed | fal.ai dependency |
| TTS / voice | Removed | Not a coding workflow |
| Slack, Discord, Telegram, WhatsApp | Removed | Separate concern from local agent |
| Skills marketplace | Replaced | Rebuilt as local skill modules — agents load .md-based expertise on demand |
| Mixture-of-agents | Removed | Scope reduction |
| Home Assistant | Removed | Separate concern |
| RL training pipeline | Removed | Research tool, not user-facing |
| Cron scheduler | Removed | Not needed for interactive use |

What remains: 12 focused tools (terminal, process, read_file, write_file, patch, search_files, todo, memory, skills_list, skill_view, clarify, delegate_task) that cover the local coding workflow end to end — including persistent cross-session memory and reusable skill modules.

---

## What We Built New

### Rust FSM (hermes_rs/src/lib.rs)

A formal state machine compiled to native code via PyO3, driving the conversation loop:

```
12 states:  Init → BuildPrompt → ApiCall → ParseResponse → CheckScratchpad →
            AdaptToolCalls → ExecuteTools → CheckInterrupt → CheckContext →
            HandleError → Summarize → Done

5 actions:  Continue, Break, Retry, Nudge, Fail

10 response kinds: Text, ToolCalls, Truncated, TruncatedToolCall, Invalid,
                   EmptyAfterThink, IncompleteScratchpad, InvalidToolNames,
                   InvalidToolJson, CodexIncomplete
```

Every state transition is an explicit match arm. The Python side (`agent/loop_driver.py`) bridges Rust states to Python method calls — the Rust FSM drives, Python executes. This gives you an auditable state graph for every conversation turn: you can inspect exactly which state the FSM was in, what action was taken, and why.

### Rust SessionDB (hermes_rs/src/session_db.rs)

~900 lines of rusqlite replacing the Python SQLite wrapper:

- FTS5 full-text search across all sessions
- WAL mode + mmap for concurrent reads
- Batch insert via `append_messages` (single transaction for N messages)
- All 19 original methods + `reopen_session()` for session branching
- Auto-fallback: tries Rust first, falls back to Python if import fails

### Native TUI (hermes_tui/)

3,600 lines of Rust (ratatui 0.29 + crossterm 0.28):

- **Multi-agent panes** — split/tab layouts, each pane runs an independent agent subprocess
- **@mentions** — `@frontend refactor this`, `@all run tests`, `@reviewer! audit code` (pull response back)
- **Inter-agent delegation** — agents programmatically delegate tasks via `delegate_task`, results routed back automatically
- **/broadcast** — send to all agents simultaneously
- **Streaming** — real-time token display with tool call progress and timing
- **Clarify dialog** — modal overlay for agent questions (text input + choice navigation)
- **Dynamic input** — text entry grows as you type (3–12 lines)

The TUI is a 1.8MB static binary. No Python runtime needed for the frontend.

### Subprocess Protocol

JSON lines over stdin/stdout connecting the TUI to Python agent processes:

**TUI → Agent (6 types):** UserInput, ClarifyResponse, DelegatedTask, CrossAgentContext, Interrupt, Shutdown

**Agent → TUI (13 types):** Ready, SessionInfo, Token, ToolCallStart, ToolCallResult, ResponseComplete, LoopStateChange, ClarifyRequest, DelegateTask, DelegationResult, ContextCompressed, Done, Error

This means the agent runs headless — any frontend can drive it. Multiple agents run simultaneously (one subprocess per pane). The TUI and agent can be on different machines (pipe over SSH). And testing uses the exact same protocol as real usage.

### Persistent Memory (src/tools/memory_tool.py)

Two-scope memory system that survives across sessions and context compression:

- **Global** (`~/.hermes-lite/MEMORY.md`) — user preferences, patterns, conventions that persist across projects
- **Project** (`.hermes/MEMORY.md` in cwd) — architecture decisions, key paths, project-specific context

In multi-agent swarm mode, all agents share the same filesystem, so project memories are automatically visible to every agent. The architect saves context, and any sub-agent can read it — no IPC needed. File locking prevents write corruption from concurrent agents.

Memory is also injected back into the conversation after context compression events, so agents never lose accumulated knowledge even in very long sessions.

### Skills System (src/tools/skill_tools.py)

Reusable expertise modules stored as `.md` files under `~/.hermes-lite/skills/`:

- `skills_list` — browse available skills with descriptions
- `skill_view` — load a skill's full instructions on demand

Skills are indexed in the system prompt so the agent knows what's available. When a task matches a skill (e.g. building a frontend, testing a web app), the agent loads it and follows specialized instructions. Ships with 6 built-in skills: algorithmic-art, brand-guidelines, frontend-design, mcp-builder, theme-factory, webapp-testing.

### Demo Recording System (demo/scripts/tui_demo_driver.py)

Automated demo recording pipeline that drives the TUI through scripted scenarios:

- **tmux automation** — sends keystrokes to a tmux session running the TUI, with instant-paste input
- **13 scripted scenes** — skills browsing, app building, swarm deployment, delegation, shared memory, broadcast, shutdown
- **Pre-flight validation** — verifies agent subprocess connects and API key is valid before recording starts
- **Multi-source API key resolution** — sources from env vars, project `.env`, and `~/.hermes-lite/.env` with fallback chain
- **asciinema recording** — captures terminal output to `.cast` format at configurable resolution (up to 200x55 for 1080p)
- **Post-processing pipeline** — variable speed sections (3x base with 30x fast-forward for long waits), real-world elapsed timer overlay burned into the corner frame-by-frame via PIL, rendered to GIF (agg) and MP4 (ffmpeg)

This isn't a screen recorder — it's a reproducible demo generator. Same script, same scenes, every time.

### Parallel Tool Execution

When the LLM returns multiple tool calls, independent tools run via ThreadPoolExecutor. Inline tools (todo, memory, clarify, delegate_task) still run sequentially since they need conversation state or user interaction.

### Streaming & Interrupt Fixes

Fixed streaming that was silently disabled in subprocess mode (auxiliary API parameters leaked into the main call path). Fixed interrupt handling that consumed non-interrupt messages, breaking multi-turn conversations.

---

## Architecture Comparison

```
hermes-agent:                           hermes-lite:

  Python CLI (prompt_toolkit)             Rust TUI (ratatui) ──── 1.8MB binary
       │                                       │
       │ (same process)                        │ JSON protocol (stdin/stdout)
       ▼                                       ▼
  Python agent loop (while True)          Rust FSM ──► Python loop driver
       │                                       │
       │ (sequential)                          │ (parallel where possible)
       ▼                                       ▼
  40+ Python tools                        12 focused tools
       │                                       │
       ▼                                       ▼
  Python SQLite (hermes_state.py)         Rust SessionDB (rusqlite + FTS5 + WAL)
```

---

## By the Numbers

| Metric | hermes-agent | hermes-lite |
|--------|-------------|-------------|
| Language | Pure Python | Python + 5,152 lines Rust |
| Tools | 40+ | 12 (focused on coding + memory + skills) |
| Tool execution | Sequential | Parallel (ThreadPoolExecutor) |
| State machine | while-loop | Formal Rust FSM (12 states, 5 actions, 10 response kinds) |
| Session DB | Python SQLite | Rust rusqlite (FTS5, WAL, mmap) |
| TUI | Python prompt_toolkit | Rust ratatui (1.8MB binary) |
| Rust extension size | N/A | 4.1 MB (.dylib) |
| Subprocess protocol | None | 19 message types (6 in, 13 out) |
| Multi-agent | Child spawn (depth 2) | Full swarm — split/tab panes, @mentions, delegation, broadcast, shared memory |
| Messaging platforms | 5 | 0 (local only — by design) |
| Memory | In-session only | Persistent (global + project), shared across swarm agents |
| Skills | Built-in only | Loadable skill modules (6 built-in, extensible) |
| Unit tests | — | 1,065 |
| Integration tests | — | 26 (prodpush, real LLM calls) |
| Test code | — | 11,700+ lines |
| Python code | ~50,000+ lines | ~36,000+ lines |

---

## Model Agnostic

hermes-lite calls Claude via the Anthropic SDK directly, and everything else
(OpenAI, OpenRouter, vLLM/rvLLM, and any OpenAI-compatible endpoint) via the
OpenAI SDK directly:

| Provider | Models | Context |
|----------|--------|---------|
| Anthropic | Claude Opus 4/4.5/4.6, Sonnet 4, Haiku 4.5 | 200K |
| OpenAI | GPT-4o, GPT-4-turbo, GPT-4o-mini | 128K |
| OpenRouter | All gateway models | varies |
| Local | rvLLM / vLLM / MLX-VLM via OPENAI_BASE_URL | varies |
| Any | OpenAI chat-completions–compatible endpoint | Auto-probed |

Switch models at any time with `/model` or `--model`. Unknown models are probed at descending context tiers (2M → 1M → 512K → 200K → 128K → 64K → 32K).

The Rust FSM and subprocess protocol are model-independent — they don't care what's behind the LLM call. Swap providers, run local models, use whatever works for your use case.

---

## Portability

**Single binary TUI.** `cargo build --release -p hermes_tui` produces a 1.8MB executable. Copy it to any machine with a terminal.

**pip-installable agent.** `pip install -e .` with 14 core dependencies. The Rust extension is optional — the agent falls back to pure Python if it's missing.

**Six terminal backends.** Run commands locally, in Docker containers, over SSH, in Singularity images, on Modal cloud, or in Daytona workspaces — all through the same tool interface.

**Remote agents over SSH.** Since the TUI communicates with agents over stdin/stdout JSON, you can pipe over SSH:

```bash
ssh server "hermes-lite-agent --subprocess-mode" | ./hermes-tui --pipe
```

**No cloud dependencies.** The only external call is to your LLM provider. Everything else runs locally.

---

## Safety

All safety features from the original Hermes are preserved:

- **Dangerous command approval** — 30 regex patterns (rm -rf, chmod 777, dd, DROP TABLE, fork bombs, pipe-to-shell, etc.)
- **Write-deny list** — blocks writes to ~/.ssh/, ~/.aws/, /etc/sudoers, shell rc files, credentials (19 paths + 6 prefix patterns)
- **API key redaction** — scrubs sk-*, ghp_*, xoxb-* and other secret patterns from logs
- **Prompt injection scanning** — `hermes_rs.scan_context_content()` checks context files

The focused tool count (12 vs 40+) and local-only design naturally shrink the attack surface.

---

## Multi-Agent Swarms

The TUI supports full multi-agent coordination:

- `/split` / `/hsplit` / `/tabs` — spawn agents in split or tab layouts
- `/name` — name agents by role (architect, frontend, tester, etc.)
- `@name msg` — route messages to specific agents
- `@all msg` / `/broadcast` — send to all agents
- `delegate_task` tool — agents programmatically assign work to other agents
- Results automatically routed back to the delegating agent

**Shared memory** ties the swarm together: the architect saves project context to `.hermes/MEMORY.md` (e.g. app structure, agent roles, key decisions), and every sub-agent can read those memories automatically. No manual context passing needed — file-based sharing with locking handles it.

The demo shows an architect agent delegating tasks to 5 specialist agents (frontend, stylist, enhancer, security, QA) who work in parallel on a weather monitoring dashboard. The architect saves project knowledge to shared memory, sub-agents read it, and results are routed back automatically. Each agent runs as an independent subprocess with its own session, model, and conversation history.

---

## Summary

hermes-agent inspired hermes-lite. The original is a broad AI agent platform; hermes-lite is a focused deep dive into what a local coding agent can be when you go all-in on performance, reliability, and multi-agent coordination.

The core value: a model-agnostic system agent with a Rust-accelerated foundation, persistent memory across sessions and agents, loadable skill modules, and a multi-agent swarm that shares context automatically. Point it at any LLM provider — Anthropic, OpenAI, open-source, local — and get a fast, auditable coding environment that runs entirely on your machine.
