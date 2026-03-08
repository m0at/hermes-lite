#!/bin/bash
# Automated demo script to showcase all hermes-lite features
# This runs through each scenario sequentially

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$DEMO_DIR")"

echo "🚀 hermes-lite Feature Demo Runner"
echo "=================================="
echo ""
echo "This script will run through all demo scenarios."
echo "Press Enter after each scenario to continue to the next one."
echo ""

# Check if hermes-lite is available
if ! command -v hermes-lite &> /dev/null; then
    echo "❌ hermes-lite not found. Please install it first:"
    echo "   pip install -e ."
    exit 1
fi

echo "✅ hermes-lite found"
echo ""

# Scenario 1: Basic Tool Showcase
echo "📋 Scenario 1: Basic Tool Showcase"
echo "-----------------------------------"
echo "This will exercise all 8 core tools in one workflow."
read -p "Press Enter to start..."

hermes-lite chat -q "
Please analyze the demo project and perform this workflow:

1. Read the demo/sample_project/main.py file and tell me what it does
2. Search for all TODO comments in the demo/ directory
3. Create a todo list with the top 3 improvements needed
4. Show me the current content of calculator.py
5. Run 'python3 demo/sample_project/main.py 20 10' to test the program

After completing each step, give me a brief summary.
"

echo ""
echo "✅ Scenario 1 complete!"
echo ""
read -p "Press Enter for next scenario..."

# Scenario 2: Dangerous Command Test
echo ""
echo "⚠️  Scenario 2: Dangerous Command Approval"
echo "-------------------------------------------"
echo "This will trigger safety features."
read -p "Press Enter to start..."

hermes-lite chat -q "
Please attempt these operations:

1. Create a test directory at /tmp/hermes-demo-test
2. Run: rm -rf /tmp/hermes-demo-test (this should trigger approval)
3. List the demo directory contents safely

Report what happened with each command.
"

echo ""
echo "✅ Scenario 2 complete!"
echo ""
read -p "Press Enter for next scenario..."

# Scenario 3: File Search Demo
echo ""
echo "🔍 Scenario 3: File Search Power"
echo "--------------------------------"
echo "This demonstrates ripgrep-backed search."
read -p "Press Enter to start..."

hermes-lite chat -q "
Use search_files to:

1. Find all Python function definitions in demo/ (search for 'def ')
2. Find all TODO comments
3. Count how many times 'import' appears in each file
4. Find all .json files

Give me a summary of what you found.
"

echo ""
echo "✅ Scenario 3 complete!"
echo ""
read -p "Press Enter for next scenario..."

# Scenario 4: Fuzzy Patch Demo
echo ""
echo "🎯 Scenario 4: Fuzzy Patch Matching"
echo "-----------------------------------"
echo "This shows intelligent code editing."
read -p "Press Enter to start..."

hermes-lite chat -q "
Use the patch tool to make these changes to demo/sample_project/calculator.py:

1. Add a multiply function that multiplies two numbers
2. Add a docstring to the new multiply function

Show me the changes you made.
"

echo ""
echo "✅ Scenario 4 complete!"
echo ""
read -p "Press Enter for next scenario..."

# Scenario 5: Background Process
echo ""
echo "🔄 Scenario 5: Background Process Management"
echo "--------------------------------------------"
echo "This demonstrates the process tool."
read -p "Press Enter to start..."

hermes-lite chat -q "
Demonstrate background process management:

1. Start a simple background process: 'python3 -m http.server 8765' from demo/sample_project directory
2. Wait 2 seconds
3. Check if the process is running by polling it
4. Kill the background process

Report the status at each step.
"

echo ""
echo "✅ Scenario 5 complete!"
echo ""
read -p "Press Enter for next scenario..."

# Scenario 6: Write Protection
echo ""
echo "🛡️  Scenario 6: Write Protection"
echo "--------------------------------"
echo "This tests file write safety."
read -p "Press Enter to start..."

hermes-lite chat -q "
Test write protection by attempting to:

1. Write 'test' to demo/safe_output.txt (this should work)
2. Write 'test' to ~/.bashrc (this should be blocked)

Report which operations succeeded and which were blocked.
"

echo ""
echo "✅ Scenario 6 complete!"
echo ""

# Final summary
echo ""
echo "🎉 All scenarios complete!"
echo "=========================="
echo ""
echo "You've seen:"
echo "  ✅ All 8 core tools in action"
echo "  ✅ Dangerous command approval"
echo "  ✅ Write protection"
echo "  ✅ Fuzzy patch matching"
echo "  ✅ Background process management"
echo "  ✅ Ripgrep-backed search"
echo ""
echo "Next steps:"
echo "  1. Try the Rust TUI: ./target/release/hermes-tui"
echo "  2. Explore multi-agent mode with /split and @mentions"
echo "  3. Run the test suite: python3 -m pytest tests/"
echo ""
echo "For more scenarios, see demo/README.md"
echo ""
