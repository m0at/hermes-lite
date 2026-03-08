"""Status command for hermes-lite."""

from __future__ import annotations

import os
from pathlib import Path

from hermes_cli.colors import Colors, color
from hermes_cli.config import get_config_path, get_env_path, load_config
from hermes_cli.runtime_provider import LOCAL_MODEL_PORTS, _local_server_alive


def _check(ok: bool) -> str:
    return color("✓", Colors.GREEN) if ok else color("✗", Colors.RED)


def _redact(value: str) -> str:
    if not value:
        return "(not set)"
    if len(value) < 12:
        return "***"
    return value[:4] + "..." + value[-4:]


def show_status(args):
    config = load_config()
    model_cfg = config.get("model", {})
    if isinstance(model_cfg, str):
        model = model_cfg
        provider = "anthropic"
    else:
        model = model_cfg.get("default", "")
        provider = model_cfg.get("provider", "anthropic")

    show_all = getattr(args, "all", False)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openai_base = os.getenv("OPENAI_BASE_URL", "")
    local_port = LOCAL_MODEL_PORTS.get(model, 8800) if model.startswith("local/") else 8800

    print()
    print(color("◆ hermes-lite status", Colors.CYAN, Colors.BOLD))
    print(f"  Config:        {get_config_path()}")
    print(f"  Env file:      {get_env_path()}")
    print(f"  Provider:      {provider}")
    print(f"  Model:         {model}")
    print()
    print(color("◆ Credentials", Colors.CYAN, Colors.BOLD))
    print(f"  Anthropic key: {_check(bool(anthropic_key))} {anthropic_key if show_all else _redact(anthropic_key)}")
    print(f"  Local base:    {openai_base or '(default: auto)'}")
    if provider == "local" or model.startswith("local/"):
        print(f"  Local server:  {_check(_local_server_alive(local_port))} port {local_port}")
    print()
    print(color("◆ Sessions", Colors.CYAN, Colors.BOLD))
    state_db = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes-lite"))) / "state.db"
    print(f"  SQLite DB:     {_check(state_db.exists())} {state_db}")
