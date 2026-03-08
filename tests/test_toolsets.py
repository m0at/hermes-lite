"""Tests for toolsets.py — toolset resolution, validation, and composition."""

import pytest

from toolsets import (
    TOOLSETS,
    get_toolset,
    resolve_toolset,
    resolve_multiple_toolsets,
    get_all_toolsets,
    get_toolset_names,
    validate_toolset,
    create_custom_toolset,
    get_toolset_info,
)


class TestGetToolset:
    def test_known_toolset(self):
        ts = get_toolset("terminal")
        assert ts is not None
        assert "terminal" in ts["tools"]

    def test_unknown_returns_none(self):
        assert get_toolset("nonexistent") is None


class TestResolveToolset:
    def test_leaf_toolset(self):
        tools = resolve_toolset("terminal")
        assert "terminal" in tools

    def test_default_toolset(self):
        tools = resolve_toolset("hermes-lite-cli")
        assert "terminal" in tools
        assert "read_file" in tools
        assert "todo" in tools

    def test_cycle_detection(self):
        TOOLSETS["_cycle_a"] = {"description": "test", "tools": ["t1"], "includes": ["_cycle_b"]}
        TOOLSETS["_cycle_b"] = {"description": "test", "tools": ["t2"], "includes": ["_cycle_a"]}
        try:
            tools = resolve_toolset("_cycle_a")
            assert "t1" in tools
            assert "t2" in tools
        finally:
            del TOOLSETS["_cycle_a"]
            del TOOLSETS["_cycle_b"]

    def test_unknown_toolset_returns_empty(self):
        assert resolve_toolset("nonexistent") == []

    def test_all_alias(self):
        tools = resolve_toolset("all")
        assert len(tools) >= 5

    def test_star_alias(self):
        tools = resolve_toolset("*")
        assert len(tools) >= 5


class TestResolveMultipleToolsets:
    def test_combines_and_deduplicates(self):
        tools = resolve_multiple_toolsets(["terminal", "file"])
        assert "terminal" in tools
        assert "read_file" in tools
        assert len(tools) == len(set(tools))

    def test_empty_list(self):
        assert resolve_multiple_toolsets([]) == []


class TestValidateToolset:
    def test_valid(self):
        assert validate_toolset("terminal") is True
        assert validate_toolset("file") is True

    def test_all_alias_valid(self):
        assert validate_toolset("all") is True
        assert validate_toolset("*") is True

    def test_invalid(self):
        assert validate_toolset("nonexistent") is False


class TestGetToolsetInfo:
    def test_known(self):
        info = get_toolset_info("terminal")
        assert info["name"] == "terminal"
        assert len(info["tools"]) > 0

    def test_unknown_returns_empty(self):
        assert get_toolset_info("nonexistent") == {}


class TestCreateCustomToolset:
    def test_runtime_creation(self):
        create_custom_toolset(
            name="_test_custom",
            description="Test toolset",
            tools=["terminal"],
            includes=["file"],
        )
        try:
            tools = resolve_toolset("_test_custom")
            assert "terminal" in tools
            assert "read_file" in tools
            assert validate_toolset("_test_custom") is True
        finally:
            del TOOLSETS["_test_custom"]


class TestToolsetConsistency:
    def test_all_toolsets_have_required_keys(self):
        for name, ts in TOOLSETS.items():
            assert "description" in ts, f"{name} missing description"
            assert "tools" in ts, f"{name} missing tools"
            assert "includes" in ts, f"{name} missing includes"

    def test_all_includes_reference_existing_toolsets(self):
        for name, ts in TOOLSETS.items():
            for inc in ts["includes"]:
                assert inc in TOOLSETS, f"{name} includes unknown toolset '{inc}'"
