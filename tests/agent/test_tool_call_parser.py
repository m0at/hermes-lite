"""Comprehensive tests for agent.tool_call_parser module."""

import pytest

from agent.tool_call_parser import ParsedToolCall, content_after_tool_calls, has_tool_calls, has_tool_call_start, parse_tool_calls, strip_tool_calls


# ---------------------------------------------------------------------------
# 1. Basic parsing – single tool call
# ---------------------------------------------------------------------------

class TestBasicParsing:
    def test_single_tool_call(self):
        content = '<tool_call>{"name": "get_weather", "arguments": {"city": "London"}}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "get_weather"
        assert result[0].arguments == {"city": "London"}
        assert isinstance(result[0].raw, str)

    def test_parsed_tool_call_is_dataclass(self):
        content = '<tool_call>{"name": "noop", "arguments": {}}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        tc = result[0]
        assert isinstance(tc, ParsedToolCall)
        assert tc.name == "noop"
        assert tc.arguments == {}

    def test_raw_field_contains_original_json(self):
        json_str = '{"name": "foo", "arguments": {"x": 1}}'
        content = f"<tool_call>{json_str}</tool_call>"
        result = parse_tool_calls(content)
        assert json_str in result[0].raw


# ---------------------------------------------------------------------------
# 2. Multiple tool calls
# ---------------------------------------------------------------------------

class TestMultipleToolCalls:
    def test_two_tool_calls(self):
        content = (
            '<tool_call>{"name": "a", "arguments": {"k": 1}}</tool_call>'
            '<tool_call>{"name": "b", "arguments": {"k": 2}}</tool_call>'
        )
        result = parse_tool_calls(content)
        assert len(result) == 2
        assert result[0].name == "a"
        assert result[1].name == "b"

    def test_three_tool_calls(self):
        content = (
            '<tool_call>{"name": "x", "arguments": {}}</tool_call>\n'
            '<tool_call>{"name": "y", "arguments": {}}</tool_call>\n'
            '<tool_call>{"name": "z", "arguments": {}}</tool_call>'
        )
        result = parse_tool_calls(content)
        assert len(result) == 3
        assert [tc.name for tc in result] == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# 3. Mixed content – text around tool calls
# ---------------------------------------------------------------------------

class TestMixedContent:
    def test_text_before_tool_call(self):
        content = 'Here is my plan:\n<tool_call>{"name": "run", "arguments": {}}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "run"

    def test_text_after_tool_call(self):
        content = '<tool_call>{"name": "run", "arguments": {}}</tool_call>\nDone!'
        result = parse_tool_calls(content)
        assert len(result) == 1

    def test_text_between_tool_calls(self):
        content = (
            'Step 1:\n<tool_call>{"name": "a", "arguments": {}}</tool_call>\n'
            'Step 2:\n<tool_call>{"name": "b", "arguments": {}}</tool_call>\n'
            'Finished.'
        )
        result = parse_tool_calls(content)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 4. Newlines inside tags
# ---------------------------------------------------------------------------

class TestNewlinesInTags:
    def test_newlines_around_json(self):
        content = '<tool_call>\n{"name": "func", "arguments": {"a": 1}}\n</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "func"
        assert result[0].arguments == {"a": 1}

    def test_multiple_newlines(self):
        content = '<tool_call>\n\n{"name": "func", "arguments": {}}\n\n</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "func"


# ---------------------------------------------------------------------------
# 5. Single quotes (non-standard JSON, Qwen sometimes emits this)
# ---------------------------------------------------------------------------

class TestSingleQuotes:
    def test_single_quoted_json(self):
        content = "<tool_call>{'name': 'greet', 'arguments': {'who': 'world'}}</tool_call>"
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "greet"
        assert result[0].arguments == {"who": "world"}


# ---------------------------------------------------------------------------
# 6. Empty arguments
# ---------------------------------------------------------------------------

class TestEmptyArguments:
    def test_empty_arguments_dict(self):
        content = '<tool_call>{"name": "ping", "arguments": {}}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].arguments == {}

    def test_no_arguments_key(self):
        # If the model omits arguments entirely, parser should default to {}
        content = '<tool_call>{"name": "ping"}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "ping"
        assert result[0].arguments == {} or result[0].arguments is None


# ---------------------------------------------------------------------------
# 7. Nested JSON in arguments
# ---------------------------------------------------------------------------

class TestNestedJSON:
    def test_nested_dict(self):
        content = '<tool_call>{"name": "create", "arguments": {"config": {"retries": 3, "timeout": 30}}}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].arguments["config"]["retries"] == 3

    def test_nested_list(self):
        content = '<tool_call>{"name": "batch", "arguments": {"items": [1, 2, {"nested": true}]}}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].arguments["items"][2]["nested"] is True

    def test_deeply_nested(self):
        content = '<tool_call>{"name": "deep", "arguments": {"a": {"b": {"c": {"d": "value"}}}}}</tool_call>'
        result = parse_tool_calls(content)
        assert result[0].arguments["a"]["b"]["c"]["d"] == "value"


# ---------------------------------------------------------------------------
# 8. Malformed JSON
# ---------------------------------------------------------------------------

class TestMalformedJSON:
    def test_invalid_json_returns_empty(self):
        content = "<tool_call>this is not json</tool_call>"
        result = parse_tool_calls(content)
        assert result == []

    def test_truncated_json(self):
        content = '<tool_call>{"name": "func", "arguments": {</tool_call>'
        result = parse_tool_calls(content)
        assert result == []

    def test_json_array_instead_of_object(self):
        content = "<tool_call>[1, 2, 3]</tool_call>"
        result = parse_tool_calls(content)
        assert result == []


# ---------------------------------------------------------------------------
# 9. Incomplete tags
# ---------------------------------------------------------------------------

class TestIncompleteTags:
    def test_no_closing_tag(self):
        content = '<tool_call>{"name": "func", "arguments": {}}'
        result = parse_tool_calls(content)
        assert result == []

    def test_no_opening_tag(self):
        content = '{"name": "func", "arguments": {}}</tool_call>'
        result = parse_tool_calls(content)
        assert result == []

    def test_mismatched_tags(self):
        content = '<tool_call>{"name": "func", "arguments": {}}</tool>'
        result = parse_tool_calls(content)
        assert result == []


# ---------------------------------------------------------------------------
# 10. No tool calls
# ---------------------------------------------------------------------------

class TestNoToolCalls:
    def test_plain_text(self):
        assert parse_tool_calls("Hello, how can I help you?") == []

    def test_empty_string(self):
        assert parse_tool_calls("") == []

    def test_similar_looking_tags(self):
        assert parse_tool_calls("<tool>not a tool call</tool>") == []


# ---------------------------------------------------------------------------
# 11. `function` key as alternative to `name`
# ---------------------------------------------------------------------------

class TestFunctionKey:
    def test_function_key_instead_of_name(self):
        content = '<tool_call>{"function": "search", "arguments": {"q": "test"}}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "search"
        assert result[0].arguments == {"q": "test"}

    def test_function_key_with_empty_args(self):
        content = '<tool_call>{"function": "noop", "arguments": {}}</tool_call>'
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "noop"


# ---------------------------------------------------------------------------
# 12. strip_tool_calls
# ---------------------------------------------------------------------------

class TestStripToolCalls:
    def test_removes_tool_call_block(self):
        content = 'Hello <tool_call>{"name": "x", "arguments": {}}</tool_call> World'
        result = strip_tool_calls(content)
        assert "<tool_call>" not in result
        assert "</tool_call>" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_multiple_tool_calls(self):
        content = (
            'A<tool_call>{"name": "x", "arguments": {}}</tool_call>'
            'B<tool_call>{"name": "y", "arguments": {}}</tool_call>C'
        )
        result = strip_tool_calls(content)
        assert "<tool_call>" not in result
        # Should preserve surrounding text
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_no_tool_calls_returns_original(self):
        content = "Just some text."
        assert strip_tool_calls(content) == content

    def test_only_tool_call(self):
        content = '<tool_call>{"name": "x", "arguments": {}}</tool_call>'
        result = strip_tool_calls(content)
        assert result.strip() == ""

    def test_strip_with_newlines_in_tags(self):
        content = 'Before\n<tool_call>\n{"name": "x", "arguments": {}}\n</tool_call>\nAfter'
        result = strip_tool_calls(content)
        assert "<tool_call>" not in result
        assert "Before" in result
        assert "After" in result


# ---------------------------------------------------------------------------
# 13. has_tool_calls
# ---------------------------------------------------------------------------

class TestHasToolCalls:
    def test_true_when_present(self):
        content = '<tool_call>{"name": "x", "arguments": {}}</tool_call>'
        assert has_tool_calls(content) is True

    def test_false_when_absent(self):
        assert has_tool_calls("No tools here") is False

    def test_false_on_empty(self):
        assert has_tool_calls("") is False

    def test_true_with_surrounding_text(self):
        content = 'prefix <tool_call>{"name": "x", "arguments": {}}</tool_call> suffix'
        assert has_tool_calls(content) is True

    def test_false_on_incomplete_tag(self):
        assert has_tool_calls('<tool_call>{"name": "x"}') is False


# ---------------------------------------------------------------------------
# 14. content_after_tool_calls
# ---------------------------------------------------------------------------

class TestContentAfterToolCalls:
    def test_returns_text_after_last_tool_call(self):
        content = '<tool_call>{"name": "x", "arguments": {}}</tool_call>\nHere is the result.'
        result = content_after_tool_calls(content)
        assert "Here is the result." in result

    def test_no_content_after(self):
        content = '<tool_call>{"name": "x", "arguments": {}}</tool_call>'
        result = content_after_tool_calls(content)
        assert result.strip() == ""

    def test_no_tool_calls_returns_full_content(self):
        content = "Just regular text."
        result = content_after_tool_calls(content)
        assert result == content

    def test_multiple_tool_calls_returns_after_last(self):
        content = (
            '<tool_call>{"name": "a", "arguments": {}}</tool_call>\n'
            'middle\n'
            '<tool_call>{"name": "b", "arguments": {}}</tool_call>\n'
            'final text'
        )
        result = content_after_tool_calls(content)
        assert "final text" in result
        # Should not contain middle text or tool calls
        assert "<tool_call>" not in result


# ---------------------------------------------------------------------------
# 15. Whitespace handling
# ---------------------------------------------------------------------------

class TestWhitespaceHandling:
    def test_spaces_around_tags(self):
        content = '  <tool_call>  {"name": "x", "arguments": {}}  </tool_call>  '
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "x"

    def test_tabs_around_tags(self):
        content = '\t<tool_call>\t{"name": "x", "arguments": {}}\t</tool_call>\t'
        result = parse_tool_calls(content)
        assert len(result) == 1

    def test_mixed_whitespace(self):
        content = ' \t\n<tool_call>\n\t {"name": "x", "arguments": {}} \n\t</tool_call>\n '
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "x"


# ---------------------------------------------------------------------------
# 16. Realistic Qwen3.5 output with thinking + tool calls
# ---------------------------------------------------------------------------

class TestRealisticQwenOutput:
    def test_qwen_thinking_then_tool_call(self):
        content = (
            "<think>\n"
            "The user wants to search for files. I should use the search tool.\n"
            "Let me construct the appropriate arguments.\n"
            "</think>\n\n"
            '<tool_call>{"name": "search_files", "arguments": {"pattern": "*.py", "directory": "/src"}}</tool_call>'
        )
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "search_files"
        assert result[0].arguments == {"pattern": "*.py", "directory": "/src"}

    def test_qwen_thinking_multiple_tool_calls(self):
        content = (
            "<think>\n"
            "I need to read two files to understand the issue.\n"
            "</think>\n\n"
            '<tool_call>{"name": "read_file", "arguments": {"path": "/src/main.py"}}</tool_call>\n'
            '<tool_call>{"name": "read_file", "arguments": {"path": "/src/utils.py"}}</tool_call>'
        )
        result = parse_tool_calls(content)
        assert len(result) == 2
        assert result[0].arguments["path"] == "/src/main.py"
        assert result[1].arguments["path"] == "/src/utils.py"

    def test_qwen_with_explanation_and_tool_call(self):
        content = (
            "<think>\nLet me think about this...\n</think>\n\n"
            "I'll search for the relevant files first.\n\n"
            '<tool_call>{"name": "grep", "arguments": {"pattern": "def main", "path": "."}}</tool_call>\n\n'
            "This should help us find the entry point."
        )
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "grep"

    def test_qwen_function_key_format(self):
        content = (
            "<think>\nI need to execute a command.\n</think>\n\n"
            '<tool_call>{"function": "bash", "arguments": {"command": "ls -la /tmp"}}</tool_call>'
        )
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "bash"
        assert result[0].arguments["command"] == "ls -la /tmp"

    def test_strip_preserves_thinking_and_text(self):
        content = (
            "<think>\nSome reasoning.\n</think>\n\n"
            "Here is what I found:\n"
            '<tool_call>{"name": "search", "arguments": {}}</tool_call>\n'
            "Summary of results."
        )
        result = strip_tool_calls(content)
        assert "<think>" in result
        assert "Here is what I found:" in result
        assert "Summary of results." in result
        assert "<tool_call>" not in result

    def test_qwen_single_quotes_with_thinking(self):
        content = (
            "<think>\nLet me check.\n</think>\n\n"
            "<tool_call>{'name': 'read_file', 'arguments': {'path': '/etc/hosts'}}</tool_call>"
        )
        result = parse_tool_calls(content)
        assert len(result) == 1
        assert result[0].name == "read_file"


# ---------------------------------------------------------------------------
# 17. has_tool_call_start — detects truncated tool calls
# ---------------------------------------------------------------------------

class TestHasToolCallStart:
    def test_complete_tool_call(self):
        content = '<tool_call>{"name": "x", "arguments": {}}</tool_call>'
        assert has_tool_call_start(content) is True

    def test_truncated_tool_call(self):
        content = '<tool_call>{"name": "delegate_task", "arguments": {"goal": "test"'
        assert has_tool_call_start(content) is True

    def test_no_tool_call(self):
        assert has_tool_call_start("Just text") is False

    def test_empty(self):
        assert has_tool_call_start("") is False

    def test_truncated_with_text_before(self):
        content = 'Let me do this.\n<tool_call>{"name": "x", "arguments": {'
        assert has_tool_call_start(content) is True
