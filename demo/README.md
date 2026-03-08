# hermes-lite Feature Demo

This demo showcases all the major features of hermes-lite in a hands-on, interactive way.

## What You'll See

### 🛠️ Core Tools (8 total)
- **terminal** - Execute shell commands with dangerous-command approval
- **process** - Background process management (spawn, monitor, kill)
- **read_file** - Read files with line numbers and fuzzy filename suggestions
- **write_file** - Create/overwrite files with write protection
- **patch** - Smart find-replace with 8 fuzzy matching strategies
- **search_files** - Ripgrep-backed content search and file finding
- **todo** - Task planning with state tracking
- **clarify** - Interactive questions with multiple choice or open-ended responses

### 🎯 Key Features
- **Streaming responses** - Real-time token output
- **Parallel tool execution** - Non-inline tools run concurrently
- **Context compression** - Auto-triggered at 85% of context window
- **Dangerous command approval** - 30 regex patterns for safety
- **Write protection** - Blocks writes to sensitive paths
- **Fuzzy file matching** - Typo-tolerant filename suggestions
- **Multi-agent mode** - Multiple agent panes with @mentions and routing

### 🚀 Three Ways to Run

#### 1. CLI Mode (Interactive REPL)
```bash
# Start fresh session
hermes-lite

# Or resume last session
hermes-lite --continue
```

#### 2. Single-Shot Mode
```bash
# Quick one-off task
hermes-lite chat -q "analyze the demo files and summarize what they do"
```

#### 3. Rust TUI Mode (Multi-Agent)
```bash
# Native terminal UI with multi-pane support
./target/release/hermes-tui
```

---

## Demo Scenarios

### Scenario 1: Basic Tool Showcase
**Goal:** Exercise all 8 core tools in one workflow

**What to try:**
```
Please help me with this workflow:

1. Read the demo/sample_project/main.py file
2. Search for all TODO comments in the demo folder
3. Create a todo list to track the work needed
4. Write a new test file at demo/sample_project/test_main.py
5. Use patch to fix a bug in main.py (change "Hello" to "Greetings")
6. Run the Python file using terminal
7. Start a background HTTP server using process
8. Ask me a clarify question about what port to use
```

**Features demonstrated:**
- ✅ read_file with line numbers
- ✅ search_files for content
- ✅ todo task planning
- ✅ write_file with path creation
- ✅ patch with fuzzy matching
- ✅ terminal execution
- ✅ process background management
- ✅ clarify interactive questions

---

### Scenario 2: Dangerous Command Approval
**Goal:** Show safety features in action

**What to try:**
```
Please run these commands:
1. rm -rf /tmp/hermes-demo-test
2. chmod 777 demo/sample_project/main.py
3. ls -la demo/
```

**Features demonstrated:**
- ⚠️ Approval prompt for `rm -rf`
- ⚠️ Approval prompt for `chmod 777`
- ✅ Safe commands execute normally
- 📋 Approval persistence per session

---

### Scenario 3: Write Protection
**Goal:** Test file write safety

**What to try:**
```
Try to:
1. Write a file to ~/.ssh/id_rsa
2. Write a file to /etc/passwd
3. Write a file to ~/.bashrc
4. Write a file to demo/safe_output.txt (this should work)
```

**Features demonstrated:**
- 🛡️ Blocks writes to `~/.ssh/`, `~/.aws/`, `~/.gnupg/`
- 🛡️ Blocks writes to `/etc/passwd`, `/etc/sudoers`
- 🛡️ Blocks writes to shell rc files
- ✅ Allows writes to safe locations

---

### Scenario 4: Fuzzy Patch Matching
**Goal:** Show intelligent code editing

**What to try:**
```
Use patch to make these changes to demo/sample_project/calculator.py:

1. Change the add function to include logging
2. Fix the whitespace in the subtract function
3. Add a new multiply function
```

**Features demonstrated:**
- 🎯 8 fuzzy matching strategies (exact → whitespace-normalized → indentation-flexible)
- 🔧 Handles minor whitespace differences
- 🧩 Works even with imperfect old_string matches

---

### Scenario 5: Background Process Management
**Goal:** Demonstrate process tool

**What to try:**
```
1. Start a Python HTTP server in the background serving demo/sample_project
2. Poll the process to check if it's running
3. Send a request to the server using curl
4. Kill the background process
```

**Features demonstrated:**
- 🔄 Spawn background processes with PTY support
- 📊 Poll for status and output (200KB rolling buffer)
- 📝 Read full logs with pagination
- 🛑 Kill processes
- ✨ Crash recovery via JSON checkpoint

---

### Scenario 6: Context Compression
**Goal:** Trigger auto-compression

**What to try:**
```
Read all files in the demo folder, then ask me to analyze them all together and create a comprehensive report. Keep asking for more details about each file until we hit the context window limit.
```

**Features demonstrated:**
- 📦 Auto-triggers at 85% of context window
- 🧠 Preserves head + tail of conversation
- 📝 Summarizes middle section
- 🎯 Compression-aware todo tool (survives compression)

---

### Scenario 7: Multi-Agent Mode (TUI Only)
**Goal:** Show agent orchestration

**What to run in TUI:**
```
# Start the TUI
./target/release/hermes-tui

# Commands to try:
/split                          # Create a second agent pane
/name coder                     # Name first agent "coder"
/focus 2                        # Switch to second pane
/name reviewer                  # Name it "reviewer"

# Now try @mentions:
@coder write a Python function to calculate fibonacci
@reviewer! analyze the code that coder just wrote

# Or broadcast:
/broadcast what files are in the demo folder?

# Navigation:
Ctrl+Left/Right                 # Switch between panes
Alt+1                          # Jump to pane 1
Alt+2                          # Jump to pane 2
```

**Features demonstrated:**
- 🪟 Split and tab layouts
- 🏷️ Named agents
- 📨 @mentions for routing
- 📡 /broadcast for all agents
- 🎯 @agent! to pull responses back
- ⌨️ Keyboard navigation

---

### Scenario 8: File Search Power
**Goal:** Show ripgrep-backed search

**What to try:**
```
1. Search for all Python function definitions in demo/
2. Find all files with "TODO" in them
3. Count how many times "import" appears in each file
4. Find all .py files modified in the last day
```

**Features demonstrated:**
- 🔍 Regex content search
- 📁 Glob file finding
- 📊 Output modes: content, files_only, count
- ⚡ Fast ripgrep backend

---

### Scenario 9: Todo Task Planning
**Goal:** Demonstrate task management

**What to try:**
```
Help me refactor the demo project. First, create a todo list with these tasks:
1. Add type hints to all functions
2. Write unit tests
3. Add docstrings
4. Create a requirements.txt

Then work through them one by one, updating status as you go.
```

**Features demonstrated:**
- 📋 Task creation with IDs
- 🔄 Status tracking (pending → in_progress → completed)
- 📦 Survives context compression
- 🎯 Only one task in_progress at a time

---

### Scenario 10: Clarify Questions
**Goal:** Interactive decision-making

**What to try:**
```
I want to create a web service. Ask me clarifying questions about:
- What framework to use (Flask, FastAPI, Django)
- What database to use
- What deployment target
Then implement based on my answers.
```

**Features demonstrated:**
- ❓ Multiple choice questions
- 📝 Open-ended questions
- 🎨 TUI renders as modal dialog
- ⏱️ Optional timeouts

---

## Quick Test Commands

### Test All Tools in One Go
```bash
hermes-lite chat -q "
Run this complete workflow:
1. Read demo/sample_project/main.py
2. Search for 'def' in demo/
3. Create a todo with 3 tasks
4. Write a new file demo/output.txt
5. Patch main.py to add a comment
6. Run 'ls -la demo/'
7. Tell me what you accomplished
"
```

### Test Dangerous Commands
```bash
hermes-lite chat -q "Run: rm -rf /tmp/test-hermes && echo 'done'"
# You'll see approval prompt for rm -rf
```

### Test Write Protection
```bash
hermes-lite chat -q "Write 'test' to ~/.ssh/test_file"
# Should be blocked by write protection
```

### Test Fuzzy Matching
```bash
hermes-lite chat -q "Use patch to change any function in demo/sample_project/calculator.py"
# Watch it handle whitespace differences gracefully
```

---

## Advanced: Terminal Backends

### Run in Docker
```bash
TERMINAL_ENV=docker TERMINAL_DOCKER_IMAGE=ubuntu:24.04 hermes-lite chat -q "run uname -a"
```

### Run via SSH
```bash
TERMINAL_ENV=ssh \
TERMINAL_SSH_HOST=example.com \
TERMINAL_SSH_USER=youruser \
hermes-lite chat -q "run hostname"
```

---

## Expected Output Examples

### Read File with Line Numbers
```
     1|#!/usr/bin/env python3
     2|"""Demo application"""
     3|
     4|def greet(name):
     5|    return f"Hello, {name}!"
```

### Search Results
```
demo/sample_project/main.py
5:def greet(name):
9:def main():

demo/sample_project/calculator.py
1:def add(a, b):
5:def subtract(a, b):
```

### Todo List
```
[ ] 1. add-type-hints: Add type hints to all functions (pending)
[→] 2. write-tests: Write unit tests (in_progress)
[✓] 3. add-docs: Add docstrings (completed)
```

### Dangerous Command Approval
```
⚠️  DANGEROUS COMMAND DETECTED
Command: rm -rf /tmp/hermes-demo-test
Pattern: rm.*-rf
Risk: Recursive deletion

Allow this command? [y/N/always]
```

### Write Protection Block
```
❌ Write denied: ~/.ssh/id_rsa
Reason: Path matches protected pattern: ~/.ssh/
Protected directories: ~/.ssh/, ~/.aws/, ~/.gnupg/, ~/.kube/
```

---

## Troubleshooting

### "Command not found: hermes-lite"
```bash
# Make sure you've installed:
pip install -e .
```

### "TUI not found"
```bash
# Build the Rust TUI:
cargo build --release -p hermes_tui
```

### "No API key"
```bash
# Export your API key:
export ANTHROPIC_API_KEY=sk-ant-...
```

### "Rust extensions not loaded"
```bash
# Build Rust extensions:
pip install maturin
maturin develop --release -m hermes_rs/Cargo.toml
```

---

## What Makes This Demo Special

1. **Real Features** - Everything shown here is implemented and tested (1062 unit tests + 26 integration tests)
2. **Safety First** - Dangerous command approval and write protection prevent accidents
3. **Smart Tools** - Fuzzy matching, parallel execution, context compression work transparently
4. **Multi-Agent** - Rust TUI supports true multi-agent orchestration with @mentions
5. **Production Ready** - Same subprocess protocol used by tests and TUI

---

## Next Steps

After running the demos:

1. **Check the architecture** - See `docs/ARCHITECTURE.md`
2. **Run tests** - `python3 -m pytest tests/ -q`
3. **Try prodpush** - `python3 -m pytest tests/prodpush/ -v -m prodpush`
4. **Build your own** - Fork and extend with new tools or integrations

---

## File Structure

```
demo/
├── README.md                    # This file
├── sample_project/              # Demo Python project
│   ├── main.py                 # Simple app with TODO comments
│   ├── calculator.py           # Functions for patch demo
│   └── utils.py                # Utility functions
├── sample_data/                 # Sample files for search
│   ├── data.json               # JSON data
│   ├── config.yaml             # YAML config
│   └── notes.txt               # Text notes
└── scripts/                     # Demo automation scripts
    ├── run_all_demos.sh        # Run all scenarios
    └── test_features.py        # Python test harness
```

---

**Ready to see hermes-lite in action?** Pick a scenario and start exploring! 🚀
