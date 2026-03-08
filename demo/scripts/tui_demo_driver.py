#!/usr/bin/env python3
"""
Automated TUI demo driver for screen recording.

Uses tmux to run the TUI/CLI, sends keystrokes via `tmux send-keys`,
and records with asciinema by attaching to the tmux session.

Usage:
    python3 demo/scripts/tui_demo_driver.py              # run TUI demo
    python3 demo/scripts/tui_demo_driver.py --fast        # 2x speed
    python3 demo/scripts/tui_demo_driver.py --scene 3     # jump to scene 3
    python3 demo/scripts/tui_demo_driver.py --dry-run     # print scenes
    python3 demo/scripts/tui_demo_driver.py --record      # record to .cast + .mp4

Requires: tmux, asciinema (for --record), agg + ffmpeg (for MP4)
"""

import argparse
import os
import random
import subprocess
import sys
import time

# ── Config ───────────────────────────────────────────────────────────────

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

HERMES_TUI = os.path.join(_REPO_ROOT, "target", "release", "hermes-tui")
HERMES_CLI = os.path.join(_REPO_ROOT, ".venv", "bin", "hermes-lite")

TMUX_SESSION = "hermes-demo"
COLS, ROWS = 120, 40

# Typing speed
CHAR_DELAY = 0.045
CHAR_JITTER = 0.02

SCENE_PAUSE = 2.0
PRE_ENTER_PAUSE = 0.4

# ── Scene definitions ────────────────────────────────────────────────────

_BUILD_PROMPT = (
    "Create a Vite vanilla JS app in /tmp/hermes-weather with these files: "
    "package.json (vite dep, dev script on port 4321), index.html, src/style.css, src/weather.js, src/chat.js, src/main.js. "
    "\n\n"
    "This is 'HERMES WEATHER COMMAND CENTER' — a split-screen ops dashboard. "
    "100vh, no body scroll, CSS grid: left 65% weather monitor, right 35% Hermes chat. "
    "Use @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap') for monospace. "
    "\n\n"
    "LEFT PANEL — Extreme Weather Monitor: "
    "Background #080808. Top bar: '⚡ HERMES WEATHER COMMAND CENTER' in gold #d4a574, "
    "with live stats '8 Active Events | 3 Critical | 2 Escalating' and a real-time UTC clock that updates every second. "
    "Below: CSS grid of 8 event cards (2 columns, gap 12px, padding 16px). "
    "Each card: dark bg #111 with 1px solid #222 border, border-radius 8px, "
    "subtle box-shadow 0 0 20px rgba(212,165,116,0.05). "
    "Card contents: emoji + event name bold at top, location + coordinates in dim gray, "
    "a severity bar (div with colored gradient bg — red for 5, orange for 4, yellow for 3 — width proportional to level out of 5), "
    "time-ago text that updates live ('2h 34m ago' etc). "
    "Level-5 (critical) cards get a CSS animation: pulsing red border-glow (box-shadow pulse 0 0 15px rgba(255,50,50,0.4)). "
    "Events data array in weather.js: "
    "(1) {name:'Hurricane Valentina Cat-5',emoji:'🌀',location:'Caribbean Sea',coords:'18.2°N 64.8°W',severity:5,hoursAgo:2}, "
    "(2) {name:'M7.2 Earthquake',emoji:'🌍',location:'Hokkaido, Japan',coords:'42.8°N 143.2°E',severity:5,hoursAgo:1}, "
    "(3) {name:'Extreme Heat Dome 54°C',emoji:'🔥',location:'Persian Gulf',coords:'27.1°N 49.6°E',severity:5,hoursAgo:8}, "
    "(4) {name:'EF4 Tornado Outbreak',emoji:'🌪️',location:'Oklahoma, USA',coords:'35.4°N 97.5°W',severity:4,hoursAgo:3}, "
    "(5) {name:'Eyjafjallajökull Eruption',emoji:'🌋',location:'Iceland',coords:'63.6°N 19.6°W',severity:4,hoursAgo:12}, "
    "(6) {name:'Catastrophic Flooding',emoji:'🌊',location:'Dhaka, Bangladesh',coords:'23.8°N 90.4°E',severity:4,hoursAgo:18}, "
    "(7) {name:'Arctic Blast -52°C',emoji:'❄️',location:'Tromsø, Norway',coords:'69.6°N 19.0°E',severity:3,hoursAgo:6}, "
    "(8) {name:'Bushfire Emergency',emoji:'🔥',location:'New South Wales, AU',coords:'33.8°S 151.2°E',severity:3,hoursAgo:24}. "
    "Add a subtle animated CSS scanline overlay on the whole left panel (repeating-linear-gradient with 2px transparent/rgba bands, moving slowly downward). "
    "\n\n"
    "RIGHT PANEL — Hermes Agent Chat: "
    "Full height, bg #0a0a0a, left border 2px solid #d4a574. "
    "Header: gold bg bar with '⚕ Hermes Agent' bold white text and a pulsing green dot (CSS animation) as status. "
    "Scrollable message area (.chat-messages) taking remaining space with flex-grow, overflow-y auto. "
    "Messages: user messages in right-aligned bubbles bg #1a2332 with subtle blue-left-border, "
    "Hermes responses left-aligned with gold left-border 3px solid #d4a574, bg #111. "
    "Each Hermes message has a small '⚕ Hermes' label in gold above it. "
    "Include fake tool-call lines styled like our TUI: '  ┊ ✓ weather_api   fetched 8 events  (0.8s)' in dim green. "
    "Pre-load 4 messages in chat.js: "
    "(1) user: 'What are the most critical events right now?' "
    "(2) hermes tool line: '✓ weather_api   scanning global feeds  (1.2s)', "
    "then hermes response: 'Three events at CRITICAL severity. Hurricane Valentina is a Cat-5 threatening the Caribbean with 180mph winds. A M7.2 earthquake struck Hokkaido 1 hour ago — tsunami advisory active. The Persian Gulf heat dome has reached 54°C, the highest temperature ever reliably recorded. I recommend immediate monitoring of all three.' "
    "(3) user: 'Show me the hurricane trajectory forecast' "
    "(4) hermes tool line: '✓ trajectory_model  running Monte Carlo  (2.1s)', "
    "then hermes response: 'Valentina is tracking WNW at 12kt. The ensemble model shows 68% probability of landfall on Puerto Rico within 36 hours. Wind field extends 120nm from center. Storm surge forecast: 4-6m on southeast coast. I have flagged this for escalation.' "
    "At bottom: input field with dark bg #111, gold border on focus, placeholder 'Ask Hermes about weather events...'. "
    "When user submits text, add their message bubble, show a typing indicator (three pulsing dots in gold), "
    "then after 1.5s add a Hermes response. Use keyword matching: if input contains 'hurricane' or 'storm' respond about Valentina, "
    "if 'earthquake' or 'quake' respond about Hokkaido, if 'heat' or 'temperature' respond about the heat dome, "
    "otherwise give a generic weather analysis response. Always prepend a fake tool-call line. "
    "Input clears after send, auto-scroll to bottom. Enter key to send. "
    "\n\n"
    "OVERALL STYLE: Everything JetBrains Mono. Custom thin scrollbar (#333 thumb, transparent track). "
    "No default margins/padding on body. Smooth transitions on hover states. "
    "Cards hover: slight translateY(-2px) and brighter border. "
    "Make it look like a real military/ops command center, dark and serious."
)

_SWARM_AGENTS = ["frontend", "stylist", "enhancer", "security", "qa"]

_DELEGATE_PROMPT = (
    "You lead a 5-agent swarm. Use delegate_task for each:\n"
    "(1) 'frontend': Read /tmp/hermes-weather/src/weather.js and /tmp/hermes-weather/src/main.js. "
    "Add a click handler on each weather card that expands it inline to show a 'details' section: "
    "a 3-line ASCII-art mini-graph of severity trend (rising/falling/stable using ▁▂▃▅▇ block chars), "
    "a 'Last Updated' timestamp, and a 'Status: ACTIVE/MONITORING/RESOLVED' line. "
    "Clicking again collapses it. Use CSS transition max-height for smooth animation.\n"
    "(2) 'stylist': Read /tmp/hermes-weather/src/style.css. Add these visual upgrades: "
    "a radar-sweep CSS animation on the header (rotating gradient arc), "
    "card severity bars should have animated shimmer (moving gradient highlight), "
    "the chat typing indicator dots should bounce sequentially not all at once. "
    "Add a subtle grid-line background pattern on the left panel using CSS background-image repeating-linear-gradient.\n"
    "(3) 'enhancer': Read /tmp/hermes-weather/src/chat.js. "
    "Improve Hermes chat responses — add 3 more keyword handlers: "
    "'flood' responds about Bangladesh situation, 'volcano' about Iceland eruption, "
    "'forecast' gives a 48-hour global outlook summary. "
    "Also make the typing indicator show 'Hermes is analyzing...' text next to the dots.\n"
    "(4) 'security': Read all files in /tmp/hermes-weather/src/. "
    "Check for XSS in the chat input (make sure user messages are text-content not innerHTML), "
    "check for any injection risks, verify Content-Security-Policy would work. Give a security audit report.\n"
    "(5) 'qa': Read all files in /tmp/hermes-weather/src/ and index.html. "
    "Verify: all 8 weather events render, chat has 4 pre-loaded messages, "
    "input field exists and sends on Enter, severity bars show correct widths, "
    "critical events have pulse animation. Report any bugs or missing features."
)

SCENES = [
    # ── Act 1: List and load skills ────────────────────────────────────────
    {
        "title": "Scene 1: Browse skills and load frontend-design",
        "steps": [
            {"type": "wait", "seconds": 3},
            {"type": "narrate", "text": "Checking available skills..."},
            {"type": "wait", "seconds": 1},
            {"type": "send", "text": (
                "List your available skills, then load the frontend-design skill. "
                "Briefly summarize what it teaches you."
            )},
            {"type": "wait_quiet", "seconds": 30},
            {"type": "wait", "seconds": 3},
        ],
    },
    # ── Act 2: Build the full weather command center ──────────────────────
    {
        "title": "Scene 2: Build Hermes Weather Command Center",
        "steps": [
            {"type": "narrate", "text": "Building the Hermes Weather Command Center..."},
            {"type": "wait", "seconds": 1},
            {"type": "send", "text": _BUILD_PROMPT},
            {"type": "wait_quiet", "seconds": 180},
            {"type": "wait", "seconds": 3},
        ],
    },
    # ── Act 3: Install and launch ─────────────────────────────────────────
    {
        "title": "Scene 3: Install and start dev server",
        "steps": [
            {"type": "narrate", "text": "Installing and launching..."},
            {"type": "send", "text": (
                "cd /tmp/hermes-weather && npm install && npx vite --port 4321 & "
                "Sleep 3 seconds, then curl http://localhost:4321 to verify it serves. "
                "Show the first 30 lines of HTML output."
            )},
            {"type": "wait_quiet", "seconds": 60},
            {"type": "wait", "seconds": 2},
        ],
    },
    # ── Act 4: Open and verify ────────────────────────────────────────────
    {
        "title": "Scene 4: Open in browser",
        "steps": [
            {"type": "narrate", "text": "Opening in browser..."},
            {"type": "send", "text": (
                "Run: open http://localhost:4321 — then describe what the page looks like: "
                "confirm the split layout, count the weather event cards, "
                "verify the Hermes chat panel has pre-loaded messages."
            )},
            {"type": "wait_quiet", "seconds": 30},
            {"type": "wait", "seconds": 3},
        ],
    },
    # ── Act 5: Set up 6-agent swarm ───────────────────────────────────────
    {
        "title": "Scene 5: Deploy 6-agent swarm",
        "steps": [
            {"type": "narrate", "text": "Deploying 6-agent swarm..."},
            {"type": "send", "text": "/name architect"},
            {"type": "wait", "seconds": 1},
        ] + [
            step
            for name in _SWARM_AGENTS
            for step in [
                {"type": "send", "text": "/split"},
                {"type": "wait", "seconds": 6},
                {"type": "key", "key": "C-Right"},
                {"type": "wait", "seconds": 1},
                {"type": "send", "text": f"/name {name}"},
                {"type": "wait", "seconds": 1},
            ]
        ] + [
            {"type": "send", "text": "/tabs"},
            {"type": "wait", "seconds": 2},
            {"type": "narrate", "text": "Listing agents..."},
            {"type": "send", "text": "/agents"},
            {"type": "wait", "seconds": 4},
        ],
    },
    # ── Act 6: Architect delegates to the swarm ───────────────────────────
    {
        "title": "Scene 6: Architect delegates to swarm",
        "steps": [
            {"type": "narrate", "text": "Architect delegating tasks to 5 workers..."},
            {"type": "key", "key": "M-1"},
            {"type": "wait", "seconds": 1},
            {"type": "send", "text": _DELEGATE_PROMPT},
            {"type": "wait_quiet", "seconds": 120},
            {"type": "wait", "seconds": 3},
            # Wait for workers
            {"type": "narrate", "text": "Workers processing..."},
            {"type": "key", "key": "M-2"},
            {"type": "wait_quiet", "seconds": 90},
            {"type": "key", "key": "M-3"},
            {"type": "wait_quiet", "seconds": 60},
            {"type": "key", "key": "M-4"},
            {"type": "wait_quiet", "seconds": 60},
            {"type": "key", "key": "M-5"},
            {"type": "wait_quiet", "seconds": 60},
            {"type": "key", "key": "M-6"},
            {"type": "wait_quiet", "seconds": 60},
            {"type": "wait", "seconds": 2},
        ],
    },
    # ── Act 7: Architect reviews ──────────────────────────────────────────
    {
        "title": "Scene 7: Architect reviews swarm results",
        "steps": [
            {"type": "narrate", "text": "Architect reviewing results..."},
            {"type": "key", "key": "M-1"},
            {"type": "wait", "seconds": 1},
            {"type": "send", "text": "Summarize what each agent in the swarm reported back. One line per agent."},
            {"type": "wait_quiet", "seconds": 45},
            {"type": "wait", "seconds": 3},
        ],
    },
    # ── Act 8: Architect saves swarm knowledge to shared memory ───────────
    {
        "title": "Scene 8: Save project memories (shared across swarm)",
        "steps": [
            {"type": "narrate", "text": "Saving project knowledge to shared memory..."},
            {"type": "key", "key": "M-1"},
            {"type": "wait", "seconds": 1},
            {"type": "send", "text": (
                "Save what we've built to your project memory so all agents remember it. "
                "Use the memory tool with target='project' to save: "
                "(1) The app structure: Vite vanilla JS app at /tmp/hermes-weather with weather.js, chat.js, style.css, main.js. "
                "(2) The 6-agent swarm roles: architect, frontend, stylist, enhancer, security, qa. "
                "(3) Key decisions: 8 weather events, split-screen layout, JetBrains Mono font, dark ops theme."
            )},
            {"type": "wait_quiet", "seconds": 30},
            {"type": "wait", "seconds": 2},
        ],
    },
    # ── Act 9: Sub-agent reads shared memories ─────────────────────────────
    {
        "title": "Scene 9: Sub-agent reads shared project memories",
        "steps": [
            {"type": "narrate", "text": "Frontend agent reading shared memories..."},
            {"type": "key", "key": "M-2"},
            {"type": "wait", "seconds": 1},
            {"type": "send", "text": (
                "Read your project memories to see what the team has documented about this project. "
                "Then briefly confirm you can see the shared context from the architect."
            )},
            {"type": "wait_quiet", "seconds": 30},
            {"type": "wait", "seconds": 3},
        ],
    },
    # ── Act 10: Broadcast status check ─────────────────────────────────────
    {
        "title": "Scene 10: Broadcast to all agents",
        "steps": [
            {"type": "narrate", "text": "Broadcasting status check..."},
            {"type": "send", "text": "/broadcast Report your status in one sentence."},
            {"type": "wait_quiet", "seconds": 60},
            {"type": "wait", "seconds": 2},
            {"type": "key", "key": "M-2"},
            {"type": "wait", "seconds": 2},
            {"type": "key", "key": "M-4"},
            {"type": "wait", "seconds": 2},
            {"type": "key", "key": "M-6"},
            {"type": "wait", "seconds": 2},
        ],
    },
    # ── Act 11: Final app verification ────────────────────────────────────
    {
        "title": "Scene 11: Final verification",
        "steps": [
            {"type": "narrate", "text": "Final verification..."},
            {"type": "key", "key": "M-1"},
            {"type": "wait", "seconds": 1},
            {"type": "send", "text": (
                "Curl http://localhost:4321 and verify the page has all 8 weather events "
                "and the Hermes chat panel. Then open http://localhost:4321 in the browser."
            )},
            {"type": "wait_quiet", "seconds": 30},
            {"type": "wait", "seconds": 3},
        ],
    },
    # ── Act 12: Usage stats ───────────────────────────────────────────────
    {
        "title": "Scene 12: Usage stats",
        "steps": [
            {"type": "narrate", "text": "Token usage across the swarm..."},
            {"type": "send", "text": "/usage"},
            {"type": "wait", "seconds": 4},
        ],
    },
    # ── Act 13: Shutdown ──────────────────────────────────────────────────
    {
        "title": "Scene 13: Shutdown swarm",
        "steps": [
            {"type": "narrate", "text": "Shutting down..."},
        ] + [
            step
            for _ in range(5)
            for step in [
                {"type": "send", "text": "/close"},
                {"type": "wait", "seconds": 0.5},
            ]
        ] + [
            {"type": "send", "text": "/quit"},
            {"type": "wait", "seconds": 2},
        ],
    },
]

CLI_SCENES = []


# ── Clipboard helper ─────────────────────────────────────────────────────

def copy_image_to_clipboard(image_path: str):
    abs_path = os.path.abspath(image_path)
    if not os.path.exists(abs_path):
        log(f"WARNING: Image not found: {abs_path}")
        return False
    if sys.platform == "darwin":
        script = f'''
        set theFile to POSIX file "{abs_path}"
        set theImage to read theFile as «class PNGf»
        set the clipboard to theImage
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=True,
                           capture_output=True, timeout=5)
            return True
        except Exception as e:
            log(f"WARNING: Clipboard copy failed: {e}")
            return False
    return False


# ── tmux driver ──────────────────────────────────────────────────────────

def log(msg: str):
    print(f"  >> {msg}", file=sys.stderr, flush=True)


def tmux(*args):
    """Run a tmux command."""
    subprocess.run(["tmux"] + list(args), capture_output=True)


def tmux_send_keys(*keys):
    """Send keys to the tmux session."""
    subprocess.run(["tmux", "send-keys", "-t", TMUX_SESSION] + list(keys),
                   capture_output=True)


def tmux_has_session():
    r = subprocess.run(["tmux", "has-session", "-t", TMUX_SESSION],
                       capture_output=True)
    return r.returncode == 0


def tmux_capture():
    """Capture current tmux pane content (for detecting quiet)."""
    r = subprocess.run(
        ["tmux", "capture-pane", "-t", TMUX_SESSION, "-p"],
        capture_output=True, text=True
    )
    return r.stdout if r.returncode == 0 else ""


def tmux_kill():
    subprocess.run(["tmux", "kill-session", "-t", TMUX_SESSION],
                   capture_output=True)


class DemoDriver:
    def __init__(self, speed_mult: float = 1.0):
        self.speed = speed_mult

    def _delay(self, seconds: float):
        time.sleep(seconds / self.speed)

    def start_tui(self):
        tui_path = os.path.abspath(HERMES_TUI)
        if not os.path.exists(tui_path):
            print(f"ERROR: TUI not found at {tui_path}", file=sys.stderr)
            sys.exit(1)

        if tmux_has_session():
            tmux_kill()

        # Pass ANTHROPIC_API_KEY through to tmux session so agent subprocess inherits it
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        env_prefix = f"ANTHROPIC_API_KEY={api_key} " if api_key else ""

        tmux("new-session", "-d", "-s", TMUX_SESSION,
             "-x", str(COLS), "-y", str(ROWS),
             "sh", "-c", f"{env_prefix}{tui_path}")
        log("TUI started in tmux session")

        # Wait for agent subprocess to connect — abort early if it doesn't
        log("Waiting for agent subprocess to connect...")
        connected = False
        for _ in range(15):
            time.sleep(1)
            content = tmux_capture()
            if "No agent subprocess" in content:
                continue
            if content.strip():
                connected = True
                break
        if not connected:
            content = tmux_capture()
            log(f"FATAL: Agent subprocess did not connect after 15s!")
            log(f"TUI pane content:\n{content[:500]}")
            tmux_kill()
            sys.exit(1)
        log("Agent subprocess connected successfully")

    def start_cli(self):
        cli_path = os.path.abspath(HERMES_CLI)
        if not os.path.exists(cli_path):
            print(f"ERROR: CLI not found at {cli_path}", file=sys.stderr)
            sys.exit(1)

        if tmux_has_session():
            tmux_kill()

        tmux("new-session", "-d", "-s", TMUX_SESSION,
             "-x", str(COLS), "-y", str(ROWS), cli_path)
        log("CLI started in tmux session")

    def stop(self):
        try:
            tmux_kill()
        except Exception:
            pass

    def type_text(self, text: str):
        """Type character by character with natural jitter via tmux."""
        for ch in text:
            # tmux send-keys needs special handling for some chars
            if ch == ';':
                tmux_send_keys('-l', ch)
            elif ch == ' ':
                tmux_send_keys('Space')
            else:
                tmux_send_keys('-l', ch)
            delay = CHAR_DELAY + random.uniform(-CHAR_JITTER, CHAR_JITTER)
            self._delay(max(0.01, delay))

    def send_line(self, text: str):
        """Type text then press Enter."""
        self.type_text(text)
        self._delay(PRE_ENTER_PAUSE)
        tmux_send_keys("Enter")

    def send_key(self, key: str):
        """Send a tmux key name (e.g. 'Escape', 'C-Left', 'M-1', 'Up')."""
        tmux_send_keys(key)

    def wait_quiet(self, seconds: int):
        """Wait for the agent to finish by monitoring tmux pane for quiet.

        Polls the tmux pane content. When it stops changing for 5+ seconds
        after initial activity, the agent is done. Falls back to max timeout.
        """
        log(f"Waiting up to {seconds}s for agent...")
        start = time.time()
        last_content = ""
        last_change_time = time.time()
        saw_activity = False

        while time.time() - start < seconds:
            time.sleep(1.0 / self.speed)
            content = tmux_capture()

            # Detect broken agent subprocess mid-demo
            if "No agent subprocess" in content:
                log("WARNING: Agent subprocess disconnected!")

            if content != last_content:
                last_content = content
                last_change_time = time.time()
                saw_activity = True
            else:
                quiet = time.time() - last_change_time
                elapsed = time.time() - start
                # Done if: saw activity, been quiet 6s, and at least 8s elapsed
                if saw_activity and quiet > 6 and elapsed > 8:
                    log(f"Agent finished ({elapsed:.0f}s, quiet {quiet:.0f}s)")
                    return True

        elapsed = time.time() - start
        log(f"Wait complete ({elapsed:.0f}s)")
        return True

    def scroll_up(self, pages: int = 1):
        for _ in range(pages):
            tmux_send_keys("PPage")
            self._delay(0.5)

    def scroll_down(self, pages: int = 1):
        for _ in range(pages):
            tmux_send_keys("NPage")
            self._delay(0.5)

    def run_step(self, step: dict):
        stype = step["type"]

        if stype == "type":
            self.type_text(step["text"])
        elif stype == "enter":
            tmux_send_keys("Enter")
        elif stype == "send":
            self.send_line(step["text"])
        elif stype == "wait_quiet":
            self.wait_quiet(seconds=step.get("seconds", 60))
        elif stype == "wait":
            self._delay(step["seconds"])
        elif stype == "key":
            self.send_key(step["key"])
        elif stype == "scroll_up":
            self.scroll_up(step.get("lines", 1))
        elif stype == "scroll_down":
            self.scroll_down(step.get("lines", 1))
        elif stype == "clipboard_image":
            path = step["path"]
            if copy_image_to_clipboard(path):
                log(f"Copied {path} to clipboard")
            else:
                log(f"FAILED to copy {path} to clipboard")
        elif stype == "narrate":
            log(step["text"])
        else:
            log(f"WARNING: Unknown step type '{stype}'")

    def run_scene(self, scene: dict, scene_num: int):
        title = scene["title"]
        print(f"\n{'='*60}", file=sys.stderr, flush=True)
        print(f"  {title}", file=sys.stderr, flush=True)
        print(f"{'='*60}", file=sys.stderr, flush=True)

        for step in scene["steps"]:
            if not tmux_has_session():
                log("tmux session died!")
                return False
            self.run_step(step)

        self._delay(SCENE_PAUSE)
        return True


# ── Recording ────────────────────────────────────────────────────────────

def record_session(driver, scenes, output_dir):
    """Record the tmux session with asciinema, then convert to MP4."""
    cast_file = os.path.join(output_dir, "hermes-demo.cast")
    gif_file = os.path.join(output_dir, "hermes-demo.gif")
    mp4_file = os.path.join(output_dir, "hermes-demo.mp4")

    os.makedirs(output_dir, exist_ok=True)

    # Start asciinema recording in background (attaches to tmux)
    log("Starting asciinema recording...")
    rec_proc = subprocess.Popen(
        ["asciinema", "rec", cast_file,
         "--overwrite", "--cols", str(COLS), "--rows", str(ROWS),
         "-c", f"tmux attach -t {TMUX_SESSION}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Give asciinema time to attach
    time.sleep(2)

    # Run all scenes
    try:
        for num, scene in scenes:
            if not driver.run_scene(scene, num):
                break
    except (KeyboardInterrupt, SystemExit):
        log("Interrupted")

    # Detach from tmux (which stops asciinema recording)
    time.sleep(1)
    subprocess.run(["tmux", "detach-client", "-s", TMUX_SESSION],
                   capture_output=True)
    time.sleep(1)

    # Wait for asciinema to finish
    try:
        rec_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        rec_proc.terminate()

    if os.path.exists(cast_file) and os.path.getsize(cast_file) > 100:
        log(f"Recording saved: {cast_file} ({os.path.getsize(cast_file)} bytes)")

        # Try to convert to GIF then MP4
        has_agg = subprocess.run(["which", "agg"], capture_output=True).returncode == 0
        has_ffmpeg = subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0

        if has_agg:
            log("Rendering to GIF with agg...")
            r = subprocess.run(
                ["agg", cast_file, gif_file,
                 "--theme", "monokai", "--font-size", "16", "--fps-cap", "30"],
                capture_output=True, text=True
            )
            if r.returncode == 0 and os.path.exists(gif_file):
                log(f"GIF: {gif_file} ({os.path.getsize(gif_file) // 1024}KB)")

                if has_ffmpeg:
                    log("Converting to MP4...")
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", gif_file,
                         "-movflags", "faststart", "-pix_fmt", "yuv420p",
                         "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                         mp4_file],
                        capture_output=True
                    )
                    if os.path.exists(mp4_file):
                        log(f"MP4: {mp4_file} ({os.path.getsize(mp4_file) // 1024}KB)")
                    else:
                        log("MP4 conversion failed")
            else:
                log(f"agg failed: {r.stderr[:200] if r.stderr else 'unknown error'}")
        else:
            log("agg not installed — skipping GIF/MP4 conversion")
            log("Install: cargo install --git https://github.com/asciinema/agg agg")

        return cast_file
    else:
        log("Recording failed or empty")
        return None


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Automated demo driver for hermes-lite")
    parser.add_argument("--fast", action="store_true", help="2x speed")
    parser.add_argument("--speed", type=float, default=1.0, help="Speed multiplier")
    parser.add_argument("--scene", type=int, default=1, help="Start from scene N")
    parser.add_argument("--tui-only", action="store_true", help="TUI scenes only")
    parser.add_argument("--cli-only", action="store_true", help="CLI scenes only")
    parser.add_argument("--record", action="store_true",
                        help="Record to output/hermes-demo.cast (+ .mp4 if agg+ffmpeg available)")
    parser.add_argument("--dry-run", action="store_true", help="Print scene list")
    args = parser.parse_args()

    speed = args.speed
    if args.fast:
        speed = 2.0

    all_scenes = [(i + 1, s, "tui") for i, s in enumerate(SCENES)]
    cli_start = len(SCENES) + 1
    all_scenes += [(cli_start + i, s, "cli") for i, s in enumerate(CLI_SCENES)]

    if args.dry_run:
        print("Demo scenes:")
        for num, scene, mode in all_scenes:
            n_steps = len(scene["steps"])
            sends = sum(1 for s in scene["steps"] if s["type"] == "send")
            waits = sum(1 for s in scene["steps"] if s["type"] == "wait_quiet")
            print(f"  {num:2d}. [{mode.upper():3s}] {scene['title']}")
            print(f"      {n_steps} steps, {sends} commands, {waits} agent waits")
        return

    print("=" * 60, file=sys.stderr)
    print("  hermes-lite Demo Driver (tmux)", file=sys.stderr)
    print(f"  Speed: {speed}x  |  Start: scene {args.scene}  |  Record: {args.record}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    driver = DemoDriver(speed_mult=speed)

    try:
        # TUI scenes
        if not args.cli_only:
            tui_scenes = [(n, s) for n, s, m in all_scenes if m == "tui" and n >= args.scene]
            if tui_scenes:
                driver.start_tui()
                time.sleep(1)

                if args.record:
                    record_session(driver, tui_scenes, os.path.join(_REPO_ROOT, "output"))
                else:
                    for num, scene in tui_scenes:
                        if not driver.run_scene(scene, num):
                            break

                driver.stop()

        # CLI scenes
        if not args.tui_only:
            cli_filtered = [(n, s) for n, s, m in all_scenes if m == "cli" and n >= args.scene]
            if cli_filtered:
                log("Switching to CLI for image paste demos...")
                driver._delay(2)
                driver.start_cli()
                time.sleep(1)

                if args.record:
                    record_session(driver, cli_filtered,
                                   os.path.join(_REPO_ROOT, "output"))
                else:
                    for num, scene in cli_filtered:
                        if not driver.run_scene(scene, num):
                            break

                driver.stop()

    except (KeyboardInterrupt, SystemExit):
        log("Interrupted")
    finally:
        try:
            driver.stop()
        except Exception:
            pass

    print("\nDemo complete!", file=sys.stderr)


if __name__ == "__main__":
    main()
