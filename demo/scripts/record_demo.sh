#!/usr/bin/env bash
# Record the hermes-lite demo as MP4 using Docker.
#
# Usage:
#   ./demo/scripts/record_demo.sh                    # TUI-only demo
#   ./demo/scripts/record_demo.sh --full              # TUI + CLI image scenes
#   ./demo/scripts/record_demo.sh --fast              # 2x speed
#   ./demo/scripts/record_demo.sh --full --fast       # both
#
# Requires: Docker, ANTHROPIC_API_KEY set
# Output: output/hermes-demo.mp4

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Parse args
MODE="tui-only"
SPEED="1.0"
for arg in "$@"; do
    case "$arg" in
        --full)     MODE="full" ;;
        --cli-only) MODE="cli-only" ;;
        --fast)     SPEED="2.0" ;;
    esac
done

# Check API key
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set"
    echo "  export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

# Create output dir
mkdir -p output

echo "Building Docker image (first run takes a few minutes)..."
docker build -t hermes-demo-recorder -f demo/docker/Dockerfile .

echo ""
echo "Recording demo (mode: ${MODE}, speed: ${SPEED}x)..."
echo ""

docker run --rm \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
    -e DEMO_MODE="${MODE}" \
    -e DEMO_SPEED="${SPEED}" \
    -v "$(pwd)/output:/output" \
    hermes-demo-recorder

echo ""
echo "Output:"
ls -lh output/hermes-demo.*
