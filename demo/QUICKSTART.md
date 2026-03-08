# Quick Start Guide

Get up and running with the hermes-lite demo in under 5 minutes.

## Prerequisites

```bash
# 1. Install hermes-lite (if not already installed)
pip install -e .

# 2. Build Rust extensions (optional but recommended)
pip install maturin
maturin develop --release -m hermes_rs/Cargo.toml

# 3. Build Rust TUI (for multi-agent demos)
cargo build --release -p hermes_tui

# 4. Set your API key
export ANTHROPIC_API_KEY=sk-ant-...
```

## 30-Second Test

```bash
# Single command to test everything works:
hermes-lite chat -q "Read demo/sample_project/main.py and tell me what it does"
```

Expected: The agent reads the file and summarizes it.

## 5-Minute Tour

### 1. Basic File Operations (60 seconds)

```bash
hermes-lite chat -q "
1. Read demo/sample_project/calculator.py
2. Search for all TODO comments in demo/
3. Write a summary to demo/summary.txt
"
```

**What you'll see:**
- ✅ `read_file` with line numbers
- ✅ `search_files` with regex
- ✅ `write_file` with path creation

### 2. Terminal & Safety (60 seconds)

```bash
hermes-lite chat -q "
1. Run 'ls -la demo/sample_project'
2. Run 'python3 demo/sample_project/main.py 100 50'
"
```

**What you'll see:**
- ✅ Safe terminal commands execute normally
- ✅ Output displayed in real-time

### 3. Dangerous Command Test (60 seconds)

```bash
hermes-lite chat -q "
Create a temp directory /tmp/hermes-test then run: rm -rf /tmp/hermes-test
"
```

**What you'll see:**
- ⚠️ Approval prompt for `rm -rf`
- 📋 Option to allow once or always

### 4. Patch Tool (60 seconds)

```bash
hermes-lite chat -q "
Use patch to add a multiply function to demo/sample_project/calculator.py
"
```

**What you'll see:**
- 🔧 Smart find-replace with fuzzy matching
- ✅ Handles whitespace differences gracefully

### 5. Multi-Agent TUI (60 seconds)

```bash
./target/release/hermes-tui
```

Once in the TUI, type:
```
/split
@a2 read demo/sample_project/main.py and summarize it
```

**What you'll see:**
- 🪟 Two agent panes side by side
- 📨 Message routed to second agent
- ⚡ Real-time streaming in both panes

## Common Commands Reference

### CLI Mode

| Command | Description |
|---------|-------------|
| `hermes-lite` | Start interactive REPL |
| `hermes-lite -c` | Continue last session |
| `hermes-lite chat -q "..."` | Single-shot query |
| `/help` | Show all commands |
| `/tools` | List available tools |
| `/verbose` | Toggle tool display verbosity |
| `/quit` | Exit |

### TUI Mode

| Command | Description |
|---------|-------------|
| `/split` | Create vertical split |
| `/hsplit` | Create horizontal split |
| `/name <n>` | Rename current agent |
| `@agent message` | Route to agent |
| `@agent! message` | Route and pull back response |
| `/broadcast msg` | Send to all agents |
| `Ctrl+Left/Right` | Navigate panes |
| `Alt+1-9` | Jump to pane |

## Troubleshooting

### "Command not found"
```bash
# Make sure you're in the venv:
source .venv/bin/activate
pip install -e .
```

### "No API key"
```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Or add to ~/.hermes-lite/.env
```

### "TUI not found"
```bash
cargo build --release -p hermes_tui
# Then run: ./target/release/hermes-tui
```

### "Permission denied"
```bash
chmod +x demo/scripts/*.sh demo/sample_project/*.py
```

## Next Steps

1. **Run automated demos**: `./demo/scripts/run_all_demos.sh`
2. **Read full scenarios**: Open `demo/README.md`
3. **Try the test suite**: `python3 -m pytest tests/ -q`
4. **Explore architecture**: See `docs/ARCHITECTURE.md`

## One-Liners for Each Tool

```bash
# read_file
hermes-lite chat -q "Read demo/sample_project/main.py"

# write_file
hermes-lite chat -q "Write 'Hello' to demo/test.txt"

# patch
hermes-lite chat -q "Use patch to change 'Hello' to 'Greetings' in demo/sample_project/main.py"

# search_files
hermes-lite chat -q "Search for 'TODO' in demo/"

# terminal
hermes-lite chat -q "Run 'python3 demo/sample_project/main.py'"

# process
hermes-lite chat -q "Start a background python HTTP server on port 8000"

# todo
hermes-lite chat -q "Create a todo list with 3 tasks"

# clarify
hermes-lite chat -q "Ask me what my favorite programming language is, then write a hello world program in it"
```

## Performance Expectations

| Operation | Expected Time |
|-----------|---------------|
| Single file read | < 2 seconds |
| Search entire demo/ | < 3 seconds |
| Write new file | < 2 seconds |
| Patch existing file | < 3 seconds |
| Terminal command | < 2 seconds |
| Todo creation | < 2 seconds |
| Full workflow (6 steps) | < 30 seconds |

## Tips

1. **Start simple** - Try one tool at a time before combining them
2. **Watch the output** - Use `/verbose` to see tool execution details
3. **Use @mentions in TUI** - More intuitive than /ask commands
4. **Check logs** - See `~/.hermes-lite/logs/` for trajectory files
5. **Session resume** - Use `hermes-lite -c` to continue where you left off

Ready to dive deeper? Check out the full scenarios in `demo/README.md`! 🚀
