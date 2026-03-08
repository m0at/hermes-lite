"""Tests for model_tools.py — function call dispatch, agent-loop interception."""

import json
import pytest

from model_tools import (
    handle_function_call,
    get_all_tool_names,
    get_toolset_for_tool,
    get_tool_definitions,
    _AGENT_LOOP_TOOLS,
    TOOL_TO_TOOLSET_MAP,
)


class TestHandleFunctionCall:
    def test_agent_loop_tool_returns_error(self):
        for tool_name in _AGENT_LOOP_TOOLS:
            result = json.loads(handle_function_call(tool_name, {}))
            assert "error" in result
            assert "agent loop" in result["error"].lower()

    def test_unknown_tool_returns_error(self):
        result = json.loads(handle_function_call("totally_fake_tool_xyz", {}))
        assert "error" in result
        assert "totally_fake_tool_xyz" in result["error"]


class TestAgentLoopTools:
    def test_expected_tools_in_set(self):
        assert "todo" in _AGENT_LOOP_TOOLS

    def test_no_regular_tools_in_set(self):
        assert "terminal" not in _AGENT_LOOP_TOOLS
        assert "read_file" not in _AGENT_LOOP_TOOLS


class TestToolDefinitions:
    def test_get_default_definitions(self):
        defs = get_tool_definitions()
        assert isinstance(defs, list)
        assert len(defs) > 0

    def test_definitions_have_function_name(self):
        defs = get_tool_definitions()
        for d in defs:
            assert "function" in d
            assert "name" in d["function"]


class TestBackwardCompat:
    def test_get_all_tool_names_returns_list(self):
        names = get_all_tool_names()
        assert isinstance(names, list)
        assert len(names) > 0
        assert "terminal" in names

    def test_get_toolset_for_unknown_tool(self):
        result = get_toolset_for_tool("totally_nonexistent_tool")
        assert result is None

    def test_tool_to_toolset_map(self):
        assert isinstance(TOOL_TO_TOOLSET_MAP, dict)
        assert len(TOOL_TO_TOOLSET_MAP) > 0
