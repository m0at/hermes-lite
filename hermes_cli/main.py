#!/usr/bin/env python3
"""Main CLI entrypoint for hermes-lite."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from hermes_cli import __version__
from hermes_cli.config import config_command, ensure_hermes_home, get_env_path
from hermes_cli.doctor import run_doctor
from hermes_cli.setup import run_setup_wizard
from hermes_cli.status import show_status
from hermes_constants import DEFAULT_HERMES_HOME


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
os.environ.setdefault("HERMES_HOME", str(DEFAULT_HERMES_HOME))
os.environ.setdefault("MSWEA_GLOBAL_CONFIG_DIR", os.environ["HERMES_HOME"])
os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")
sys.path.insert(0, str(PROJECT_ROOT))

_user_env = get_env_path()
if _user_env.exists():
    try:
        load_dotenv(dotenv_path=_user_env, encoding="utf-8")
    except UnicodeDecodeError:
        load_dotenv(dotenv_path=_user_env, encoding="latin-1")
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)


def _has_any_provider_configured() -> bool:
    if os.getenv("ANTHROPIC_API_KEY"):
        return True
    if os.getenv("OPENAI_BASE_URL"):
        return True
    return False


def _resolve_last_cli_session() -> Optional[str]:
    try:
        try:
            from hermes_rs import RustSessionDB as SessionDB
        except ImportError:
            from hermes_state import SessionDB

        db = SessionDB()
        sessions = db.search_sessions(source="cli", limit=1)
        db.close()
        if sessions:
            return sessions[0]["id"]
    except Exception:
        pass
    return None


def cmd_chat(args):
    if getattr(args, "continue_last", False) and not getattr(args, "resume", None):
        last_id = _resolve_last_cli_session()
        if not last_id:
            print("No previous CLI session found to continue.")
            sys.exit(1)
        args.resume = last_id

    if not _has_any_provider_configured():
        print()
        print("No runtime is configured yet.")
        print("Run:  hermes-lite setup")
        print()
        sys.exit(1)

    from cli import main as cli_main

    kwargs = {
        "model": args.model,
        "provider": getattr(args, "provider", None),
        "toolsets": args.toolsets,
        "verbose": args.verbose,
        "query": args.query,
        "resume": getattr(args, "resume", None),
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    cli_main(**kwargs)


def cmd_setup(args):
    run_setup_wizard(args)


def cmd_model(args):
    from hermes_cli.config import load_config, save_config, save_env_value
    from hermes_cli.models import ANTHROPIC_MODELS, LOCAL_MODELS

    config = load_config()
    current_model = config.get("model", {})
    if isinstance(current_model, str):
        current_default = current_model
        current_provider = "anthropic"
    else:
        current_default = current_model.get("default", "")
        current_provider = current_model.get("provider", "anthropic")

    print()
    print(f"Current provider: {current_provider}")
    print(f"Current model:    {current_default}")
    print()
    print("1. Anthropic")
    print("2. Local")
    print("3. Cancel")

    try:
        provider_choice = input("Choose provider [1-3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if provider_choice in {"", "3"}:
        print("No change.")
        return

    if provider_choice == "1":
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not anthropic_key:
            try:
                anthropic_key = input("Anthropic API key: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not anthropic_key:
                print("Cancelled.")
                return
            save_env_value("ANTHROPIC_API_KEY", anthropic_key)

        print()
        for idx, (model_id, desc) in enumerate(ANTHROPIC_MODELS, start=1):
            suffix = f" ({desc})" if desc else ""
            print(f"{idx}. {model_id}{suffix}")
        try:
            raw = input(f"Model [1-{len(ANTHROPIC_MODELS)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            choice = int(raw or "1") - 1
        except ValueError:
            choice = 0
        model_id = ANTHROPIC_MODELS[max(0, min(choice, len(ANTHROPIC_MODELS) - 1))][0]
        config["model"] = {"default": model_id, "provider": "anthropic", "base_url": ""}
        save_config(config)
        print(f"Saved: anthropic / {model_id}")
        return

    if provider_choice == "2":
        model_id = LOCAL_MODELS[0][0]
        config["model"] = {
            "default": model_id,
            "provider": "local",
            "base_url": "http://127.0.0.1:8800/v1",
        }
        save_config(config)
        save_env_value("OPENAI_BASE_URL", "http://127.0.0.1:8800/v1")
        save_env_value("OPENAI_API_KEY", "local")
        print(f"Saved: local / {model_id}")
        print("Run `hermes-lite-serve qwen` when you want to start the local server.")
        return

    print("No change.")


def cmd_status(args):
    show_status(args)


def cmd_doctor(args):
    run_doctor(args)


def cmd_version(_args):
    print(f"hermes-lite {__version__}")


def cmd_config(args):
    config_command(args)


def cmd_serve(args):
    from local_models.serve import main as serve_main

    sys.argv = ["hermes-lite-serve", *args.serve_args]
    serve_main()


def main():
    parser = argparse.ArgumentParser(
        prog="hermes-lite",
        description="hermes-lite: a local coding-agent CLI with Anthropic-first runtime",
    )
    parser.add_argument("--version", "-V", action="store_true", help="Show version and exit")
    parser.add_argument("-m", "--model", default=None, help="Model to use")
    parser.add_argument(
        "--provider",
        choices=["anthropic", "local"],
        default=None,
        help="Inference provider (shortcut for `hermes-lite chat --provider ...`)",
    )
    parser.add_argument("--resume", "-r", metavar="SESSION_ID", default=None, help="Resume a previous session")
    parser.add_argument(
        "--continue",
        "-c",
        dest="continue_last",
        action="store_true",
        default=False,
        help="Resume the most recent CLI session",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    chat_parser = subparsers.add_parser("chat", help="Interactive chat with the agent")
    chat_parser.add_argument("-q", "--query", help="Single query (non-interactive mode)")
    chat_parser.add_argument("-m", "--model", help="Model to use")
    chat_parser.add_argument("-t", "--toolsets", help="Comma-separated toolsets to enable")
    chat_parser.add_argument("--provider", choices=["anthropic", "local"], default=None)
    chat_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    chat_parser.add_argument("--resume", "-r", metavar="SESSION_ID")
    chat_parser.add_argument("--continue", "-c", dest="continue_last", action="store_true", default=False)
    chat_parser.set_defaults(func=cmd_chat)

    setup_parser = subparsers.add_parser("setup", help="Interactive setup wizard")
    setup_parser.set_defaults(func=cmd_setup)

    model_parser = subparsers.add_parser("model", help="Select default provider and model")
    model_parser.set_defaults(func=cmd_model)

    config_parser = subparsers.add_parser("config", help="View or edit configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_subparsers.add_parser("edit", help="Open config in $EDITOR")
    set_parser = config_subparsers.add_parser("set", help="Set a config value")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    config_subparsers.add_parser("check", help="Check for missing config")
    config_subparsers.add_parser("migrate", help="Migrate missing config")
    config_parser.set_defaults(func=cmd_config)

    status_parser = subparsers.add_parser("status", help="Show runtime/config status")
    status_parser.add_argument("--all", action="store_true")
    status_parser.set_defaults(func=cmd_status)

    doctor_parser = subparsers.add_parser("doctor", help="Run local diagnostics")
    doctor_parser.set_defaults(func=cmd_doctor)

    serve_parser = subparsers.add_parser("serve", help="Start the optional local model server")
    serve_parser.add_argument("serve_args", nargs=argparse.REMAINDER)
    serve_parser.set_defaults(func=cmd_serve)

    version_parser = subparsers.add_parser("version", help="Show version")
    version_parser.set_defaults(func=cmd_version)

    args = parser.parse_args()

    if args.version:
        cmd_version(args)
        return

    ensure_hermes_home()

    if (args.resume or args.continue_last or args.provider or args.model) and args.command is None:
        args.command = "chat"
        args.func = cmd_chat

    if args.command is None:
        args.command = "chat"
        args.func = cmd_chat

    args.func(args)


if __name__ == "__main__":
    main()
