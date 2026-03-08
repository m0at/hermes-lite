#!/bin/bash
# Verification script for the hermes-lite demo
# Checks that all files are present and scripts are executable

echo "🔍 hermes-lite Demo Verification"
echo "================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$DEMO_DIR")"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

CHECKS_PASSED=0
CHECKS_FAILED=0

check_file() {
    local file="$1"
    local description="$2"
    
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $description"
        ((CHECKS_PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} $description (missing: $file)"
        ((CHECKS_FAILED++))
        return 1
    fi
}

check_dir() {
    local dir="$1"
    local description="$2"
    
    if [ -d "$dir" ]; then
        echo -e "${GREEN}✓${NC} $description"
        ((CHECKS_PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} $description (missing: $dir)"
        ((CHECKS_FAILED++))
        return 1
    fi
}

check_executable() {
    local file="$1"
    local description="$2"
    
    if [ -x "$file" ]; then
        echo -e "${GREEN}✓${NC} $description"
        ((CHECKS_PASSED++))
        return 0
    else
        echo -e "${YELLOW}!${NC} $description (not executable: $file)"
        echo "    Run: chmod +x $file"
        ((CHECKS_FAILED++))
        return 1
    fi
}

check_command() {
    local cmd="$1"
    local description="$2"
    
    if command -v "$cmd" &> /dev/null; then
        echo -e "${GREEN}✓${NC} $description"
        ((CHECKS_PASSED++))
        return 0
    else
        echo -e "${YELLOW}!${NC} $description (command not found: $cmd)"
        ((CHECKS_FAILED++))
        return 1
    fi
}

echo "📖 Checking Documentation Files"
echo "--------------------------------"
check_file "$DEMO_DIR/START_HERE.md" "START_HERE.md"
check_file "$DEMO_DIR/DEMO_OVERVIEW.md" "DEMO_OVERVIEW.md"
check_file "$DEMO_DIR/QUICKSTART.md" "QUICKSTART.md"
check_file "$DEMO_DIR/README.md" "README.md (main scenarios)"
check_file "$DEMO_DIR/TUI_DEMO.md" "TUI_DEMO.md"
check_file "$DEMO_DIR/EXPECTED_OUTPUT.md" "EXPECTED_OUTPUT.md"
check_file "$DEMO_DIR/FEATURES_CHECKLIST.md" "FEATURES_CHECKLIST.md"
check_file "$DEMO_DIR/INDEX.md" "INDEX.md"
check_file "$DEMO_DIR/VISUAL_GUIDE.md" "VISUAL_GUIDE.md"
echo ""

echo "🎯 Checking Sample Project Files"
echo "---------------------------------"
check_dir "$DEMO_DIR/sample_project" "sample_project/ directory"
check_file "$DEMO_DIR/sample_project/main.py" "main.py"
check_file "$DEMO_DIR/sample_project/calculator.py" "calculator.py"
check_file "$DEMO_DIR/sample_project/utils.py" "utils.py"
echo ""

echo "📁 Checking Sample Data Files"
echo "------------------------------"
check_dir "$DEMO_DIR/sample_data" "sample_data/ directory"
check_file "$DEMO_DIR/sample_data/data.json" "data.json"
check_file "$DEMO_DIR/sample_data/config.yaml" "config.yaml"
check_file "$DEMO_DIR/sample_data/notes.txt" "notes.txt"
echo ""

echo "🔧 Checking Scripts"
echo "-------------------"
check_dir "$DEMO_DIR/scripts" "scripts/ directory"
check_file "$DEMO_DIR/scripts/run_all_demos.sh" "run_all_demos.sh"
check_file "$DEMO_DIR/scripts/test_features.py" "test_features.py"
check_executable "$DEMO_DIR/scripts/run_all_demos.sh" "run_all_demos.sh is executable"
check_executable "$DEMO_DIR/scripts/test_features.py" "test_features.py is executable"
echo ""

echo "🛠️ Checking System Requirements"
echo "--------------------------------"
check_command "python3" "Python 3 installed"
check_command "hermes-lite" "hermes-lite command available"

# Optional checks
if command -v cargo &> /dev/null; then
    echo -e "${GREEN}✓${NC} Rust/Cargo installed (for TUI)"
    ((CHECKS_PASSED++))
else
    echo -e "${YELLOW}!${NC} Rust/Cargo not found (TUI demos won't work)"
    echo "    Install from: https://rustup.rs/"
fi

if [ -f "$ROOT_DIR/target/release/hermes-tui" ]; then
    echo -e "${GREEN}✓${NC} hermes-tui built"
    ((CHECKS_PASSED++))
else
    echo -e "${YELLOW}!${NC} hermes-tui not built"
    echo "    Run: cargo build --release -p hermes_tui"
fi

echo ""

# Summary
echo "================================"
echo "📊 Verification Summary"
echo "================================"
echo -e "Passed: ${GREEN}$CHECKS_PASSED${NC}"
echo -e "Failed: ${RED}$CHECKS_FAILED${NC}"
echo ""

if [ $CHECKS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed!${NC}"
    echo ""
    echo "🚀 You're ready to run the demos!"
    echo ""
    echo "Quick start:"
    echo "  hermes-lite chat -q \"Read demo/sample_project/main.py\""
    echo ""
    echo "Or read:"
    echo "  cat demo/START_HERE.md"
    echo ""
    exit 0
else
    echo -e "${YELLOW}⚠️  Some checks failed${NC}"
    echo ""
    echo "Please fix the issues above, then run this script again."
    echo ""
    exit 1
fi
