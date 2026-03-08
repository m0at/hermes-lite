# Multi-Agent TUI Demo Guide

This guide focuses specifically on the Rust TUI and its multi-agent capabilities.

## Starting the TUI

```bash
# From the repo root:
./target/release/hermes-tui
```

You should see a terminal UI with:
- Input box at the bottom
- Message history area
- Status bar showing model, tokens, session ID

## Single Agent Basics

Before diving into multi-agent features, get comfortable with the basics:

### Your First Message

```
Hello! Can you read demo/sample_project/main.py?
```

**Watch for:**
- 🟢 Real-time token streaming
- 📝 Tool execution with timing
- ✅ Successful completion indicator

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Ctrl+C` | Interrupt current operation |
| `Ctrl+D` | Exit TUI |
| `Up/Down` | Scroll history |
| `Ctrl+Left/Right` | Navigate panes (multi-agent) |
| `Alt+1-9` | Jump to specific pane |

### Slash Commands

```
/help          # Show all commands
/tools         # List available tools
/model         # Change model
/clear         # Clear screen
/split         # Create new agent pane
/agents        # List all agents
```

## Multi-Agent Demo Scenarios

### Scenario 1: Code Review Workflow

**Setup:**
```
/split
/name coder
Alt+2
/name reviewer
```

**Workflow:**
```
# In pane 1 (coder):
Write a Python function to calculate prime numbers up to n

# In pane 2 (reviewer):
@coder! show me the code you just wrote

# Then review it:
Analyze this code for efficiency and suggest improvements
```

**What's happening:**
- `@coder!` routes the request to the coder agent
- The `!` suffix pulls the response back to reviewer's pane
- Each agent maintains independent context

### Scenario 2: Parallel Research

**Setup:**
```
/split
/split
/tabs          # Switch to tab layout for easier reading
/name researcher1
Alt+2
/name researcher2
Alt+3
/name researcher3
```

**Workflow:**
```
/broadcast Search the demo folder and tell me what you find

# Or target specific agents:
Alt+1
@researcher1 focus on Python files
Alt+2
@researcher2 focus on configuration files
Alt+3
@researcher3 focus on documentation
```

**What's happening:**
- `/broadcast` sends the same message to all 3 agents
- They work independently in parallel
- Each maintains their own tool execution state

### Scenario 3: Task Delegation

**Setup:**
```
/split
/hsplit        # Horizontal split for different layout
/name coordinator
Alt+2
/name worker1
Alt+3
/name worker2
```

**Workflow:**
```
# In coordinator pane (Alt+1):
Create a todo list with these tasks:
1. Read all Python files in demo/sample_project
2. Create a test file
3. Run the tests

# Delegate to workers:
@worker1 handle task 1 - read all Python files
@worker2 handle task 2 - create test files

# Check on them:
/agents        # See status of all agents
```

**What's happening:**
- Coordinator creates the plan
- Work is distributed to specialized agents
- `/agents` shows each agent's current state

### Scenario 4: Interactive Decision Making

**Setup:**
```
/split
/name analyst
Alt+2
/name implementer
```

**Workflow:**
```
# In analyst pane:
Ask me what kind of application I want to build (use clarify tool)

# This will show an interactive dialog in the TUI
# After answering:

# In implementer pane:
@analyst! what did the user want to build?
# Then implement based on that
```

**What's happening:**
- Clarify tool renders as modal dialog overlay
- Response is captured and stored in analyst's context
- Can be shared with other agents via @mentions

### Scenario 5: Background Process Monitoring

**Setup:**
```
/split
/name monitor
Alt+2
/name executor
```

**Workflow:**
```
# In executor pane:
Start a Python HTTP server on port 8765 in the background

# In monitor pane:
Poll the background processes and tell me if the server is running

# Test it:
Run: curl http://localhost:8765

# Clean up:
@executor kill the HTTP server process
```

**What's happening:**
- Process tool manages background jobs
- Monitor can check status without disturbing executor
- Clean separation of concerns

## Advanced TUI Features

### Layout Management

```
/split         # Vertical split
/hsplit        # Horizontal split
/tabs          # Tab layout (one pane visible, tab bar at top)
/zoom          # Toggle between split and tab layouts
/close         # Close current pane
```

### Agent Navigation

```
Ctrl+Left      # Previous pane
Ctrl+Right     # Next pane
Alt+1          # Jump to pane 1
Alt+2          # Jump to pane 2
...
Alt+9          # Jump to pane 9
```

### Inter-Agent Communication

```
@agentname message              # Send to agent, no response
@agentname! message            # Send to agent, pull response back
@all message                    # Broadcast to all agents
/broadcast message              # Same as @all
/ask agentname message         # Explicit ask command
```

### Agent Management

```
/name newname                   # Rename current agent
/focus agentname               # Switch to named agent
/focus 2                       # Switch to pane 2
/agents                        # List all agents with stats
```

## Visual Indicators

### Status Bar

```
[Agent: a1] [Model: claude-sonnet-4] [Tokens: 1234/200000] [Session: abc123]
```

### Tool Execution

```
🔧 terminal (id: tool_xyz)
   Args: {"command": "ls -la"}
   ⏱️  Duration: 234ms
   ✅ Success
```

### Thinking Blocks

```
💭 [Thinking]
   Let me analyze this code...
   [streaming tokens appear here]
```

### Clarify Dialog

```
┌─────────────────────────────────────┐
│ What framework should I use?        │
│                                     │
│ 1. Flask                           │
│ 2. FastAPI                         │
│ 3. Django                          │
│ 4. Other (type your answer)        │
│                                     │
│ > _                                │
└─────────────────────────────────────┘
```

## Tips & Tricks

### 1. Name Your Agents Meaningfully

```
Good: /name code-reviewer
Good: /name file-analyzer
Good: /name test-runner

Bad: /name a1
Bad: /name agent2
```

### 2. Use Tab Layout for Complex Tasks

```
/tabs          # Switch to tab layout
# Now you can focus on one agent at a time
# Tab bar shows all agent names at top
```

### 3. @mention! for Context Sharing

```
# Agent 1 does research:
Read all the config files and summarize

# Agent 2 implements based on that:
@researcher! what did you find?
# Now agent 2 has the context
```

### 4. Broadcast for Parallel Work

```
/broadcast analyze demo/sample_project/ and report your findings

# Each agent works independently
# Compare results by switching between panes
```

### 5. Session Persistence

Each agent pane has its own session ID. They persist across TUI restarts:

```
# In one session:
/name important-work
[do some work]

# Close TUI, restart it later
# Sessions are preserved in ~/.hermes-lite/state.db
# Resume by creating same agent name
```

## Common Patterns

### Code Review Pattern

```
1. /split
2. /name coder | Alt+2 | /name reviewer
3. Coder writes code
4. Reviewer: @coder! show me the code
5. Reviewer analyzes and suggests improvements
6. Coder: @reviewer! what should I change?
7. Coder implements changes
```

### Research & Report Pattern

```
1. /split /split /tabs
2. Name agents: researcher1, researcher2, writer
3. /broadcast search demo/ for information
4. Alt+3 (writer)
5. @researcher1! what did you find?
6. @researcher2! what did you find?
7. Writer synthesizes into report
```

### Test-Driven Development Pattern

```
1. /split
2. /name test-writer | Alt+2 | /name implementer
3. Test-writer: Create test file for calculator
4. Implementer: @test-writer! what tests should I pass?
5. Implementer: Writes code to pass tests
6. Test-writer: Runs tests and reports results
```

## Performance Notes

- Each agent subprocess is independent (no shared memory)
- Agents can run tools in parallel
- TUI updates in real-time as tokens stream
- Background processes are tracked per-agent
- Maximum 64 processes total across all agents

## Troubleshooting

### "Agent not responding"

```
# Check if it's still processing:
Ctrl+C         # Interrupt current operation

# Or check process list:
/jobs          # Shows background tasks
```

### "Can't create more panes"

```
# Maximum is typically 9 panes (Alt+1-9)
# Close unused panes:
/close

# Or use tab layout for better organization:
/tabs
```

### "Messages going to wrong agent"

```
# Check current focus:
/agents

# Use explicit routing:
@specificagent your message here

# Or jump to the right pane:
Alt+1          # Then type message
```

### "Lost track of which agent is which"

```
/agents        # Shows all agents with names and stats

# Rename to be more descriptive:
/name better-name
```

## Next Steps

1. **Try the scenarios** - Work through each multi-agent scenario above
2. **Experiment with layouts** - Find what works for your workflow
3. **Build your own patterns** - Combine agents in new ways
4. **Check subprocess protocol** - See `docs/ARCHITECTURE.md` for technical details
5. **Run prodpush tests** - See how we test multi-agent features: `tests/prodpush/`

The TUI is where hermes-lite really shines - have fun orchestrating multiple AI agents! 🚀
