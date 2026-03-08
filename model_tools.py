#!/usr/bin/env python3
"""
Minimal tool orchestration layer for hermes-lite.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from typing import Any, Dict, List, Optional

from toolsets import resolve_toolset, validate_toolset
from tools.registry import registry

logger = logging.getLogger(__name__)


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=300)
    return asyncio.run(coro)


def _discover_tools() -> None:
    modules = [
        "tools.terminal_tool",
        "tools.file_tools",
        "tools.todo_tool",
        "tools.process_registry",
        "tools.clarify_tool",
    ]
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
        except Exception as exc:
            logger.debug("Could not import %s: %s", mod_name, exc)


_discover_tools()

TOOL_TO_TOOLSET_MAP: Dict[str, str] = registry.get_tool_to_toolset_map()
TOOLSET_REQUIREMENTS: Dict[str, dict] = registry.get_toolset_requirements()

_last_resolved_tool_names: List[str] = []
_AGENT_LOOP_TOOLS = {"todo"}


def get_tool_definitions(
    enabled_toolsets: Optional[List[str]] = None,
    disabled_toolsets: Optional[List[str]] = None,
    quiet_mode: bool = False,
) -> List[Dict[str, Any]]:
    tools_to_include: set[str] = set()

    if enabled_toolsets:
        for toolset_name in enabled_toolsets:
            if validate_toolset(toolset_name):
                tools_to_include.update(resolve_toolset(toolset_name))
            elif not quiet_mode:
                print(f"⚠️  Unknown toolset: {toolset_name}")
    else:
        tools_to_include.update(resolve_toolset("hermes-lite-cli"))
        if disabled_toolsets:
            for toolset_name in disabled_toolsets:
                if validate_toolset(toolset_name):
                    tools_to_include.difference_update(resolve_toolset(toolset_name))

    filtered_tools = registry.get_definitions(tools_to_include, quiet=quiet_mode)

    global _last_resolved_tool_names
    _last_resolved_tool_names = [t["function"]["name"] for t in filtered_tools]
    return filtered_tools


def handle_function_call(
    function_name: str,
    function_args: Dict[str, Any],
    task_id: Optional[str] = None,
    user_task: Optional[str] = None,
) -> str:
    if function_name in _AGENT_LOOP_TOOLS:
        return json.dumps(
            {"error": f"Tool '{function_name}' must be handled by the agent loop."},
            ensure_ascii=False,
        )
    return registry.dispatch(function_name, function_args, task_id=task_id, user_task=user_task)


def get_all_tool_names() -> List[str]:
    return registry.get_all_tool_names()


def get_toolset_for_tool(name: str) -> Optional[str]:
    return registry.get_toolset_for_tool(name)


def get_available_toolsets() -> Dict[str, dict]:
    return registry.get_available_toolsets()


def check_toolset_requirements() -> Dict[str, bool]:
    return registry.check_toolset_requirements()


def check_tool_availability(quiet: bool = False):
    return registry.check_tool_availability(quiet=quiet)
