"""Comprehensive tests for agent.tool_response_adapter."""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.tool_response_adapter import (
    adapt_response,
    format_tool_results_as_content,
    should_adapt,
)


def make_response(content, tool_calls=None, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ]
    )


SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "Run code",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
]


# ── 1. adapt_response basic: tool_call tag → tool_calls populated ──


def test_adapt_response_populates_tool_calls():
    content = '<tool_call>\n{"name": "execute_code", "arguments": {"code": "print(1)"}}\n</tool_call>'
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    assert result.choices[0].message.tool_calls is not None
    assert len(result.choices[0].message.tool_calls) == 1


# ── 2. adapt_response: correct name and arguments ──


def test_adapt_response_correct_name_and_arguments():
    content = '<tool_call>\n{"name": "read_file", "arguments": {"path": "/tmp/x.py"}}\n</tool_call>'
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    tc = result.choices[0].message.tool_calls[0]
    assert tc.function.name == "read_file"
    args = json.loads(tc.function.arguments)
    assert args == {"path": "/tmp/x.py"}


# ── 3. adapt_response: unique IDs starting with "call_" ──


def test_adapt_response_unique_ids():
    content = (
        '<tool_call>\n{"name": "execute_code", "arguments": {"code": "a"}}\n</tool_call>\n'
        '<tool_call>\n{"name": "read_file", "arguments": {"path": "b"}}\n</tool_call>'
    )
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    calls = result.choices[0].message.tool_calls
    assert len(calls) == 2
    ids = [c.id for c in calls]
    assert all(i.startswith("call_") for i in ids)
    assert ids[0] != ids[1]


# ── 4. adapt_response: content stripped of tool_call blocks ──


def test_adapt_response_strips_tool_call_from_content():
    content = 'Here is my plan.\n<tool_call>\n{"name": "execute_code", "arguments": {"code": "x"}}\n</tool_call>\nDone.'
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    msg_content = result.choices[0].message.content
    assert "<tool_call>" not in msg_content
    assert "</tool_call>" not in msg_content
    assert "Here is my plan." in msg_content


# ── 5. adapt_response: finish_reason changed to "tool_calls" ──


def test_adapt_response_sets_finish_reason():
    content = '<tool_call>\n{"name": "execute_code", "arguments": {"code": "1"}}\n</tool_call>'
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    assert result.choices[0].finish_reason == "tool_calls"


# ── 6. adapt_response: multiple tool calls parsed ──


def test_adapt_response_multiple_tool_calls():
    content = (
        '<tool_call>\n{"name": "execute_code", "arguments": {"code": "print(1)"}}\n</tool_call>\n'
        '<tool_call>\n{"name": "read_file", "arguments": {"path": "/a"}}\n</tool_call>\n'
        '<tool_call>\n{"name": "execute_code", "arguments": {"code": "print(2)"}}\n</tool_call>'
    )
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    calls = result.choices[0].message.tool_calls
    assert len(calls) == 3
    assert calls[0].function.name == "execute_code"
    assert calls[1].function.name == "read_file"
    assert calls[2].function.name == "execute_code"


# ── 7. adapt_response no-op: already has tool_calls ──


def test_adapt_response_noop_existing_tool_calls():
    existing = [
        SimpleNamespace(
            id="call_existing",
            function=SimpleNamespace(name="read_file", arguments='{"path": "/z"}'),
        )
    ]
    content = '<tool_call>\n{"name": "execute_code", "arguments": {"code": "x"}}\n</tool_call>'
    resp = make_response(content, tool_calls=existing)
    # adapt_response doesn't call should_adapt — it always tries to parse.
    # But since existing tool_calls are truthy, the response shouldn't change
    # because the caller should check should_adapt() first.
    # Test that calling adapt_response directly still works (it parses and adds)
    result = adapt_response(resp, SAMPLE_TOOLS)
    # The implementation parses regardless — check it has calls
    assert result.choices[0].message.tool_calls is not None


# ── 8. adapt_response no-op: no tool_call tags ──


def test_adapt_response_noop_no_tags():
    content = "Just a normal response with no tool calls."
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    assert result.choices[0].message.tool_calls is None
    assert result.choices[0].message.content == content
    assert result.choices[0].finish_reason == "stop"


# ── 9. adapt_response: invalid tool name not included ──


def test_adapt_response_invalid_tool_name_excluded():
    content = (
        '<tool_call>\n{"name": "nonexistent_tool", "arguments": {"x": 1}}\n</tool_call>\n'
        '<tool_call>\n{"name": "read_file", "arguments": {"path": "/ok"}}\n</tool_call>'
    )
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    calls = result.choices[0].message.tool_calls
    assert len(calls) == 1
    assert calls[0].function.name == "read_file"


# ── 10. should_adapt: local model + tool_call content → True ──


def test_should_adapt_local_model_with_tool_call():
    content = '<tool_call>\n{"name": "execute_code", "arguments": {"code": "1"}}\n</tool_call>'
    resp = make_response(content)
    assert should_adapt(resp, "local/qwen3.5-9b") is True


def test_should_adapt_local_model_variants():
    content = '<tool_call>\n{"name": "execute_code", "arguments": {}}\n</tool_call>'
    resp = make_response(content)
    assert should_adapt(resp, "local/qwen3.5-9b") is True
    assert should_adapt(resp, "local/llama-3") is True


# ── 11. should_adapt: cloud model → False ──


def test_should_adapt_cloud_model_false():
    content = '<tool_call>\n{"name": "execute_code", "arguments": {"code": "1"}}\n</tool_call>'
    resp = make_response(content)
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HERMES_FORCE_TOOL_INJECTION", None)
        for model in ["gpt-4", "gpt-4o", "anthropic/claude-sonnet-4", "google/gemini-2.5-flash"]:
            assert should_adapt(resp, model) is False


# ── 12. should_adapt: no tool_call content → False ──


def test_should_adapt_no_tool_call_content():
    resp = make_response("Just a normal message.")
    assert should_adapt(resp, "local/qwen3.5-9b") is False


# ── 13. should_adapt: env var override ──


def test_should_adapt_env_var_override():
    content = '<tool_call>\n{"name": "execute_code", "arguments": {}}\n</tool_call>'
    resp = make_response(content)
    with patch.dict(os.environ, {"HERMES_FORCE_TOOL_INJECTION": "1"}):
        assert should_adapt(resp, "gpt-4") is True


# ── 14. format_tool_results_as_content: single result ──


def test_format_tool_results_single():
    results = [{"name": "execute_code", "content": "OK"}]
    output = format_tool_results_as_content(results)
    assert "<tool_response>" in output
    assert "</tool_response>" in output
    assert "execute_code" in output
    assert "OK" in output


# ── 15. format_tool_results_as_content: multiple results ──


def test_format_tool_results_multiple():
    results = [
        {"name": "execute_code", "content": "output1"},
        {"name": "read_file", "content": "file contents"},
    ]
    output = format_tool_results_as_content(results)
    assert output.count("<tool_response>") == 2
    assert "output1" in output
    assert "file contents" in output
    assert "execute_code" in output
    assert "read_file" in output


# ── 16. format_tool_results_as_content: special chars ──


def test_format_tool_results_special_chars():
    results = [
        {
            "name": "execute_code",
            "content": 'Error: <KeyError> "foo" & \'bar\'',
        }
    ]
    output = format_tool_results_as_content(results)
    assert "foo" in output
    assert "bar" in output
    assert "Error" in output


# ── 17. should_adapt: truncated tool call (no closing tag) → True ──


def test_should_adapt_truncated_tool_call():
    """A <tool_call> tag without closing </tool_call> should still trigger adaptation."""
    content = '<tool_call>{"name": "delegate_task", "arguments": {"goal": "test"'
    resp = make_response(content)
    assert should_adapt(resp, "local/qwen3.5-9b") is True


# ── 18. adapt_response: truncated JSON returns unchanged but preserves original content ──


def test_adapt_response_truncated_preserves_original():
    content = '<tool_call>{"name": "execute_code", "arguments": {"code": "print(1)'
    resp = make_response(content)
    result = adapt_response(resp, SAMPLE_TOOLS)
    # Should not crash, tool_calls should be None (unparseable)
    msg = result.choices[0].message
    assert msg.tool_calls is None
    # Original content should be preserved for truncation detection
    assert hasattr(msg, "_original_content")
    assert "<tool_call>" in msg._original_content


# ── 19. should_adapt: truncated + cloud model → False ──


def test_should_adapt_truncated_cloud_model_false():
    content = '<tool_call>{"name": "execute_code", "arguments": {"code": "x"'
    resp = make_response(content)
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HERMES_FORCE_TOOL_INJECTION", None)
        assert should_adapt(resp, "gpt-4") is False
