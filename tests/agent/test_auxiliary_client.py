"""Tests for agent.auxiliary_client — Anthropic-first with local fallback via litellm."""

import os
from unittest.mock import patch, MagicMock

import pytest

from agent.auxiliary_client import (
    get_text_auxiliary_client,
    get_vision_auxiliary_client,
    auxiliary_max_tokens_param,
    LitellmAuxiliaryClient,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip provider env vars so each test starts clean."""
    for key in (
        "ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_KEY",
        "OPENAI_MODEL", "LLM_MODEL", "HERMES_AUX_MODEL",
        "HERMES_LOCAL_AUX_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


class TestGetTextAuxiliaryClient:
    def test_anthropic_key_returns_litellm_client(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client, model = get_text_auxiliary_client()
        assert isinstance(client, LitellmAuxiliaryClient)
        assert model == "claude-haiku-4-5"

    def test_anthropic_key_respects_aux_model_override(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("HERMES_AUX_MODEL", "claude-sonnet-4-5-20250929")
        client, model = get_text_auxiliary_client()
        assert model == "claude-sonnet-4-5-20250929"

    def test_local_endpoint_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8800/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "local")
        client, model = get_text_auxiliary_client()
        assert isinstance(client, LitellmAuxiliaryClient)
        assert "qwen" in model

    def test_returns_none_when_nothing_available(self):
        client, model = get_text_auxiliary_client()
        assert client is None
        assert model is None


class TestGetVisionAuxiliaryClient:
    def test_always_returns_none(self):
        client, model = get_vision_auxiliary_client()
        assert client is None
        assert model is None


class TestAuxiliaryMaxTokensParam:
    def test_returns_max_tokens(self):
        result = auxiliary_max_tokens_param(1024)
        assert result == {"max_tokens": 1024}
