"""Runtime provider resolution for hermes-lite."""

from __future__ import annotations

import os
import socket
from typing import Any, Dict, Optional

from hermes_cli.config import load_config


LOCAL_MODEL_PORTS = {
    "local/qwen3.5-9b": 8800,
}

_LOCAL_MODEL_ALIASES = {
    "local/qwen3.5-9b": "qwen",
}

_managed_server_proc = None


def _get_model_config() -> Dict[str, Any]:
    config = load_config()
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        return dict(model_cfg)
    if isinstance(model_cfg, str) and model_cfg.strip():
        return {"default": model_cfg.strip()}
    return {}


def resolve_requested_provider(requested: Optional[str] = None) -> str:
    if requested and requested.strip():
        return requested.strip().lower()

    env_provider = os.getenv("HERMES_INFERENCE_PROVIDER", "").strip().lower()
    if env_provider:
        return env_provider

    model_cfg = _get_model_config()
    cfg_provider = model_cfg.get("provider")
    if isinstance(cfg_provider, str) and cfg_provider.strip():
        return cfg_provider.strip().lower()

    model_id = model_cfg.get("default", "")
    if isinstance(model_id, str) and model_id.startswith("local/"):
        return "local"

    return "anthropic"


def _local_server_alive(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def _auto_start_local_server(model_id: str, port: int) -> bool:
    global _managed_server_proc

    if _local_server_alive(port):
        return True

    alias = _LOCAL_MODEL_ALIASES.get(model_id)
    if not alias:
        return False

    import atexit
    import signal
    import subprocess
    import sys
    import time

    cmd = [sys.executable, "-m", "local_models.serve", alias]
    print(f"Starting local model server on port {port}...")
    print(f"  $ {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _managed_server_proc = proc
    except Exception as exc:
        print(f"  Failed to start server: {exc}")
        return False

    def _cleanup_server():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    atexit.register(_cleanup_server)
    try:
        previous = signal.getsignal(signal.SIGTERM)

        def _sigterm_handler(signum, frame):
            _cleanup_server()
            if callable(previous) and previous not in (signal.SIG_DFL, signal.SIG_IGN):
                previous(signum, frame)
            raise SystemExit(1)

        signal.signal(signal.SIGTERM, _sigterm_handler)
    except ValueError:
        pass

    print("  Waiting for model to load...", end="", flush=True)
    for i in range(120):
        ret = proc.poll()
        if ret is not None:
            stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            print(f"\n  Server exited with code {ret}")
            if stderr:
                for line in stderr.strip().splitlines()[-5:]:
                    print(f"    {line}")
            return False
        if _local_server_alive(port):
            print(f" ready! (took ~{i // 2}s)")
            return True
        if i % 10 == 0 and i > 0:
            print(".", end="", flush=True)
        time.sleep(0.5)

    print(f"\n  Timed out waiting for server on port {port}")
    return False


def _resolve_local_runtime(*, requested_provider: str = "local") -> Dict[str, Any]:
    model_cfg = _get_model_config()
    model_id = model_cfg.get("default", "local/qwen3.5-9b")
    port = LOCAL_MODEL_PORTS.get(model_id, 8800)

    base_url = str(model_cfg.get("base_url", "")).strip() or os.getenv("OPENAI_BASE_URL", "").strip()
    if not base_url:
        base_url = f"http://127.0.0.1:{port}/v1"

    _auto_start_local_server(model_id, port)

    return {
        "provider": "local",
        "api_mode": "chat_completions",
        "base_url": base_url.rstrip("/"),
        "api_key": os.getenv("OPENAI_API_KEY", "").strip() or "local",
        "source": "local",
        "requested_provider": requested_provider,
    }


def resolve_runtime_provider(
    *,
    requested: Optional[str] = None,
    explicit_api_key: Optional[str] = None,
    explicit_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    requested_provider = resolve_requested_provider(requested)

    if requested_provider == "local":
        return _resolve_local_runtime(requested_provider=requested_provider)

    api_key = explicit_api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    return {
        "provider": "anthropic",
        "api_mode": "chat_completions",
        "base_url": explicit_base_url if explicit_base_url is not None else "",
        "api_key": api_key,
        "source": "env",
        "requested_provider": requested_provider,
    }


def format_runtime_provider_error(error: Exception) -> str:
    return str(error)
