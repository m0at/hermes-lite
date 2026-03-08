# hermes-lite demo recorder
# Builds everything from source, records the automated demo, outputs MP4.
#
# Usage:
#   docker build -t hermes-demo-recorder -f demo/docker/Dockerfile .
#   docker run --rm -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
#     -v $(pwd)/output:/output hermes-demo-recorder
#
# The MP4 will appear at ./output/hermes-demo.mp4

# ── Stage 1: Rust builder ────────────────────────────────────────────────
FROM rust:1.82-bookworm AS rust-builder

WORKDIR /build

# Build agg (asciinema gif generator) first — it's a separate crate
RUN cargo install --git https://github.com/asciinema/agg agg

# Copy Rust sources
COPY Cargo.toml Cargo.lock ./
COPY hermes_rs/ hermes_rs/
COPY hermes_tui/ hermes_tui/

# Build the TUI binary
RUN cargo build --release -p hermes_tui

# Build the Python extension (maturin wheel)
RUN pip install maturin --break-system-packages \
    && maturin build --release -m hermes_rs/Cargo.toml -o /wheels

# ── Stage 2: Runtime + recorder ──────────────────────────────────────────
FROM python:3.12-bookworm

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip install --no-cache-dir asciinema pexpect

WORKDIR /app

# Copy the full repo (Python sources needed at runtime)
COPY . .

# Install the Python package + Rust extension wheel
COPY --from=rust-builder /wheels/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

# Install the hermes-lite package itself
RUN pip install --no-cache-dir -e .

# Copy built binaries
COPY --from=rust-builder /build/target/release/hermes-tui /app/target/release/hermes-tui
COPY --from=rust-builder /usr/local/cargo/bin/agg /usr/local/bin/agg

# Recording script
COPY demo/docker/record.sh /record.sh
RUN chmod +x /record.sh

# Output directory (mount point)
VOLUME /output

# Terminal size for consistent recording
ENV COLUMNS=120
ENV LINES=40
ENV TERM=xterm-256color

ENTRYPOINT ["/record.sh"]
