"""Tests for agent.tool_prompt_injector module."""

import json
import pytest

from agent.tool_prompt_injector import (
    format_tools_for_prompt,
    inject_tools_into_system_prompt,
    needs_tool_injection,
    format_tool_response,
)

SAMPLE_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_code",
        "description": "Run code",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
}

SAMPLE_TOOL_2 = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file from disk",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}


# --- format_tools_for_prompt ---


class TestFormatToolsForPrompt:
    def test_output_contains_tools_block(self):
        result = format_tools_for_prompt([SAMPLE_TOOL])
        assert "<tools>" in result
        assert "</tools>" in result

    def test_output_contains_tool_json(self):
        result = format_tools_for_prompt([SAMPLE_TOOL])
        assert "execute_code" in result
        assert "Run code" in result

    def test_multiple_tools_listed(self):
        result = format_tools_for_prompt([SAMPLE_TOOL, SAMPLE_TOOL_2])
        assert "execute_code" in result
        assert "read_file" in result

    def test_empty_tools_list(self):
        result = format_tools_for_prompt([])
        # Should produce minimal or empty output, no tool content
        assert "execute_code" not in result

    def test_output_includes_usage_instructions(self):
        result = format_tools_for_prompt([SAMPLE_TOOL])
        # Should contain some guidance on how to invoke a tool call
        lower = result.lower()
        assert any(
            keyword in lower
            for keyword in ["tool_call", "tool call", "function", "invoke", "call"]
        ), f"Expected usage instructions in output, got: {result}"


# --- inject_tools_into_system_prompt ---


class TestInjectToolsIntoSystemPrompt:
    def test_appends_to_existing_prompt(self):
        original = "You are a helpful assistant."
        result = inject_tools_into_system_prompt(original, [SAMPLE_TOOL])
        assert "<tools>" in result
        assert "execute_code" in result
        # Result should be longer than original
        assert len(result) > len(original)

    def test_empty_system_prompt(self):
        result = inject_tools_into_system_prompt("", [SAMPLE_TOOL])
        assert "<tools>" in result
        assert "execute_code" in result

    def test_preserves_original_prompt_content(self):
        original = "You are a helpful assistant. Follow instructions carefully."
        result = inject_tools_into_system_prompt(original, [SAMPLE_TOOL])
        assert original in result


# --- needs_tool_injection ---


class TestNeedsToolInjection:
    def test_local_model_returns_true(self):
        assert needs_tool_injection("local/qwen3.5-9b") is True

    def test_anthropic_model_returns_false(self):
        assert needs_tool_injection("anthropic/claude-sonnet-4") is False

    def test_google_model_returns_false(self):
        assert needs_tool_injection("google/gemini-2.5-flash") is False

    def test_env_var_force_override(self, monkeypatch):
        monkeypatch.setenv("HERMES_FORCE_TOOL_INJECTION", "1")
        # Even a non-local model should return True when env var is set
        assert needs_tool_injection("anthropic/claude-sonnet-4") is True

    def test_env_var_not_set_no_override(self, monkeypatch):
        monkeypatch.delenv("HERMES_FORCE_TOOL_INJECTION", raising=False)
        assert needs_tool_injection("anthropic/claude-sonnet-4") is False


# --- format_tool_response ---


class TestFormatToolResponse:
    def test_correct_xml_output(self):
        result = format_tool_response("call_123", "execute_code", "Hello World")
        assert "<tool_response>" in result
        assert "</tool_response>" in result
        assert "execute_code" in result
        assert "Hello World" in result

    def test_handles_special_characters(self):
        special = '<script>alert("xss")</script> & "quotes" \'apos\''
        result = format_tool_response("call_456", "execute_code", special)
        assert "execute_code" in result
        # The result text must be recoverable from the output
        assert "alert" in result

    def test_empty_result(self):
        result = format_tool_response("call_789", "execute_code", "")
        assert "<tool_response>" in result
        assert "</tool_response>" in result
        assert "execute_code" in result
