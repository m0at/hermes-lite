#!/usr/bin/env bash
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────
CAST_FILE="/tmp/hermes-demo.cast"
GIF_FILE="/tmp/hermes-demo.gif"
MP4_FILE="/output/hermes-demo.mp4"
SPEED="${DEMO_SPEED:-1.0}"
MODE="${DEMO_MODE:-tui-only}"  # tui-only, cli-only, or full

# ── Preflight checks ────────────────────────────────────────────────────
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set"
    echo "Usage: docker run --rm -e ANTHROPIC_API_KEY=\$ANTHROPIC_API_KEY -v \$(pwd)/output:/output hermes-demo-recorder"
    exit 1
fi

if [ ! -d "/output" ]; then
    echo "ERROR: /output not mounted"
    echo "Add: -v \$(pwd)/output:/output"
    exit 1
fi

echo "============================================"
echo "  hermes-lite Demo Recorder"
echo "  Mode: ${MODE} | Speed: ${SPEED}x"
echo "  Terminal: ${COLUMNS}x${LINES}"
echo "============================================"
echo ""

# ── Step 1: Record with asciinema ────────────────────────────────────────
echo "[1/3] Recording demo..."

DRIVER_ARGS="--speed ${SPEED}"
case "${MODE}" in
    tui-only) DRIVER_ARGS="${DRIVER_ARGS} --tui-only" ;;
    cli-only) DRIVER_ARGS="${DRIVER_ARGS} --cli-only" ;;
    full)     ;;  # no extra flag
esac

# asciinema records everything the pexpect script renders
asciinema rec "${CAST_FILE}" \
    --overwrite \
    --cols "${COLUMNS}" \
    --rows "${LINES}" \
    -c "python3 demo/scripts/tui_demo_driver.py ${DRIVER_ARGS}"

echo ""
echo "[1/3] Recording complete: $(du -h "${CAST_FILE}" | cut -f1)"

# ── Step 2: Render to GIF with agg ──────────────────────────────────────
echo "[2/3] Rendering to GIF..."

agg "${CAST_FILE}" "${GIF_FILE}" \
    --theme monokai \
    --font-size 16 \
    --fps-cap 30 \
    --speed "${SPEED}" \
    --cols "${COLUMNS}" \
    --rows "${LINES}"

echo "[2/3] GIF rendered: $(du -h "${GIF_FILE}" | cut -f1)"

# ── Step 3: Convert to MP4 with ffmpeg ───────────────────────────────────
echo "[3/3] Converting to MP4..."

ffmpeg -y \
    -i "${GIF_FILE}" \
    -movflags faststart \
    -pix_fmt yuv420p \
    -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \
    -c:v libx264 \
    -preset medium \
    -crf 18 \
    "${MP4_FILE}" \
    2>/dev/null

echo "[3/3] MP4 created: $(du -h "${MP4_FILE}" | cut -f1)"

# ── Also copy the raw .cast file (useful for asciinema player embeds) ────
cp "${CAST_FILE}" "/output/hermes-demo.cast"

echo ""
echo "============================================"
echo "  Done!"
echo "  MP4:  ${MP4_FILE}"
echo "  Cast: /output/hermes-demo.cast"
echo "============================================"
