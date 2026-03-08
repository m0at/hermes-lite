"""Local diagnostics for hermes-lite."""

from __future__ import annotations

import os
import shutil
import sys

from dotenv import load_dotenv

from hermes_cli.colors import Colors, color
from hermes_cli.config import ensure_hermes_home, get_env_path, get_hermes_home
from hermes_cli.runtime_provider import _local_server_alive


def _ok(text: str, detail: str = ""):
    print(f"  {color('✓', Colors.GREEN)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))


def _warn(text: str, detail: str = ""):
    print(f"  {color('⚠', Colors.YELLOW)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))


def _fail(text: str, detail: str = ""):
    print(f"  {color('✗', Colors.RED)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))


def run_doctor(_args):
    ensure_hermes_home()
    env_path = get_env_path()
    if env_path.exists():
        load_dotenv(env_path, override=False)

    print()
    print(color("◆ hermes-lite doctor", Colors.CYAN, Colors.BOLD))
    print()
    print(color("◆ Python", Colors.CYAN, Colors.BOLD))
    if sys.version_info >= (3, 11):
        _ok(f"Python {sys.version.split()[0]}")
    else:
        _fail(f"Python {sys.version.split()[0]}", "(3.11+ required)")

    if sys.prefix != sys.base_prefix:
        _ok("Virtual environment active")
    else:
        _warn("Virtual environment not active")

    print()
    print(color("◆ Packages", Colors.CYAN, Colors.BOLD))
    for module, label in [
        ("openai", "OpenAI SDK"),
        ("litellm", "LiteLLM"),
        ("rich", "Rich"),
        ("prompt_toolkit", "prompt_toolkit"),
        ("yaml", "PyYAML"),
    ]:
        try:
            __import__(module)
            _ok(label)
        except ImportError:
            _fail(label, "(missing)")

    print()
    print(color("◆ Runtime", Colors.CYAN, Colors.BOLD))
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        _ok("ANTHROPIC_API_KEY present")
    else:
        _warn("ANTHROPIC_API_KEY not set")

    local_base = os.getenv("OPENAI_BASE_URL", "").strip()
    if local_base:
        _ok("OPENAI_BASE_URL present", f"({local_base})")
    else:
        _warn("OPENAI_BASE_URL not set", "(fine unless you want local models)")

    if _local_server_alive(8800):
        _ok("Local server responding", "(port 8800)")
    else:
        _warn("Local server not running", "(run `hermes-lite-serve qwen` if needed)")

    print()
    print(color("◆ Files", Colors.CYAN, Colors.BOLD))
    home = get_hermes_home()
    _ok("Home directory", str(home))
    _ok(".env file", str(env_path) if env_path.exists() else "(will be created on setup)")
    if shutil.which("rg"):
        _ok("ripgrep available")
    else:
        _warn("ripgrep not found", "(file search falls back to slower shell tools)")
