"""Tests for agent/model_capabilities.py — capability detection, tool adapter
decisions, env var overrides, and provider-aware routing.

Coverage:
  ModelCapabilities defaults   — verify dataclass field defaults
  detect_capabilities          — known models, cloud providers, local models
  needs_tool_adapter           — local vs cloud, env var override
  Provider-aware routing       — openrouter qwen, localhost base_url
  Env var override             — HERMES_FORCE_TOOL_INJECTION
"""

import pytest

from agent.model_capabilities import (
    ModelCapabilities,
    detect_capabilities,
    needs_tool_adapter,
)


# =========================================================================
# ModelCapabilities defaults
# =========================================================================

class TestModelCapabilitiesDefaults:
    def test_default_supports_tools(self):
        caps = ModelCapabilities()
        assert caps.supports_tools is True

    def test_default_supports_vision(self):
        caps = ModelCapabilities()
        assert caps.supports_vision is False

    def test_default_supports_streaming(self):
        caps = ModelCapabilities()
        assert caps.supports_streaming is True

    def test_default_tool_call_format(self):
        caps = ModelCapabilities()
        assert caps.tool_call_format == "native"

    def test_default_max_tools(self):
        caps = ModelCapabilities()
        assert caps.max_tools == 0


# =========================================================================
# detect_capabilities — local/qwen3.5-9b
# =========================================================================

class TestLocalQwen:
    def test_supports_tools_false(self):
        caps = detect_capabilities("local/qwen3.5-9b")
        assert caps.supports_tools is False

    def test_tool_call_format_xml(self):
        caps = detect_capabilities("local/qwen3.5-9b")
        assert caps.tool_call_format == "xml"

    def test_supports_vision(self):
        caps = detect_capabilities("local/qwen3.5-9b")
        assert caps.supports_vision is True

    def test_supports_streaming(self):
        caps = detect_capabilities("local/qwen3.5-9b")
        assert caps.supports_streaming is True


# =========================================================================
# detect_capabilities — anthropic/claude-sonnet-4
# =========================================================================

class TestClaudeSonnet:
    def test_supports_tools(self):
        caps = detect_capabilities("claude-sonnet-4")
        assert caps.supports_tools is True

    def test_tool_call_format_native(self):
        caps = detect_capabilities("claude-sonnet-4")
        assert caps.tool_call_format == "native"

    def test_supports_vision(self):
        caps = detect_capabilities("claude-sonnet-4")
        assert caps.supports_vision is True

    def test_with_provider_prefix(self):
        # "anthropic/claude-sonnet-4" doesn't match "claude-" prefix,
        # but defaults still have supports_tools=True
        caps = detect_capabilities("anthropic/claude-sonnet-4")
        assert caps.supports_tools is True
        assert caps.tool_call_format == "native"


# =========================================================================
# detect_capabilities — openai/gpt-4o
# =========================================================================

class TestGpt4o:
    def test_supports_tools(self):
        caps = detect_capabilities("openai/gpt-4o")
        # gpt-4o doesn't start with "gpt-4" when it has the "openai/" prefix,
        # but the default is supports_tools=True anyway
        assert caps.supports_tools is True

    def test_gpt4o_without_prefix(self):
        caps = detect_capabilities("gpt-4o")
        assert caps.supports_tools is True
        assert caps.tool_call_format == "native"
        assert caps.supports_vision is True


# =========================================================================
# detect_capabilities — google/gemini-2.5-flash
# =========================================================================

class TestGeminiFlash:
    def test_supports_tools(self):
        caps = detect_capabilities("gemini-2.5-flash")
        assert caps.supports_tools is True

    def test_tool_call_format_native(self):
        caps = detect_capabilities("gemini-2.5-flash")
        assert caps.tool_call_format == "native"

    def test_supports_vision(self):
        caps = detect_capabilities("gemini-2.5-flash")
        assert caps.supports_vision is True

    def test_via_openrouter(self):
        caps = detect_capabilities(
            "google/gemini-2.5-flash",
            base_url="https://openrouter.ai/api/v1",
        )
        assert caps.supports_tools is True
        assert caps.tool_call_format == "native"


# =========================================================================
# detect_capabilities — unknown model
# =========================================================================

class TestUnknownModel:
    def test_sensible_defaults(self):
        caps = detect_capabilities("completely-unknown-model-xyz")
        assert caps.supports_tools is True
        assert caps.tool_call_format == "native"
        assert caps.supports_streaming is True
        assert caps.max_tools == 0


# =========================================================================
# needs_tool_adapter — local vs cloud
# =========================================================================

class TestNeedsToolAdapter:
    def test_true_for_local_model(self):
        assert needs_tool_adapter("local/qwen3.5-9b") is True

    def test_true_for_bare_qwen(self):
        assert needs_tool_adapter("qwen2.5-coder-32b") is True

    def test_false_for_claude(self):
        assert needs_tool_adapter("claude-sonnet-4") is False

    def test_false_for_gpt4(self):
        assert needs_tool_adapter("gpt-4o") is False

    def test_false_for_gemini(self):
        assert needs_tool_adapter("gemini-2.5-flash") is False

    def test_false_for_unknown(self):
        # Unknown models default to supports_tools=True
        assert needs_tool_adapter("some-random-model") is False


# =========================================================================
# HERMES_FORCE_TOOL_INJECTION env var
# =========================================================================

class TestForceToolInjection:
    def test_force_injection_true(self, monkeypatch):
        monkeypatch.setenv("HERMES_FORCE_TOOL_INJECTION", "1")
        caps = detect_capabilities("claude-sonnet-4")
        assert caps.supports_tools is False
        assert caps.tool_call_format == "xml"

    def test_force_injection_yes(self, monkeypatch):
        monkeypatch.setenv("HERMES_FORCE_TOOL_INJECTION", "yes")
        caps = detect_capabilities("gpt-4o")
        assert caps.supports_tools is False

    def test_force_injection_TRUE_uppercase(self, monkeypatch):
        monkeypatch.setenv("HERMES_FORCE_TOOL_INJECTION", "TRUE")
        caps = detect_capabilities("gemini-2.5-flash")
        assert caps.supports_tools is False

    def test_force_injection_false_value(self, monkeypatch):
        monkeypatch.setenv("HERMES_FORCE_TOOL_INJECTION", "0")
        caps = detect_capabilities("claude-sonnet-4")
        assert caps.supports_tools is True

    def test_force_injection_empty(self, monkeypatch):
        monkeypatch.setenv("HERMES_FORCE_TOOL_INJECTION", "")
        caps = detect_capabilities("claude-sonnet-4")
        assert caps.supports_tools is True

    def test_force_injection_unset(self, monkeypatch):
        monkeypatch.delenv("HERMES_FORCE_TOOL_INJECTION", raising=False)
        caps = detect_capabilities("claude-sonnet-4")
        assert caps.supports_tools is True

    def test_needs_tool_adapter_with_force(self, monkeypatch):
        monkeypatch.setenv("HERMES_FORCE_TOOL_INJECTION", "1")
        assert needs_tool_adapter("claude-sonnet-4") is True


# =========================================================================
# base_url with localhost — may indicate local model
# =========================================================================

class TestLocalhostBaseUrl:
    def test_localhost_does_not_override_model_caps(self):
        # A cloud model name with localhost base_url: model caps apply,
        # but no _NATIVE_PROVIDERS match overrides them
        caps = detect_capabilities("claude-sonnet-4", base_url="http://localhost:8080/v1")
        assert caps.supports_tools is True  # matched by "claude-" prefix

    def test_unknown_model_on_localhost(self):
        # Unknown model on localhost gets defaults (supports_tools=True)
        caps = detect_capabilities("my-custom-finetune", base_url="http://localhost:11434")
        assert caps.supports_tools is True
        assert caps.tool_call_format == "native"

    def test_qwen_on_localhost_no_native_override(self):
        # Qwen on localhost without a native provider URL stays xml
        caps = detect_capabilities("qwen2.5-coder", base_url="http://localhost:11434")
        assert caps.supports_tools is False
        assert caps.tool_call_format == "xml"


# =========================================================================
# Various local model patterns
# =========================================================================

class TestLocalModelPatterns:
    def test_local_prefix_anything(self):
        caps = detect_capabilities("local/anything-at-all")
        assert caps.supports_tools is False
        assert caps.tool_call_format == "xml"
        assert caps.supports_vision is True

    def test_local_prefix_case_sensitivity(self):
        # Module lowercases, so "Local/" should still match "local/"
        caps = detect_capabilities("Local/my-model")
        assert caps.supports_tools is False

    def test_qwen_prefix_matches(self):
        caps = detect_capabilities("qwen2.5-72b-instruct")
        assert caps.supports_tools is False
        assert caps.tool_call_format == "xml"

    def test_qwen_in_name_but_not_prefix(self):
        # "some-qwen-model" does NOT start with "qwen", so defaults apply
        caps = detect_capabilities("some-qwen-model")
        assert caps.supports_tools is True


# =========================================================================
# OpenRouter Qwen — server-side tool support
# =========================================================================

class TestOpenRouterQwen:
    def test_qwen_on_openrouter_supports_tools(self):
        caps = detect_capabilities(
            "qwen/qwen3-coder",
            base_url="https://openrouter.ai/api/v1",
        )
        assert caps.supports_tools is True
        assert caps.tool_call_format == "native"

    def test_qwen_on_openrouter_overrides_xml(self):
        # Without openrouter, qwen would be xml
        caps_local = detect_capabilities("qwen/qwen3-coder")
        assert caps_local.supports_tools is False
        assert caps_local.tool_call_format == "xml"

        # With openrouter, server handles it
        caps_or = detect_capabilities(
            "qwen/qwen3-coder",
            base_url="https://openrouter.ai/api/v1",
        )
        assert caps_or.supports_tools is True

    def test_qwen_on_groq_supports_tools(self):
        caps = detect_capabilities(
            "qwen-2.5-32b",
            base_url="https://api.groq.com/openai/v1",
        )
        assert caps.supports_tools is True
        assert caps.tool_call_format == "native"


# =========================================================================
# Cloud provider base_url overrides
# =========================================================================

class TestCloudProviderOverrides:
    def test_openrouter_forces_native(self):
        caps = detect_capabilities("local/my-model", base_url="https://openrouter.ai/api/v1")
        assert caps.supports_tools is True
        assert caps.tool_call_format == "native"

    def test_anthropic_in_url(self):
        caps = detect_capabilities("claude-sonnet-4", base_url="https://api.anthropic.com/v1")
        assert caps.supports_tools is True

    def test_openai_in_url(self):
        caps = detect_capabilities("gpt-4o", base_url="https://api.openai.com/v1")
        assert caps.supports_tools is True

    def test_groq_in_url(self):
        caps = detect_capabilities("llama-3-70b", base_url="https://api.groq.com/openai/v1")
        assert caps.supports_tools is True
