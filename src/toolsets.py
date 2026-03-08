#!/usr/bin/env python3
"""
Minimal toolset definitions for hermes-lite.

The lite build keeps the local coding-agent surface only:
- terminal + background processes
- file read/write/patch/search
- todo planning
- clarify for interactive questions
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


_CORE_TOOLS = [
    "terminal",
    "process",
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "todo",
    "clarify",
    "delegate_task",
]


TOOLSETS: Dict[str, Dict[str, Any]] = {
    "terminal": {
        "description": "Local terminal execution and background process management",
        "tools": ["terminal", "process"],
        "includes": [],
    },
    "file": {
        "description": "Read, write, patch, and search files through the terminal backend",
        "tools": ["read_file", "write_file", "patch", "search_files"],
        "includes": [],
    },
    "todo": {
        "description": "Task planning and progress tracking for multi-step work",
        "tools": ["todo"],
        "includes": [],
    },
    "clarify": {
        "description": "Ask the user a clarifying question through the CLI",
        "tools": ["clarify"],
        "includes": [],
    },
    "delegate": {
        "description": "Delegate tasks to other agents in the swarm (multi-agent TUI mode)",
        "tools": ["delegate_task"],
        "includes": [],
    },
    "hermes-lite-cli": {
        "description": "Default hermes-lite coding agent toolset",
        "tools": _CORE_TOOLS,
        "includes": [],
    },
}


def get_toolset(name: str) -> Optional[Dict[str, Any]]:
    return TOOLSETS.get(name)


def resolve_toolset(name: str, visited: Optional[Set[str]] = None) -> List[str]:
    if visited is None:
        visited = set()

    if name in {"all", "*"}:
        tools: Set[str] = set()
        for toolset_name in TOOLSETS:
            tools.update(resolve_toolset(toolset_name))
        return sorted(tools)

    if name in visited:
        return []
    visited.add(name)

    toolset = TOOLSETS.get(name)
    if not toolset:
        return []

    tools = set(toolset.get("tools", []))
    for included in toolset.get("includes", []):
        tools.update(resolve_toolset(included, visited.copy()))
    return sorted(tools)


def resolve_multiple_toolsets(toolset_names: List[str]) -> List[str]:
    tools: Set[str] = set()
    for name in toolset_names:
        tools.update(resolve_toolset(name))
    return sorted(tools)


def get_all_toolsets() -> Dict[str, Dict[str, Any]]:
    return TOOLSETS.copy()


def get_toolset_names() -> List[str]:
    return list(TOOLSETS.keys())


def validate_toolset(name: str) -> bool:
    return name in {"all", "*"} or name in TOOLSETS


def create_custom_toolset(
    name: str,
    description: str,
    tools: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
) -> None:
    TOOLSETS[name] = {
        "description": description,
        "tools": tools or [],
        "includes": includes or [],
    }


def get_toolset_info(name: str) -> Dict[str, Any]:
    toolset = get_toolset(name)
    if not toolset:
        return {}
    return {
        "name": name,
        "description": toolset.get("description", ""),
        "tools": resolve_toolset(name),
        "includes": list(toolset.get("includes", [])),
    }
