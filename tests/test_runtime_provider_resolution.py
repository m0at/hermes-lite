"""Tests for hermes_cli.runtime_provider — Anthropic-first + local resolution."""

from hermes_cli import runtime_provider as rp


def test_resolve_requested_provider_defaults_to_anthropic(monkeypatch):
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setattr(rp, "_get_model_config", lambda: {})
    assert rp.resolve_requested_provider() == "anthropic"


def test_resolve_requested_provider_explicit(monkeypatch):
    assert rp.resolve_requested_provider("local") == "local"


def test_resolve_requested_provider_env_override(monkeypatch):
    monkeypatch.setenv("HERMES_INFERENCE_PROVIDER", "local")
    monkeypatch.setattr(rp, "_get_model_config", lambda: {})
    assert rp.resolve_requested_provider() == "local"


def test_resolve_requested_provider_config(monkeypatch):
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setattr(rp, "_get_model_config", lambda: {"provider": "local"})
    assert rp.resolve_requested_provider() == "local"


def test_resolve_runtime_provider_anthropic(monkeypatch):
    monkeypatch.setattr(rp, "_get_model_config", lambda: {"provider": "anthropic"})
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    resolved = rp.resolve_runtime_provider()

    assert resolved["provider"] == "anthropic"
    assert resolved["api_key"] == "sk-ant-test"
    assert resolved["base_url"] == ""


def test_resolve_runtime_provider_anthropic_no_key(monkeypatch):
    monkeypatch.setattr(rp, "_get_model_config", lambda: {"provider": "anthropic"})
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    try:
        rp.resolve_runtime_provider()
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass


def test_resolve_runtime_provider_local(monkeypatch):
    monkeypatch.setattr(rp, "_get_model_config", lambda: {"provider": "local", "default": "local/qwen3.5-9b"})
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8800/v1")
    monkeypatch.setattr(rp, "_auto_start_local_server", lambda *a, **k: True)

    resolved = rp.resolve_runtime_provider(requested="local")

    assert resolved["provider"] == "local"
    assert "127.0.0.1" in resolved["base_url"]


def test_resolve_runtime_provider_explicit_overrides(monkeypatch):
    monkeypatch.setattr(rp, "_get_model_config", lambda: {})
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    resolved = rp.resolve_runtime_provider(
        explicit_api_key="my-key",
        explicit_base_url="https://custom.example/v1",
    )

    assert resolved["api_key"] == "my-key"
    assert resolved["base_url"] == "https://custom.example/v1"
