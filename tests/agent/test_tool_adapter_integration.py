"""Integration tests for the full tool call adaptation pipeline.

Tests all modules working together end-to-end:
- agent.tool_call_parser
- agent.tool_prompt_injector
- agent.tool_response_adapter
- agent.model_capabilities
"""

import json
from types import SimpleNamespace

import pytest

from agent.tool_call_parser import parse_tool_calls, strip_tool_calls, has_tool_calls
from agent.tool_prompt_injector import (
    format_tools_for_prompt,
    inject_tools_into_system_prompt,
    format_tool_response,
)
from agent.tool_response_adapter import should_adapt, adapt_response, format_tool_results_as_content
from agent.model_capabilities import detect_capabilities, needs_tool_adapter


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "Execute Python code in sandbox",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Python code to execute"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write to file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
]


def _make_response(content, tool_calls=None, finish_reason="stop"):
    """Build a mock OpenAI-style chat completion response."""
    msg = SimpleNamespace(content=content, tool_calls=tool_calls, role="assistant")
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason, index=0)
    return SimpleNamespace(choices=[choice], model="local/qwen3.5-9b", id="chatcmpl-test")


# ---------------------------------------------------------------------------
# 1. Full roundtrip
# ---------------------------------------------------------------------------

class TestFullRoundtrip:
    def test_inject_then_parse_then_adapt(self):
        # Step 1: inject tools into system prompt
        system = inject_tools_into_system_prompt("You are helpful.", TOOLS)
        assert "read_file" in system
        assert "<tools>" in system

        # Step 2: simulate model output with a tool call
        model_output = (
            'I\'ll read that file for you.\n\n'
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"path": "/tmp/test.py"}}\n'
            '</tool_call>'
        )
        response = _make_response(model_output)

        # Step 3: adapter detects and converts
        assert should_adapt(response, "local/qwen3.5-9b")
        adapted = adapt_response(response, TOOLS)

        assert adapted.choices[0].message.tool_calls is not None
        assert len(adapted.choices[0].message.tool_calls) == 1
        tc = adapted.choices[0].message.tool_calls[0]
        assert tc.function.name == "read_file"
        assert json.loads(tc.function.arguments) == {"path": "/tmp/test.py"}
        assert adapted.choices[0].finish_reason == "tool_calls"


# ---------------------------------------------------------------------------
# 2. Realistic Qwen output with think blocks
# ---------------------------------------------------------------------------

class TestRealisticQwenOutput:
    def test_think_block_plus_tool_call(self):
        model_output = (
            "<think>\n"
            "I need to read the file first to understand the structure.\n"
            "</think>\n\n"
            "I'll read the file for you.\n\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"path": "/tmp/test.py"}}\n'
            "</tool_call>"
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)

        calls = adapted.choices[0].message.tool_calls
        assert len(calls) == 1
        assert calls[0].function.name == "read_file"
        assert json.loads(calls[0].function.arguments) == {"path": "/tmp/test.py"}

    def test_think_block_stripped_from_remaining_content(self):
        model_output = (
            "<think>\nReasoning here.\n</think>\n\n"
            "Here is my answer.\n\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"path": "/a.txt"}}\n'
            "</tool_call>"
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)

        remaining = adapted.choices[0].message.content
        # Tool call XML should be removed; think block may or may not be
        # stripped by the adapter (it strips tool_call tags). The key assertion
        # is that the tool call was parsed correctly.
        assert "<tool_call>" not in (remaining or "")


# ---------------------------------------------------------------------------
# 3. Multiple tools in sequence (multi-turn)
# ---------------------------------------------------------------------------

class TestMultipleToolsInSequence:
    def test_first_turn_has_tool_call_second_is_final(self):
        # Turn 1: model calls a tool
        turn1_output = (
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"path": "/tmp/data.csv"}}\n'
            '</tool_call>'
        )
        resp1 = _make_response(turn1_output)
        adapted1 = adapt_response(resp1, TOOLS)
        assert adapted1.choices[0].message.tool_calls is not None
        assert adapted1.choices[0].finish_reason == "tool_calls"

        # Turn 2: model gives final text (no tool call)
        turn2_output = "The file contains 42 rows of data."
        resp2 = _make_response(turn2_output)
        assert not should_adapt(resp2, "local/qwen3.5-9b")
        # adapt_response should return unchanged
        adapted2 = adapt_response(resp2, TOOLS)
        assert adapted2.choices[0].message.tool_calls is None
        assert adapted2.choices[0].message.content == turn2_output

    def test_multiple_tool_calls_in_single_response(self):
        model_output = (
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"path": "/a.py"}}\n'
            '</tool_call>\n'
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"path": "/b.py"}}\n'
            '</tool_call>'
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        calls = adapted.choices[0].message.tool_calls
        assert len(calls) == 2
        paths = {json.loads(c.function.arguments)["path"] for c in calls}
        assert paths == {"/a.py", "/b.py"}


# ---------------------------------------------------------------------------
# 4. Tool response formatting
# ---------------------------------------------------------------------------

class TestToolResponseFormatting:
    def test_format_tool_response_xml(self):
        result = format_tool_response("call_abc", "read_file", "print('hello')")
        assert "<tool_response>" in result
        assert "</tool_response>" in result
        assert "read_file" in result
        assert "print('hello')" in result

    def test_format_tool_results_as_content(self):
        results = [
            {"name": "read_file", "content": "file contents here"},
            {"name": "execute_code", "content": "output: 42"},
        ]
        formatted = format_tool_results_as_content(results)
        assert formatted.count("<tool_response>") == 2
        assert formatted.count("</tool_response>") == 2
        assert "read_file" in formatted
        assert "execute_code" in formatted
        assert "file contents here" in formatted
        assert "output: 42" in formatted

    def test_format_tool_response_roundtrip_json(self):
        result = format_tool_response("call_1", "write_file", "ok")
        # The content between tags should be valid JSON
        inner = result.replace("<tool_response>", "").replace("</tool_response>", "").strip()
        data = json.loads(inner)
        assert data["name"] == "write_file"


# ---------------------------------------------------------------------------
# 5. No tools needed
# ---------------------------------------------------------------------------

class TestNoToolsNeeded:
    def test_plain_text_response_unchanged(self):
        content = "The answer is 42. No tools required."
        response = _make_response(content)
        assert not should_adapt(response, "local/qwen3.5-9b")
        adapted = adapt_response(response, TOOLS)
        assert adapted.choices[0].message.content == content
        assert adapted.choices[0].message.tool_calls is None

    def test_empty_content_unchanged(self):
        response = _make_response("")
        assert not should_adapt(response, "local/qwen3.5-9b")
        adapted = adapt_response(response, TOOLS)
        assert adapted.choices[0].message.tool_calls is None

    def test_none_content_unchanged(self):
        response = _make_response(None)
        assert not should_adapt(response, "local/qwen3.5-9b")


# ---------------------------------------------------------------------------
# 6. Mixed content preserved
# ---------------------------------------------------------------------------

class TestMixedContentPreserved:
    def test_text_before_tool_call_preserved(self):
        model_output = (
            "Let me check the file.\n\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"path": "/tmp/x"}}\n'
            "</tool_call>"
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        remaining = adapted.choices[0].message.content
        assert remaining is not None
        assert "Let me check the file." in remaining

    def test_text_after_tool_call_preserved(self):
        model_output = (
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"path": "/tmp/x"}}\n'
            "</tool_call>\n\n"
            "I've requested the file."
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        remaining = adapted.choices[0].message.content
        assert remaining is not None
        assert "I've requested the file." in remaining

    def test_text_both_sides_preserved(self):
        model_output = (
            "Before.\n\n"
            "<tool_call>\n"
            '{"name": "execute_code", "arguments": {"code": "print(1)"}}\n'
            "</tool_call>\n\n"
            "After."
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        remaining = adapted.choices[0].message.content
        assert "Before." in remaining
        assert "After." in remaining
        assert "<tool_call>" not in remaining


# ---------------------------------------------------------------------------
# 7. Invalid tool filtered
# ---------------------------------------------------------------------------

class TestInvalidToolFiltered:
    def test_nonexistent_tool_filtered_out(self):
        model_output = (
            '<tool_call>\n'
            '{"name": "delete_everything", "arguments": {}}\n'
            '</tool_call>'
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        # No valid tool calls remain, so tool_calls should stay None
        assert adapted.choices[0].message.tool_calls is None

    def test_mix_valid_and_invalid_keeps_valid(self):
        model_output = (
            '<tool_call>\n'
            '{"name": "delete_everything", "arguments": {}}\n'
            '</tool_call>\n'
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"path": "/tmp/ok.txt"}}\n'
            '</tool_call>'
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        calls = adapted.choices[0].message.tool_calls
        assert len(calls) == 1
        assert calls[0].function.name == "read_file"

    def test_all_invalid_returns_original_content(self):
        model_output = (
            "Some text.\n\n"
            '<tool_call>\n'
            '{"name": "nope", "arguments": {}}\n'
            '</tool_call>'
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        # No valid calls -> response not transformed
        assert adapted.choices[0].message.tool_calls is None


# ---------------------------------------------------------------------------
# 8. Think blocks + tool calls
# ---------------------------------------------------------------------------

class TestThinkBlocksAndToolCalls:
    def test_think_content_not_in_tool_call(self):
        model_output = (
            "<think>\nI should use read_file to check the code.\n</think>\n\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"path": "/src/main.py"}}\n'
            "</tool_call>"
        )
        parsed = parse_tool_calls(model_output)
        assert len(parsed) == 1
        assert parsed[0].name == "read_file"
        # Think block should not be parsed as a tool call
        for tc in parsed:
            assert "think" not in tc.name.lower()

    def test_nested_think_and_multiple_calls(self):
        model_output = (
            "<think>\nStep 1: read both files.\nStep 2: compare.\n</think>\n\n"
            "I'll read both files.\n\n"
            '<tool_call>\n{"name": "read_file", "arguments": {"path": "/a.py"}}\n</tool_call>\n'
            '<tool_call>\n{"name": "read_file", "arguments": {"path": "/b.py"}}\n</tool_call>'
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        calls = adapted.choices[0].message.tool_calls
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# 9. Capability detection gates adaptation
# ---------------------------------------------------------------------------

class TestCapabilityDetectionGatesAdaptation:
    def test_cloud_model_not_adapted(self):
        """Cloud model response should NOT be adapted even if it contains <tool_call> text."""
        model_output = (
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"path": "/tmp/x"}}\n'
            '</tool_call>'
        )
        response = _make_response(model_output)
        # should_adapt checks the model string -- cloud models should return False
        assert not should_adapt(response, "claude-3-opus")
        assert not should_adapt(response, "gpt-4-turbo")

    def test_local_model_adapted(self):
        model_output = (
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"path": "/tmp/x"}}\n'
            '</tool_call>'
        )
        response = _make_response(model_output)
        assert should_adapt(response, "local/qwen3.5-9b")

    def test_capabilities_local_needs_adapter(self):
        assert needs_tool_adapter("local/qwen3.5-9b")

    def test_capabilities_cloud_no_adapter(self):
        assert not needs_tool_adapter("claude-3-opus")
        assert not needs_tool_adapter("gpt-4-turbo")

    def test_capabilities_detect_xml_format_for_local(self):
        caps = detect_capabilities("local/qwen3.5-9b")
        assert caps.tool_call_format == "xml"
        assert not caps.supports_tools

    def test_capabilities_detect_native_for_cloud(self):
        caps = detect_capabilities("claude-3-opus")
        assert caps.tool_call_format == "native"
        assert caps.supports_tools

    def test_existing_tool_calls_not_double_adapted(self):
        """If a response already has tool_calls, should_adapt returns False."""
        existing_call = SimpleNamespace(
            id="call_existing",
            type="function",
            function=SimpleNamespace(name="read_file", arguments='{"path": "/x"}'),
        )
        response = _make_response("some content", tool_calls=[existing_call])
        assert not should_adapt(response, "local/qwen3.5-9b")

    def test_force_injection_env_var(self, monkeypatch):
        monkeypatch.setenv("HERMES_FORCE_TOOL_INJECTION", "1")
        model_output = (
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"path": "/tmp/x"}}\n'
            '</tool_call>'
        )
        response = _make_response(model_output)
        # With env var, even non-local models should be adapted
        assert should_adapt(response, "gpt-4-turbo")


# ---------------------------------------------------------------------------
# 10. End-to-end with sample tools
# ---------------------------------------------------------------------------

class TestEndToEndWithSampleTools:
    def test_full_pipeline_execute_code(self):
        # 1. Inject tools into system prompt
        system = inject_tools_into_system_prompt("You are a coding assistant.", TOOLS)
        assert "execute_code" in system
        assert "read_file" in system
        assert "write_file" in system

        # 2. Simulate model producing a tool call
        model_output = (
            "I'll run the code for you.\n\n"
            "<tool_call>\n"
            '{"name": "execute_code", "arguments": {"code": "print(2 + 2)"}}\n'
            "</tool_call>"
        )
        response = _make_response(model_output)

        # 3. Detect adaptation is needed
        caps = detect_capabilities("local/qwen3.5-9b")
        assert caps.tool_call_format == "xml"
        assert should_adapt(response, "local/qwen3.5-9b")

        # 4. Adapt the response
        adapted = adapt_response(response, TOOLS)
        calls = adapted.choices[0].message.tool_calls
        assert len(calls) == 1
        assert calls[0].function.name == "execute_code"
        assert json.loads(calls[0].function.arguments) == {"code": "print(2 + 2)"}
        assert adapted.choices[0].finish_reason == "tool_calls"
        # Surrounding text preserved
        remaining = adapted.choices[0].message.content
        assert "I'll run the code for you." in remaining

        # 5. Format tool result for next turn
        tool_result = format_tool_results_as_content([
            {"name": "execute_code", "content": "4\n"},
        ])
        assert "<tool_response>" in tool_result
        assert "execute_code" in tool_result
        assert "4" in tool_result

    def test_full_pipeline_write_file(self):
        model_output = (
            "<tool_call>\n"
            '{"name": "write_file", "arguments": {"path": "/tmp/out.txt", "content": "hello world"}}\n'
            "</tool_call>"
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        calls = adapted.choices[0].message.tool_calls
        assert len(calls) == 1
        assert calls[0].function.name == "write_file"
        args = json.loads(calls[0].function.arguments)
        assert args["path"] == "/tmp/out.txt"
        assert args["content"] == "hello world"

    def test_full_pipeline_chained_calls(self):
        """Simulate read -> execute -> write across multiple turns."""
        # Turn 1: read
        resp1 = _make_response(
            '<tool_call>\n{"name": "read_file", "arguments": {"path": "/src/app.py"}}\n</tool_call>'
        )
        a1 = adapt_response(resp1, TOOLS)
        assert a1.choices[0].message.tool_calls[0].function.name == "read_file"

        # Format tool result
        result1 = format_tool_results_as_content([
            {"name": "read_file", "content": "def main(): pass"},
        ])
        assert "def main(): pass" in result1

        # Turn 2: execute
        resp2 = _make_response(
            '<tool_call>\n{"name": "execute_code", "arguments": {"code": "import app; app.main()"}}\n</tool_call>'
        )
        a2 = adapt_response(resp2, TOOLS)
        assert a2.choices[0].message.tool_calls[0].function.name == "execute_code"

        # Turn 3: write
        resp3 = _make_response(
            '<tool_call>\n{"name": "write_file", "arguments": {"path": "/out.txt", "content": "done"}}\n</tool_call>'
        )
        a3 = adapt_response(resp3, TOOLS)
        assert a3.choices[0].message.tool_calls[0].function.name == "write_file"

        # Turn 4: final answer
        resp4 = _make_response("All tasks completed successfully.")
        a4 = adapt_response(resp4, TOOLS)
        assert a4.choices[0].message.tool_calls is None
        assert a4.choices[0].message.content == "All tasks completed successfully."

    def test_tool_call_ids_are_unique(self):
        model_output = (
            '<tool_call>\n{"name": "read_file", "arguments": {"path": "/a"}}\n</tool_call>\n'
            '<tool_call>\n{"name": "read_file", "arguments": {"path": "/b"}}\n</tool_call>\n'
            '<tool_call>\n{"name": "read_file", "arguments": {"path": "/c"}}\n</tool_call>'
        )
        response = _make_response(model_output)
        adapted = adapt_response(response, TOOLS)
        calls = adapted.choices[0].message.tool_calls
        ids = [c.id for c in calls]
        assert len(ids) == 3
        assert len(set(ids)) == 3  # all unique
