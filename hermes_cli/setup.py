"""Interactive setup wizard for hermes-lite."""

from __future__ import annotations

import sys

from hermes_cli.colors import Colors, color
from hermes_cli.config import (
    DEFAULT_CONFIG,
    ensure_hermes_home,
    get_env_value,
    load_config,
    save_config,
    save_env_value,
)
from hermes_cli.models import ANTHROPIC_MODELS


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        return input(color(f"{text}{suffix}: ", Colors.YELLOW)).strip() or default
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)


def _prompt_yes_no(text: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    while True:
        value = _prompt(f"{text} [{default_str}]").lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False


def run_setup_wizard(_args=None):
    ensure_hermes_home()
    config = load_config()
    if not config:
        config = DEFAULT_CONFIG.copy()

    print()
    print(color("◆ hermes-lite setup", Colors.CYAN, Colors.BOLD))
    print(color("Config home: ~/.hermes-lite", Colors.DIM))
    print()

    if _prompt_yes_no("Use Anthropic as the default runtime?", default=True):
        key = get_env_value("ANTHROPIC_API_KEY") or ""
        if not key:
            key = _prompt("Anthropic API key")
            if key:
                save_env_value("ANTHROPIC_API_KEY", key)

        print()
        for idx, (model_id, desc) in enumerate(ANTHROPIC_MODELS, start=1):
            suffix = f" ({desc})" if desc else ""
            print(f"  {idx}. {model_id}{suffix}")
        raw_choice = _prompt("Choose default model", "1")
        try:
            idx = max(1, min(int(raw_choice), len(ANTHROPIC_MODELS))) - 1
        except ValueError:
            idx = 0
        model_id = ANTHROPIC_MODELS[idx][0]
        config["model"] = {"default": model_id, "provider": "anthropic", "base_url": ""}
    else:
        config["model"] = {
            "default": "local/qwen3.5-9b",
            "provider": "local",
            "base_url": "http://127.0.0.1:8800/v1",
        }
        save_env_value("OPENAI_BASE_URL", "http://127.0.0.1:8800/v1")
        save_env_value("OPENAI_API_KEY", "local")

    config["toolsets"] = ["hermes-lite-cli"]
    save_config(config)

    print()
    print(color("✓ Setup complete", Colors.GREEN))
    print("  Run: hermes-lite")
    print("  Optional local model: hermes-lite-serve qwen")
