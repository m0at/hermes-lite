# Multi-Agent Tmux Mode — Design Document

## Current Architecture Summary

The Hermes TUI (`hermes_tui`) is a single-process ratatui application that:

- Spawns one Python agent subprocess (`run_agent.py --subprocess-mode`)
- Communicates via JSON-over-stdin/stdout (`ToAgent`/`FromAgent` enums)
- Maintains a single `App` struct holding conversation history, token counts, scroll state, and agent status
- Uses a synchronous event loop: poll terminal events (50ms tick), poll agent messages, render

The goal is to extend this into a **multi-agent tmux mode** where two or more agents run simultaneously with independent conversations, the user can switch between them, and agents can reference or invoke each other.

---

## 1. Architecture Options

### Option A: Single TUI Process + Multiple Subprocesses + Ratatui Splits

The TUI process owns N `AgentProcess` instances, each with its own `App` state (conversation, tokens, scroll). The terminal is divided into panes using ratatui's `Layout` system. One event loop drains all agent channels.

**Pros:**
- Simplest to implement — everything lives in one process, one event loop
- No IPC between TUI processes to coordinate
- Ratatui already supports arbitrary layout splits via `Layout::default().direction(...).constraints(...)`
- All agent state is in-memory, trivially accessible for cross-agent queries
- User sees a unified UI with consistent keybindings

**Cons:**
- Single process must handle N subprocess stdout readers + terminal events without blocking
- Layout logic gets more complex (dynamic pane counts, resizing)
- If the TUI process crashes, everything dies

### Option B: Actual tmux + Separate TUI Processes + Shared IPC

Each agent gets its own full TUI process. A coordinator (tmux, or a custom session manager) tiles them. Inter-agent communication uses Unix domain sockets or shared SQLite.

**Pros:**
- Each TUI process is isolated — one crashing doesn't kill the others
- Can leverage tmux's mature pane management, resize, detach/reattach
- Each process is simple (stays close to current single-agent design)

**Cons:**
- Loses unified keybinding control (tmux captures its own prefix key)
- Inter-agent communication requires a separate daemon or shared-state mechanism
- User experience is fragmented — two separate scroll states, status bars, input areas
- "Pull in" semantics require a sidecar IPC protocol on top of the agent protocol
- Cannot render cross-pane UI elements (e.g., a broadcast indicator, agent status overview)
- Deployment complexity: user must have tmux installed, scripts to orchestrate

### Option C: Single TUI Process + Tabbed/Split Views + Internal Message Bus

Same as Option A but adds an internal message bus (tokio broadcast channel) for agent-to-agent communication. Agents don't talk to each other directly — the TUI mediates all cross-agent messages, translating them into the existing `ToAgent` protocol.

**Pros:**
- All the benefits of Option A
- The message bus is a natural place to implement "pull in", delegation, and broadcast
- The TUI can enforce loop-prevention policies centrally
- Cross-agent context is trivially available (it's all in the same process memory)

**Cons:**
- Slightly more complex than A (the bus layer), but not meaningfully so
- Same single-process risk as A

### Recommendation: Option C

Option A and C are nearly identical — C is just A with explicit naming of the internal communication pattern. The key insight is that **the TUI is already the mediator** between user and agent. Extending it to mediate between agents is the natural evolution. Option B's isolation benefits don't justify the UX fragmentation and IPC complexity.

The "message bus" in Option C doesn't need to be a heavy abstraction. It's a `HashMap<AgentId, mpsc::Sender<ToAgent>>` plus a `tokio::sync::broadcast` channel for events any agent can subscribe to. The TUI intercepts cross-agent requests before they hit the wire.

---

## 2. Agent-to-Agent Communication

### 2.1 Communication Model

Agents never talk directly to each other. All communication flows through the TUI:

```
User ──┐
       ├──► TUI Orchestrator ──► Agent 0 (subprocess)
       │         │
       │         ├──► Agent 1 (subprocess)
       │         │
       │         └──► Agent N (subprocess)
       │
       └── [keyboard events]
```

The TUI orchestrator:
1. Routes user input to the focused agent
2. Intercepts `@agent` mentions and cross-agent tool calls
3. Translates delegation requests into `ToAgent::UserInput` messages to the target agent
4. Copies results back to the requesting agent's conversation

### 2.2 Protocol Extensions

New `ToAgent` variants:

```rust
#[derive(Debug, Serialize)]
#[serde(tag = "type")]
pub enum ToAgent {
    // ... existing variants ...

    /// Injected context from another agent's conversation.
    /// The agent treats this as additional system context, not user input.
    CrossAgentContext {
        from_agent: String,       // e.g. "a2"
        summary: String,          // what the other agent said/concluded
        full_history: Option<String>, // optional: serialized message history
    },

    /// A sub-task delegated from another agent via the TUI.
    /// The agent should treat this like a user message but tag its
    /// response so the TUI can route it back.
    DelegatedTask {
        from_agent: String,
        request_id: String,       // for correlation
        task: String,
        context: String,          // relevant context from the requesting agent
    },
}
```

New `FromAgent` variants:

```rust
#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
pub enum FromAgent {
    // ... existing variants ...

    /// Agent requests information from another agent's conversation.
    PeerQuery {
        target_agent: String,     // which agent to ask
        question: String,
        request_id: String,
    },

    /// Agent delegates a sub-task to another agent.
    DelegateTask {
        target_agent: String,
        task: String,
        context: String,
        request_id: String,
    },

    /// Response to a delegated task (returned to the TUI, which
    /// routes it back to the requesting agent as CrossAgentContext).
    DelegationResult {
        request_id: String,
        result: String,
        success: bool,
    },
}
```

### 2.3 The "Pull In" Mechanism

There are two modes of cross-agent interaction:

**Mode 1: User-initiated ("@agent1 what do you think?")**

The user types `@agent1 summarize the API design` in agent0's input. The TUI:
1. Parses the `@agent1` prefix
2. Sends `ToAgent::UserInput` to agent1 with the message
3. Collects agent1's response (waits for `FromAgent::Done`)
4. Injects the response into agent0's conversation as a system message: `"[agent1 says]: ..."`

**Mode 2: Agent-initiated (agent calls a tool)**

The Python agent has a new tool `ask_peer` (or `delegate_to`):

```python
# In the agent's toolset when --subprocess-mode --multi-agent
def ask_peer(target: str, question: str) -> str:
    """Ask another running agent a question. Returns their response."""
    # This emits FromAgent::PeerQuery over stdout
    # The TUI handles it and injects the answer back
    ...
```

When the TUI receives `FromAgent::PeerQuery`:
1. Look up `target_agent` in the agent registry
2. Send `ToAgent::DelegatedTask` to the target
3. Wait for the target's `FromAgent::DelegationResult`
4. Inject the result back to the requesting agent as `ToAgent::CrossAgentContext`

### 2.4 Avoiding Infinite Loops

This is the hardest problem. Agent A asks Agent B, who asks Agent A, who asks Agent B...

**Solution: Delegation depth counter + TTL.**

```rust
struct DelegationContext {
    request_id: String,
    origin_agent: AgentId,    // who started the chain
    depth: u8,                // incremented at each hop
    max_depth: u8,            // default: 2
}
```

Rules enforced by the TUI orchestrator:
1. `max_depth` defaults to 2. A delegated task that would exceed this is rejected immediately with an error message: "Delegation depth limit reached."
2. An agent cannot delegate back to the agent that delegated to it (no direct cycles). The TUI checks `origin_agent` and rejects.
3. Delegated tasks have a timeout (30 seconds default). If the target agent doesn't complete in time, the TUI returns a timeout error.
4. The `ask_peer` tool is **not available** inside delegated tasks (strip it from the toolset). This is the simplest hard guarantee against infinite loops.

**Recommendation:** Start with rule 4 (no nested delegation). It's the easiest to implement and eliminates all loop risks. Add depth-based delegation later if needed.

---

## 3. User Experience

### 3.1 Layout Modes

Two layout modes, toggled with `/split` and `/tabs`:

**Split mode** (default when multiple agents exist):
```
┌─── a1 (focused) ───────────────────────┬─── a2 ──────────────────────────────┐
│                                         │                                      │
│  ── ⚕ Hermes ──────────                │  ── ⚕ Hermes ──────────              │
│  Here's the API design...               │  I've refactored the tests...        │
│                                         │                                      │
│  ┊ ✓ read_file    src/main.rs           │  ┊ ✓ bash        cargo test          │
│  ┊ ⠿ edit_file    Cargo.toml            │                                      │
│                                         │                                      │
├─────────────────────────────────────────┼──────────────────────────────────────┤
│ ⠹ Iteration 3 │ llm_call               │  Ready                               │
├─────────────────────────────────────────┼──────────────────────────────────────┤
│ ┌─ Enter to send ─────────────────────┐ │                                      │
│ │ █                                   │ │                                      │
│ └─────────────────────────────────────┘ │                                      │
├─────────────────────────────────────────┴──────────────────────────────────────┤
│ claude-sonnet-4-20250514 │ 12,340 tokens (6%) │ 2 agents │ Ctrl+← / Ctrl+→ focus │
└───────────────────────────────────────────────────────────────────────────────┘
```

Key details:
- Only the focused pane has an active input area
- Unfocused panes show their conversation read-only (dimmed border)
- A shared status bar at the bottom shows global info
- Vertical split by default; `/hsplit` for horizontal

**Tab mode:**
```
┌ [a1] │ a2 │ + ──────────────────────────────────────────────────────┐
│                                                                              │
│  (full-width single agent view, same as current)                             │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

Tab bar at top. Tabs show agent name, a spinner if busy, and a dot if there's unread output.

### 3.2 Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+Left` / `Ctrl+Right` | Switch focus to previous/next pane |
| `Ctrl+1` .. `Ctrl+9` | Focus pane N directly |
| `Ctrl+W` | Close focused pane (kill agent, confirm if busy) |
| `Ctrl+T` | Toggle between split and tab mode |
| `Ctrl+B` | Enter broadcast mode (next message goes to all agents) |

These bindings are chosen to avoid conflicts with existing ones (Ctrl+C for interrupt, Ctrl+D for exit, PageUp/Down for scroll).

### 3.3 Cross-Pane Message Routing

The user can address another agent from any pane's input:

- **`@a2 <message>`** — Send message to a2, display the response in a2's pane. The current pane gets a system note: "[Sent to a2: <message>]"
- **`@a2! <message>`** — Send to a2, AND inject a2's response back into the current pane as context. The `!` means "pull the answer back here."
- **`@all <message>`** — Broadcast to all agents (same as `/broadcast <message>`)

### 3.4 Broadcast Mode

Activated by `Ctrl+B` or `/broadcast`. The input area border changes color (e.g., yellow) and shows "BROADCAST" label. The next Enter-submitted message goes to all agents simultaneously. After sending, broadcast mode deactivates (one-shot). For persistent broadcast, use `/broadcast-lock` (toggle).

### 3.5 Agent Naming

Agents are named automatically: `a1`, `a2`, `a3`, etc. Short names for fast `@` mentions:

- `@a1 summarize the API` — send to agent 1
- `@a2! what did you find?` — send to agent 2, pull answer back
- `@all refactor this` — broadcast

The user can rename with `/name researcher`, then use `@researcher` instead. Names must be unique. The pane title shows the short name (or custom name if set).

---

## 4. Implementation Plan

### Phase 1: Multi-Pane Infrastructure (no cross-agent communication)

**Goal:** Run two independent agents side by side with pane switching.

#### 4.1 Data Structures

```rust
/// Unique identifier for each agent pane (1-indexed).
type AgentId = u8;

/// Per-agent state. This is the current App struct, minus global UI state.
struct AgentPane {
    id: AgentId,
    name: String,                           // "a1", "a2", ... or user-chosen

    // Conversation (moved from App)
    messages: Vec<Message>,
    scroll_offset: u16,
    history_height: u16,

    // Session
    session_id: String,
    model: String,

    // Tokens
    input_tokens: u32,
    output_tokens: u32,
    context_length: u32,

    // Agent state
    agent_running: bool,
    loop_state: String,
    loop_iteration: u32,
    streaming_text: String,
    is_thinking: bool,

    // Spinner (per-agent since each can be independently busy)
    spinner_frame: usize,
    last_spinner_tick: Instant,

    // Status
    status_message: Option<(String, Instant)>,

    // Has unread output since last focus
    unread: bool,
}

/// The subprocess handle + channel for one agent.
struct AgentHandle {
    id: AgentId,
    to_agent: mpsc::Sender<ToAgent>,
    from_agent: mpsc::Receiver<FromAgent>,
}

/// Layout mode for displaying multiple panes.
enum LayoutMode {
    Split { direction: Direction },  // Vertical or Horizontal
    Tabs,
}

/// Top-level app state.
struct MultiApp {
    panes: Vec<AgentPane>,
    handles: Vec<AgentHandle>,
    focused: AgentId,
    layout_mode: LayoutMode,
    broadcast_mode: bool,

    // Global state
    running: bool,
    active_pane: ActivePane,  // Input vs History (within focused agent)
    show_thinking: bool,
    working_dir: String,
}
```

#### 4.2 Modified Event Loop

```rust
// main.rs — multi-agent event loop (pseudocode)

#[tokio::main]
async fn main() -> io::Result<()> {
    // Terminal setup (same as now)
    let mut app = MultiApp::new();

    // Spawn initial agent
    app.spawn_agent().await?;

    // Unified from-agent channel: all agent readers merge into one
    // Each AgentHandle's from_agent is drained in the loop
    let mut textareas: Vec<TextArea> = vec![make_textarea()];

    while app.running {
        terminal.draw(|frame| {
            match app.layout_mode {
                LayoutMode::Split { direction } => {
                    render_split(frame, &mut app, &textareas);
                }
                LayoutMode::Tabs => {
                    render_tabs(frame, &mut app, &textareas);
                }
            }
            render_global_status_bar(frame, &app);
        })?;

        // Tick all running agent spinners
        for pane in &mut app.panes {
            if pane.agent_running {
                pane.tick_spinner();
            }
        }

        // Poll terminal events
        if event::poll(Duration::from_millis(50))? {
            match event::read()? {
                Event::Key(key) => {
                    handle_global_keys(&mut app, &mut textareas, key);
                }
                _ => {}
            }
        }

        // Drain ALL agent message channels
        for handle in &mut app.handles {
            loop {
                match handle.from_agent.try_recv() {
                    Ok(msg) => {
                        let pane = &mut app.panes[handle.id as usize];
                        handle_agent_message(pane, msg);
                        if handle.id != app.focused {
                            pane.unread = true;
                        }
                    }
                    Err(TryRecvError::Empty) => break,
                    Err(TryRecvError::Disconnected) => {
                        app.panes[handle.id as usize].agent_running = false;
                        app.panes[handle.id as usize]
                            .set_status("Agent disconnected".into());
                        break;
                    }
                }
            }
        }
    }

    // Shutdown all agents
    for handle in app.handles {
        let _ = handle.to_agent.try_send(ToAgent::Shutdown);
    }

    // Terminal teardown
    Ok(())
}
```

#### 4.3 Split Layout Rendering

```rust
fn render_split(frame: &mut Frame, app: &mut MultiApp, textareas: &[TextArea]) {
    let area = frame.area();
    let n = app.panes.len();

    // Reserve bottom row for global status bar
    let [main_area, status_area] = Layout::vertical([
        Constraint::Min(0),
        Constraint::Length(1),
    ]).areas(area);

    // Split main area into N equal columns (or rows for hsplit)
    let constraints: Vec<Constraint> = (0..n)
        .map(|_| Constraint::Ratio(1, n as u32))
        .collect();

    let pane_areas = Layout::default()
        .direction(app.layout_mode.direction())
        .constraints(constraints)
        .split(main_area);

    for (i, pane_area) in pane_areas.iter().enumerate() {
        let is_focused = app.focused == i as u8;
        let pane = &mut app.panes[i];

        // Each pane gets its own internal vertical layout
        let inner_layout = build_pane_layout(*pane_area, is_focused);

        // Pane border + title
        let border_color = if is_focused { colors::GOLD } else { colors::DIM };
        let title = format!(
            " {} {} ",
            pane.name,
            if pane.agent_running { "●" } else { "" }
        );
        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(Style::default().fg(border_color))
            .title(title);

        let inner = block.inner(*pane_area);
        frame.render_widget(block, *pane_area);

        // Render pane contents inside the border
        render_pane_history(pane, frame, inner_layout.history);
        render_pane_spinner(pane, frame, inner_layout.spinner);

        if is_focused {
            render_input_area_minimal(frame, inner_layout.input, &textareas[i]);
        }
    }
}
```

#### 4.4 New Slash Commands

| Command | Description |
|---------|-------------|
| `/split` | Split: spawn new agent in a vertical split |
| `/hsplit` | Split: spawn new agent in a horizontal split |
| `/tabs` | Switch to tab mode |
| `/close` | Close focused agent pane |
| `/name <name>` | Rename focused agent |
| `/focus <name\|N>` | Focus agent by name or index |
| `/broadcast <msg>` | Send message to all agents |
| `/ask <agent> <msg>` | Send message to named agent, pull response back |
| `/list-agents` | Show all agents and their status |

```rust
pub enum SlashCommand {
    // ... existing variants ...
    Split,
    HSplit,
    Tabs,
    Close,
    Name(String),
    Focus(String),
    Broadcast(String),
    Ask { target: String, message: String },
    ListAgents,
}
```

### Phase 2: Cross-Agent Communication

**Goal:** Agents can query each other, user can `@mention` across panes.

#### 4.5 Mention Parser

```rust
/// Parse @mentions from user input.
/// Returns (target_agent_name, pull_back, cleaned_message).
fn parse_mention(input: &str) -> Option<(String, bool, String)> {
    let trimmed = input.trim();
    if !trimmed.starts_with('@') {
        return None;
    }
    // @a2! message  -> pull back
    // @a2 message   -> send only
    // @all message  -> broadcast
    let rest = &trimmed[1..];
    let (name, pull_back, msg_start) = if let Some(space_pos) = rest.find(' ') {
        let name_part = &rest[..space_pos];
        if name_part.ends_with('!') {
            (&name_part[..name_part.len()-1], true, space_pos + 1)
        } else {
            (name_part, false, space_pos + 1)
        }
    } else {
        return None; // @agent with no message
    };

    let message = rest[msg_start..].trim().to_string();
    Some((name.to_string(), pull_back, message))
}
```

#### 4.6 TUI-Mediated Delegation Flow

When a1 emits `FromAgent::PeerQuery { target_agent: "a2", question, request_id }`:

```rust
async fn handle_peer_query(
    app: &mut MultiApp,
    source_id: AgentId,
    target_name: &str,
    question: &str,
    request_id: &str,
) -> Result<(), String> {
    let target_id = app.find_agent_by_name(target_name)
        .ok_or_else(|| format!("No agent named '{target_name}'"))?;

    // Prevent self-query
    if target_id == source_id {
        return Err("Agent cannot query itself".into());
    }

    // Build delegated task (strips ask_peer from the target's toolset)
    let msg = ToAgent::DelegatedTask {
        from_agent: app.panes[source_id as usize].name.clone(),
        request_id: request_id.to_string(),
        task: question.to_string(),
        context: String::new(), // could include summary of source's recent messages
    };

    // Send to target
    app.handles[target_id as usize]
        .to_agent
        .send(msg)
        .await
        .map_err(|e| format!("Failed to send to {target_name}: {e}"))?;

    // Mark source as waiting for delegation result
    app.panes[source_id as usize]
        .set_status(format!("Waiting for {target_name}..."));

    // The result will come back as FromAgent::DelegationResult from target,
    // which the event loop routes back to source as ToAgent::CrossAgentContext.
    Ok(())
}
```

#### 4.7 Python-Side Changes

The agent needs a new tool when running in multi-agent mode. In `run_agent.py`:

```python
# Only available when --subprocess-mode --multi-agent
MULTI_AGENT_TOOLS = {
    "ask_peer": {
        "description": "Ask another running agent a question. The other agent "
                       "has its own conversation context and tools. Use this "
                       "when you need a second opinion or want to delegate "
                       "a sub-task.",
        "parameters": {
            "target": {"type": "string", "description": "Name of the agent to ask"},
            "question": {"type": "string", "description": "The question or task"},
        },
    },
    "list_peers": {
        "description": "List all other running agents and their current status.",
        "parameters": {},
    },
}
```

When `ask_peer` is called, the agent emits a `PeerQuery` JSON line to stdout and blocks (waits for a `CrossAgentContext` response on stdin). This is similar to how `ClarifyRequest`/`ClarifyResponse` already works — the agent emits a question, blocks, and the TUI sends back the answer.

### Phase 3: Shared Memory

**Goal:** Agents share a persistent memory space — observations, decisions, and learned patterns survive across agents and sessions.

#### 4.8 Memory Architecture

Inspired by Claude Code's auto-memory (writes to `~/.claude/projects/<project>/memory/`), hermes agents get a shared memory directory:

```
~/.hermes-lite/memory/
├── SHARED.md           # Always loaded into every agent's system prompt
├── patterns.md         # Coding patterns, conventions discovered
├── decisions.md        # Architectural decisions made
├── debugging.md        # Solutions to recurring problems
└── <topic>.md          # Any topic file agents create
```

**Key rules:**
- `SHARED.md` is injected into every agent's system prompt (truncated at 200 lines)
- Topic files are read on demand via a `memory_read` tool
- Any agent can write/update any memory file
- Writes are immediately visible to all agents (filesystem-level sharing)
- Memory persists across sessions — it's just files on disk

#### 4.9 Memory Tools

```python
MEMORY_TOOLS = {
    "memory_write": {
        "description": "Write or update a shared memory file. All agents can read it. "
                       "Use for patterns, decisions, and insights worth preserving.",
        "parameters": {
            "file": {"type": "string", "description": "Filename (e.g. 'patterns.md')"},
            "content": {"type": "string", "description": "Full file content (overwrites)"},
        },
    },
    "memory_read": {
        "description": "Read a shared memory file by name.",
        "parameters": {
            "file": {"type": "string", "description": "Filename to read"},
        },
    },
    "memory_append": {
        "description": "Append a line or section to a shared memory file.",
        "parameters": {
            "file": {"type": "string", "description": "Filename"},
            "content": {"type": "string", "description": "Content to append"},
        },
    },
    "memory_list": {
        "description": "List all shared memory files.",
        "parameters": {},
    },
}
```

#### 4.10 Memory Protocol Events

New `FromAgent` variant so the TUI can display memory operations:

```rust
FromAgent::MemoryOp {
    op: String,         // "read", "write", "append"
    file: String,       // "patterns.md"
    preview: String,    // first 80 chars of content
}
```

The TUI renders memory operations like tool calls but with a distinct icon:

```
  ┊ 📝 memory_write  patterns.md — "Always use snake_case for…"  (0.0s)
  ┊ 📖 memory_read   debugging.md                                (0.0s)
```

#### 4.11 Memory in Multi-Agent Context

When a1 writes to `patterns.md`, a2 can immediately read it. No protocol needed — both subprocesses read/write the same files. The TUI shows a notification in the other pane:

```
  [a1 updated shared memory: patterns.md]
```

The TUI detects this by watching `FromAgent::MemoryOp` events from any agent and cross-posting a system note to other panes.

**Conflict handling:** If two agents write the same file simultaneously, last-write-wins. This is acceptable for memory files (they're advisory, not code). For safety, `memory_append` is preferred over `memory_write` for additive updates.

### Phase 4: Skills System

**Goal:** Named, reusable prompt+tool bundles that agents can invoke. Skills are visible in the TUI with clear start/end display. Skills are classified as **solo** or **multi-agent** — this distinction drives routing, display, and which agents can run them.

#### 4.12 Skill Classification

```yaml
scope: solo | multi    # THE key field
```

| Scope | Runs on | Can `@mention`? | Can `ask_peer`? | Example |
|-------|---------|-----------------|-----------------|---------|
| `solo` | One agent | No | No | `/commit`, `/test`, `/review-pr` |
| `multi` | Orchestrates N agents | Yes | Yes | `/parallel-refactor`, `/swarm-debug`, `/code-review-pair` |

**Solo skills** are self-contained — one agent, one task, no cross-talk. They're the common case and should be fast and predictable. The TUI renders them inside a single pane.

**Multi-agent skills** are orchestrators. They spawn or coordinate multiple agents, route messages between them, and aggregate results. The TUI renders them across panes with a shared progress header.

#### 4.13 Skill Definition Format

Skills are YAML files in `~/.hermes-lite/skills/` or bundled in the project:

```yaml
# ── Solo Skill ────────────────────────────────────
# ~/.hermes-lite/skills/commit.yaml
name: commit
scope: solo
description: "Stage and commit changes with a well-crafted message"
display_name: "Git Commit"
icon: "🔀"
prompt: |
  Analyze the current git diff and staged changes.
  Write a concise commit message following conventional commits.
  Stage relevant files (not .env or credentials).
  Create the commit.
tools_required: [terminal, read_file]
tools_forbidden: [ask_peer]   # enforced: solo skills can't cross-talk
steps:                         # optional named steps for progress display
  - "Analyzing diff"
  - "Writing commit message"
  - "Staging files"
  - "Creating commit"
```

```yaml
# ── Multi-Agent Skill ─────────────────────────────
# ~/.hermes-lite/skills/code-review-pair.yaml
name: code-review-pair
scope: multi
description: "One agent writes code, the other reviews — iterate until both agree"
display_name: "Paired Code Review"
icon: "👥"
agents:
  writer:
    role: "You are the code author. Write clean, tested code."
    tools_required: [terminal, read_file, edit_file]
  reviewer:
    role: "You are the code reviewer. Find bugs, suggest improvements."
    tools_required: [read_file]
    tools_forbidden: [edit_file]  # reviewer reads only
prompt: |
  The writer implements the requested change.
  The reviewer examines the diff and provides feedback.
  They iterate until the reviewer approves.
  Max 3 rounds.
orchestration:
  rounds: 3
  flow: writer → reviewer → writer  # turn-based
  stop_when: "reviewer approves"
```

```yaml
# ── Multi-Agent Skill (parallel) ──────────────────
# ~/.hermes-lite/skills/swarm-debug.yaml
name: swarm-debug
scope: multi
description: "N agents each investigate a different hypothesis in parallel"
display_name: "Swarm Debug"
icon: "🐝"
agents_count: auto              # TUI decides based on hypothesis count
per_agent_role: "Investigate one specific hypothesis about the bug."
prompt: |
  Given the bug report, generate N hypotheses.
  Spawn one agent per hypothesis.
  Each agent investigates independently.
  Collect results and synthesize.
orchestration:
  mode: parallel                # all agents run simultaneously
  synthesize: true              # one agent summarizes all results at the end
```

#### 4.14 Skill Registry & Resolution

```python
class SkillRegistry:
    def __init__(self, skill_dirs: list[Path]):
        self.solo: dict[str, SkillDef] = {}
        self.multi: dict[str, SkillDef] = {}

    def load(self):
        for d in self.skill_dirs:
            for f in d.glob("*.yaml"):
                skill = SkillDef.from_yaml(f)
                if skill.scope == "solo":
                    self.solo[skill.name] = skill
                else:
                    self.multi[skill.name] = skill

    def resolve(self, name: str) -> SkillDef | None:
        return self.solo.get(name) or self.multi.get(name)

    def list_solo(self) -> list[SkillDef]: ...
    def list_multi(self) -> list[SkillDef]: ...
```

The TUI's `/skills` command shows both categories:

```
  Solo Skills
    /commit       🔀  Stage and commit changes
    /test         🧪  Run test suite, analyze failures
    /review-pr    📝  Fetch PR, review changes
    /deploy       🚀  Run deployment pipeline

  Multi-Agent Skills
    /code-review-pair  👥  Writer + reviewer iterate
    /swarm-debug       🐝  Parallel hypothesis investigation
    /parallel-refactor 🔧  Split refactor across agents
```

#### 4.15 Execution Protocol

The protocol events carry the scope so the TUI knows how to render:

```rust
FromAgent::SkillStart {
    skill_name: String,     // "commit"
    display_name: String,   // "Git Commit"
    scope: String,          // "solo" or "multi"
    args: String,           // raw args string
},

FromAgent::SkillProgress {
    skill_name: String,
    step: String,           // "analyzing diff"
    step_number: u32,
    total_steps: u32,       // 0 if unknown
    agent: String,          // "a1" — which agent is reporting (for multi)
},

FromAgent::SkillComplete {
    skill_name: String,
    success: bool,
    summary: String,
    duration_ms: u32,
},
```

#### 4.16 TUI Display — Solo Skills

Solo skills render inside a single pane with a bordered box:

```
  ╭─ 🔀 Git Commit ────────────────────────────────────╮
  │  ① Analyzing diff...                          done  │
  │  ② Writing commit message...                  done  │
  │  ③ Staging files...                           done  │
  │  ┊ ✓ terminal      git add src/main.rs        0.1s  │
  │  ┊ ✓ terminal      git commit -m "fix: ..."   0.3s  │
  │                                                      │
  │  ✓ Committed: fix auth token refresh (3 files)      │
  ╰──────────────────────────────────────── 1.2s total ─╯
```

#### 4.17 TUI Display — Multi-Agent Skills

Multi-agent skills get a **shared header bar** across panes and per-pane progress:

```
┌─────────────────────── 👥 Paired Code Review ─── round 2/3 ──────────────────┐
├─── a1 (writer) ────────────────────────┬─── a2 (reviewer) ───────────────────┤
│                                         │                                     │
│  Implementing the auth token refresh.   │  Reviewing changes...               │
│  ┊ ✓ edit_file    src/auth.rs     0.2s  │                                     │
│  ┊ ✓ edit_file    src/config.rs   0.1s  │  Issues found:                      │
│  ┊ ⠿ terminal     cargo test            │  - Missing error handling in L.42   │
│                                         │  - Token expiry not checked         │
│                                         │                                     │
│  ② Writing code...                done  │  ① Reviewing diff...           done  │
├─────────────────────────────────────────┼─────────────────────────────────────┤
│ ⠹ Iteration 2                          │  Ready (waiting for writer)          │
└─────────────────────────────────────────┴─────────────────────────────────────┘
```

Key differences from solo:
- Shared skill header spans all panes
- Each pane shows its agent's role label
- Progress steps are per-agent (`agent` field in `SkillProgress`)
- The orchestrator controls turn order (writer → reviewer → writer)

#### 4.18 Enforcement Rules

The TUI enforces scope boundaries:

| Rule | Solo | Multi |
|------|------|-------|
| `ask_peer` tool available | ✗ stripped | ✓ available |
| `@mention` in prompts | ✗ ignored | ✓ routed |
| Can spawn new panes | ✗ | ✓ (via orchestration) |
| Shared memory read | ✓ | ✓ |
| Shared memory write | ✓ | ✓ |
| Cross-agent context injection | ✗ | ✓ |
| Runs in focused pane only | ✓ | ✗ (spans panes) |

Enforcement is at the TUI level: when a solo skill emits `PeerQuery` or `DelegateTask`, the TUI rejects it with an error: `"Solo skill '{name}' cannot use cross-agent features. Use a multi-agent skill instead."`

#### 4.19 Skill Invocation Flow

**Solo skill:**
```
User types: /commit
  → TUI resolves "commit" in SkillRegistry → scope: solo
  → TUI sends ToAgent::UserInput with skill prompt injected
  → Agent emits SkillStart { scope: "solo" }
  → Agent runs, emits SkillProgress steps
  → Agent emits SkillComplete
  → TUI renders bordered box in current pane
```

**Multi-agent skill:**
```
User types: /code-review-pair
  → TUI resolves "code-review-pair" → scope: multi
  → TUI auto-splits if needed (ensures 2 panes)
  → TUI sends ToAgent::UserInput to a1 (writer role injected)
  → a1 runs, emits SkillProgress
  → On a1 completion, TUI sends a1's output to a2 (reviewer)
  → a2 reviews, emits SkillProgress
  → TUI checks stop condition ("reviewer approves")
  → If not done, routes feedback back to a1 → next round
  → On completion, TUI emits SkillComplete to both panes
```

The TUI is the orchestrator for multi-agent skills — agents don't know about the skill's round structure. They just receive messages and respond. The TUI implements the `orchestration` block from the YAML.

#### 4.20 Skills + Memory Integration

Both scope levels read/write shared memory:

| Skill | Memory Usage |
|-------|-------------|
| `/commit` (solo) | Reads `patterns.md` for commit conventions |
| `/test` (solo) | Appends to `debugging.md` on solved failures |
| `/review-pr` (solo) | Writes to `decisions.md` on architectural choices |
| `/code-review-pair` (multi) | Writer reads `patterns.md`; reviewer writes `review-notes.md`; both agents see updates in real time |
| `/swarm-debug` (multi) | Each agent appends findings to `debug-hypotheses.md`; synthesizer reads all at the end |

This creates a feedback loop: agents learn from each other through shared memory, and skills apply that knowledge consistently.

### Phase 5: Polish

- Tab bar rendering with unread indicators
- Pane resize (drag borders or `/resize 60:40`)
- Agent-specific model selection (one pane can use sonnet, another opus)
- Session persistence per agent (each gets its own session ID in RustSessionDB)
- `/share <agent>` — copy selected text from current conversation into another agent's context

---

## 5. Technical Challenges

### 5.1 Concurrent Subprocess Management

Each agent subprocess has three async tasks (stdout reader, stderr reader, stdin writer). With N agents, that's 3N + 1 (event loop) tokio tasks. This is fine for tokio — it's designed for thousands of tasks. But:

- **Channel backpressure:** If one agent produces output faster than the TUI renders, its `from_agent` channel (capacity 256) could fill up. The reader task will then block on `send()`, which stalls that agent's stdout pipe, which stalls the agent's Python process. This is actually fine — it's natural backpressure. But if the TUI event loop is slow (e.g., expensive render), all agents stall. **Mitigation:** Keep the render path fast. Don't do string allocation in the render loop. Pre-compute line wrapping.

- **Process lifecycle:** Agents can die at any time. The TUI must handle `Disconnected` on each agent's channel independently without affecting others. The current code already handles this for a single agent; it just needs to be per-pane.

### 5.2 Shared File System

This is the most dangerous practical problem. Two agents editing the same file simultaneously will corrupt it. There's no file locking in the agent's tool implementations.

**Approaches (in order of pragmatism):**

1. **Working directory isolation (recommended first step):** Each agent gets a different `--working-dir`. Agent-0 works in `./`, a2 works in `./feature-branch/`. This eliminates conflicts entirely for separate tasks.

2. **File lock advisory:** The TUI tracks which files each agent has open (from `ToolCallStart` with `tool_name: "edit_file"` or `"write_file"`). If a2 tries to edit a file a1 is currently editing, the TUI injects a warning: "a1 is currently editing this file. Proceed?" This is advisory, not enforced.

3. **Git branch isolation:** Each agent works on a separate git branch. The TUI creates worktrees: `git worktree add /tmp/hermes-a2 -b a2-branch`. Agents' working directories point to different worktrees. This is the cleanest solution for code tasks but requires git.

4. **Serialized file access (heavy):** A file access mutex managed by the TUI. Agent requests file operations, TUI queues them. This is complex and slow — not recommended.

**Recommendation:** Start with option 1 (separate working dirs). Add option 3 (git worktree isolation) as a `/split --worktree` flag. Option 2 is nice-to-have for detecting accidental conflicts.

### 5.3 Context Window Management

Each agent has its own context window. Cross-agent queries inject text into the target's context, consuming tokens. Concerns:

- **Context bloat from delegation:** If a1 delegates a large task to a2, a2's response might be huge. Injecting the full response back into a1's context wastes tokens. **Mitigation:** The TUI truncates delegation responses to a configurable max (e.g., 2000 tokens) and appends "[truncated — full response in a2's pane]".

- **Context compression coordination:** If a1 compresses its context while a delegation to a2 is in flight, the delegation result may reference content that a1 no longer has. This is mostly fine — the delegation result is self-contained. But `CrossAgentContext` should include enough context to be useful standalone.

- **Token accounting:** The `/usage` command should show per-agent and total token usage. The global status bar shows the focused agent's usage; `/usage all` shows a summary table.

### 5.4 Race Conditions

- **User sends message while delegation in flight:** If a1 is waiting for a2's delegation result and the user submits a new message to a1, the new message should queue (current behavior with `agent_running` flag). The delegation result arrives, is injected, then the queued message is sent. No special handling needed — the existing `agent_running` guard already serializes input.

- **Both agents emit PeerQuery simultaneously:** Agent-0 asks a2, a2 asks a1, at the same time. With the "no nested delegation" rule (Phase 2, rule 4), the second query is rejected because the target is already handling a delegation. Return an error: "a1 is currently handling a delegated task."

- **Agent dies during delegation:** The TUI detects `Disconnected` on the dead agent's channel, finds any pending delegation requests targeting that agent, and returns an error to the requesting agent: "a2 terminated during delegation."

### 5.5 Terminal Size Constraints

With two vertical panes, each gets half the terminal width. On an 80-column terminal, that's 40 columns per pane — tight but workable. Tool call lines and long code will wrap aggressively.

**Mitigations:**
- Minimum pane width of 40 columns. If the terminal is too narrow, auto-switch to tab mode with a warning.
- `/zoom` command temporarily makes the focused pane full-width (like tmux's zoom).
- Horizontal split mode (`/hsplit`) is better for wide terminals where vertical space is the constraint.

### 5.6 Input Focus and Keyboard Routing

Only one pane accepts keyboard input at a time. But the user might want to watch both panes scroll. The current `poll(50ms)` tick handles this — both panes' agent messages are drained every tick regardless of focus.

The tricky part: `Ctrl+Left` / `Ctrl+Right` for pane switching must not conflict with cursor movement in the textarea. `tui-textarea` consumes `Ctrl+Left` for word-jump. **Solution:** Use `Alt+Left` / `Alt+Right` instead (or `Ctrl+]` / `Ctrl+[` which are rarely used). Alternatively, use a prefix key like tmux: `Ctrl+A` then arrow key. But prefix keys add latency and learning curve.

**Recommended keybindings (revised):**

| Key | Action |
|-----|--------|
| `Alt+1` .. `Alt+9` | Focus pane N |
| `Alt+Left` / `Alt+Right` | Focus prev/next pane |
| `Alt+N` | New agent (split) |
| `Alt+W` | Close focused pane |
| `Alt+Z` | Zoom focused pane (toggle) |
| `Alt+B` | Broadcast mode toggle |

These avoid all conflicts with textarea editing, terminal control, and the existing Ctrl+C/D bindings.

---

## 6. Migration Path

The implementation should be backward-compatible. When running with a single agent (no `/split`), the UI and behavior are identical to today. The multi-agent code paths only activate when a second agent is spawned.

**Step-by-step:**

1. **Refactor `App` into `AgentPane` + `MultiApp`** — Extract per-agent state from `App` into `AgentPane`. `MultiApp` holds a `Vec<AgentPane>` with initially one element. All existing functionality works unchanged.

2. **Add split rendering** — Implement `render_split()` that divides the terminal. When `panes.len() == 1`, it renders full-width (identical to current). When `panes.len() > 1`, it splits.

3. **Add `/split` command** — Spawns a new `AgentProcess`, creates a new `AgentPane`, adds to `MultiApp`. Focus stays on original pane.

4. **Add pane switching** — `Alt+Left/Right` changes `focused`. Only focused pane gets keyboard input.

5. **Add `@mention` routing** — Parse user input for `@agent` prefix, route to target pane.

6. **Add protocol extensions** — New `ToAgent`/`FromAgent` variants for delegation.

7. **Add Python-side `ask_peer` tool** — New tool in subprocess mode.

8. **Add tab mode** — Alternative layout with tab bar.

Steps 1-4 are the MVP. Steps 5-8 build on it incrementally.

**Feature priority:**

| Phase | Feature | Effort | Impact |
|-------|---------|--------|--------|
| 1 | Multi-pane + split rendering | Medium | High — foundational |
| 2 | Cross-agent `@a1`/`@a2` routing | Medium | High — core UX |
| 3 | Shared memory (`~/.hermes-lite/memory/`) | Low | High — knowledge persistence |
| 4 | Skills display (`SkillStart`/`Progress`/`Complete`) | Medium | High — visual clarity |
| 5 | Polish (tabs, resize, zoom) | Low | Medium — nice-to-have |

---

## 7. Open Questions

- **Auto-naming:** Should agents get descriptive names based on their first task? E.g., the user says "refactor the auth module" and `a1` auto-renames to "auth-refactor"? The Python agent could emit a `FromAgent::SuggestName { name: String }` after the first interaction. Short names (`a1`, `a2`) remain as permanent aliases regardless.

- **Session persistence:** Should multi-agent sessions be persisted as a group? If the user exits and restarts, should they get back the same pane layout with the same conversations? This would require extending `RustSessionDB` with a "session group" concept.

- **Max agents:** What's the practical upper limit? With terminal constraints and subprocess overhead, 4 agents is probably the sweet spot. The TUI should warn when spawning a 5th agent.

- **Agent specialization:** Should the TUI support spawning agents with different system prompts or toolsets? E.g., `/split --role reviewer` spawns an agent with a code review system prompt. This is powerful but adds complexity to the spawn path.
