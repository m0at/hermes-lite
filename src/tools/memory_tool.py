#!/usr/bin/env python3
"""
Memory Tool — Persistent cross-session memory for hermes-lite agents.

Two memory scopes:
- **Global** (~/.hermes-lite/MEMORY.md) — user preferences, patterns, conventions
- **Project** (.hermes/MEMORY.md in cwd) — project-specific context, architecture notes

In multi-agent swarm mode, all sub-agents share the same filesystem, so project
memories are automatically visible to every agent in the swarm. File-based sharing
means no IPC needed — agents read the latest state on each access.

Design follows the todo_tool pattern:
- Single `memory` tool entry point
- action param selects read/add/replace/delete
- target param selects global vs project scope
- Always returns full current memory contents
- Behavioral guidance lives in schema description
"""

import json
import logging
import os
import fcntl
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_HERMES_HOME = os.path.expanduser("~/.hermes-lite")
PROJECT_MEMORY_DIR = ".hermes"
MEMORY_FILENAME = "MEMORY.md"
USER_FILENAME = "USER.md"


class MemoryStore:
    """
    File-backed memory store. One instance per AIAgent.

    Manages two scopes:
    - global: ~/.hermes-lite/MEMORY.md (user-level, cross-project)
    - project: .hermes/MEMORY.md (project-level, shared across swarm agents)

    Also manages USER.md for user profile (global scope only).
    """

    def __init__(
        self,
        memory_char_limit: int = 2200,
        user_char_limit: int = 1375,
        hermes_home: Optional[str] = None,
        project_dir: Optional[str] = None,
    ):
        self._memory_char_limit = memory_char_limit
        self._user_char_limit = user_char_limit

        home = Path(hermes_home or os.getenv("HERMES_HOME", DEFAULT_HERMES_HOME))
        self._global_memory_path = home / MEMORY_FILENAME
        self._user_profile_path = home / USER_FILENAME

        proj = Path(project_dir or os.getcwd())
        self._project_memory_dir = proj / PROJECT_MEMORY_DIR
        self._project_memory_path = self._project_memory_dir / MEMORY_FILENAME

        # In-memory cache (loaded from disk, written back on mutations)
        self._global_memory: str = ""
        self._project_memory: str = ""
        self._user_profile: str = ""

    # ------------------------------------------------------------------
    # Disk I/O
    # ------------------------------------------------------------------

    def load_from_disk(self) -> None:
        """Load all memory files from disk into cache."""
        self._global_memory = self._read_file(self._global_memory_path)
        self._project_memory = self._read_file(self._project_memory_path)
        self._user_profile = self._read_file(self._user_profile_path)

    def _read_file(self, path: Path) -> str:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.debug("Failed to read %s: %s", path, e)
        return ""

    def _write_file(self, path: Path, content: str) -> None:
        """Atomic write with file locking for safe concurrent access from swarm agents."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Use file locking to prevent concurrent write corruption
            lock_path = path.with_suffix(path.suffix + ".lock")
            with open(lock_path, "w") as lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                try:
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(content, encoding="utf-8")
                    tmp.rename(path)
                finally:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            # Clean up lock file (best effort)
            try:
                lock_path.unlink()
            except OSError:
                pass
        except Exception as e:
            logger.error("Failed to write %s: %s", path, e)

    # ------------------------------------------------------------------
    # Getters
    # ------------------------------------------------------------------

    def get_memory(self, scope: str = "global") -> str:
        if scope == "project":
            return self._project_memory
        return self._global_memory

    def get_user_profile(self) -> str:
        return self._user_profile

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, content: str, scope: str = "global") -> str:
        """Append content to memory. Returns updated memory."""
        content = content.strip()
        if not content:
            return self.get_memory(scope)

        current = self.get_memory(scope)
        if current:
            updated = current + "\n\n" + content
        else:
            updated = content

        return self._set_memory(updated, scope)

    def replace(self, old_text: str, new_text: str, scope: str = "global") -> str:
        """Replace old_text with new_text in memory. Returns updated memory."""
        current = self.get_memory(scope)
        if old_text not in current:
            return current  # No match, no change
        updated = current.replace(old_text, new_text, 1)
        return self._set_memory(updated, scope)

    def delete(self, content: str, scope: str = "global") -> str:
        """Remove content from memory. Returns updated memory."""
        current = self.get_memory(scope)
        if content not in current:
            return current
        updated = current.replace(content, "", 1).strip()
        # Clean up double blank lines
        while "\n\n\n" in updated:
            updated = updated.replace("\n\n\n", "\n\n")
        return self._set_memory(updated, scope)

    def add_user(self, content: str) -> str:
        """Append to user profile. Returns updated profile."""
        content = content.strip()
        if not content:
            return self._user_profile
        if self._user_profile:
            self._user_profile = self._user_profile + "\n\n" + content
        else:
            self._user_profile = content
        self._enforce_limit("user")
        self._write_file(self._user_profile_path, self._user_profile)
        return self._user_profile

    def _set_memory(self, content: str, scope: str) -> str:
        """Update memory for scope, enforce limits, persist to disk."""
        content = content.strip()
        if scope == "project":
            self._project_memory = content
            self._enforce_limit("project")
            self._write_file(self._project_memory_path, self._project_memory)
            return self._project_memory
        else:
            self._global_memory = content
            self._enforce_limit("global")
            self._write_file(self._global_memory_path, self._global_memory)
            return self._global_memory

    def _enforce_limit(self, target: str) -> None:
        """Trim memory to char limit, keeping most recent content."""
        if target == "user":
            if len(self._user_profile) > self._user_char_limit:
                self._user_profile = self._user_profile[-self._user_char_limit:]
                # Trim to next complete line
                idx = self._user_profile.find("\n")
                if idx > 0:
                    self._user_profile = self._user_profile[idx + 1:]
        elif target == "project":
            if len(self._project_memory) > self._memory_char_limit:
                self._project_memory = self._project_memory[-self._memory_char_limit:]
                idx = self._project_memory.find("\n")
                if idx > 0:
                    self._project_memory = self._project_memory[idx + 1:]
        else:
            if len(self._global_memory) > self._memory_char_limit:
                self._global_memory = self._global_memory[-self._memory_char_limit:]
                idx = self._global_memory.find("\n")
                if idx > 0:
                    self._global_memory = self._global_memory[idx + 1:]

    # ------------------------------------------------------------------
    # System prompt injection
    # ------------------------------------------------------------------

    def format_for_system_prompt(self, target: str = "memory") -> Optional[str]:
        """Render memory block for inclusion in the system prompt."""
        if target == "user":
            if not self._user_profile:
                return None
            return (
                "<user-profile>\n"
                "What you know about the user from past interactions:\n"
                f"{self._user_profile}\n"
                "</user-profile>"
            )

        parts = []
        if self._global_memory:
            parts.append(
                "<global-memory>\n"
                "Your persistent memories (cross-project):\n"
                f"{self._global_memory}\n"
                "</global-memory>"
            )
        if self._project_memory:
            parts.append(
                "<project-memory>\n"
                "Project-specific memories (shared with all swarm agents):\n"
                f"{self._project_memory}\n"
                "</project-memory>"
            )

        if not parts:
            return None
        return "\n\n".join(parts)

    def format_for_injection(self) -> Optional[str]:
        """Render memory for post-compression injection (like todo_tool)."""
        parts = []
        if self._global_memory:
            parts.append(f"[Global memories preserved across compression]\n{self._global_memory}")
        if self._project_memory:
            parts.append(f"[Project memories preserved across compression]\n{self._project_memory}")
        return "\n\n".join(parts) if parts else None


# =============================================================================
# Tool entry point
# =============================================================================

def memory_tool(
    action: Optional[str] = None,
    target: Optional[str] = None,
    content: Optional[str] = None,
    old_text: Optional[str] = None,
    store: Optional[MemoryStore] = None,
) -> str:
    """
    Single entry point for the memory tool.

    Args:
        action: read (default), add, replace, delete
        target: global (default), project, user
        content: text to add/replace/delete
        old_text: text to find (for replace action)
        store: MemoryStore instance from AIAgent
    """
    if store is None:
        return json.dumps({"error": "MemoryStore not initialized. Enable memory in config."})

    # Reload from disk on every read to pick up writes from other swarm agents
    store.load_from_disk()

    action = (action or "read").strip().lower()
    target = (target or "global").strip().lower()

    if action == "read":
        return _format_response(store, target)

    if not content or not content.strip():
        return json.dumps({"error": "content is required for add/replace/delete actions."})

    if action == "add":
        if target == "user":
            store.add_user(content)
        else:
            store.add(content, scope=target)
    elif action == "replace":
        if not old_text:
            return json.dumps({"error": "old_text is required for replace action."})
        if target == "user":
            # Simple replace for user profile
            current = store.get_user_profile()
            if old_text in current:
                updated = current.replace(old_text, content, 1)
                store._user_profile = updated
                store._enforce_limit("user")
                store._write_file(store._user_profile_path, store._user_profile)
        else:
            store.replace(old_text, content, scope=target)
    elif action == "delete":
        if target == "user":
            current = store.get_user_profile()
            if content in current:
                updated = current.replace(content, "", 1).strip()
                while "\n\n\n" in updated:
                    updated = updated.replace("\n\n\n", "\n\n")
                store._user_profile = updated
                store._write_file(store._user_profile_path, store._user_profile)
        else:
            store.delete(content, scope=target)
    else:
        return json.dumps({"error": f"Unknown action: {action}. Use read/add/replace/delete."})

    return _format_response(store, target)


def _format_response(store: MemoryStore, target: str) -> str:
    """Build JSON response with current memory state."""
    result = {}

    if target == "user":
        result["user_profile"] = store.get_user_profile()
        result["user_chars"] = len(store.get_user_profile())
    elif target == "project":
        result["project_memory"] = store.get_memory("project")
        result["project_chars"] = len(store.get_memory("project"))
    else:
        # Global read also returns project memory for full context
        result["global_memory"] = store.get_memory("global")
        result["global_chars"] = len(store.get_memory("global"))
        result["project_memory"] = store.get_memory("project")
        result["project_chars"] = len(store.get_memory("project"))

    return json.dumps(result, ensure_ascii=False)


def check_memory_requirements() -> bool:
    return True


# =============================================================================
# Schema
# =============================================================================

MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Manage persistent memories that survive across sessions and context compression. "
        "Two scopes:\n"
        "- global: user preferences, patterns, conventions (~/.hermes-lite/MEMORY.md)\n"
        "- project: architecture, decisions, context for this project (.hermes/MEMORY.md)\n"
        "- user: observations about the user for personalization\n\n"
        "In multi-agent swarm mode, project memories are shared across all agents "
        "automatically via the filesystem.\n\n"
        "Actions:\n"
        "- read (default): return current memories\n"
        "- add: append new content\n"
        "- replace: swap old_text with content\n"
        "- delete: remove content\n\n"
        "Save important context: project structure, user preferences, recurring patterns, "
        "architecture decisions, key file paths. Keep entries concise and factual.\n"
        "Always read before writing to avoid duplicates."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "add", "replace", "delete"],
                "description": "What to do. Default: read.",
            },
            "target": {
                "type": "string",
                "enum": ["global", "project", "user"],
                "description": "Memory scope. Default: global.",
            },
            "content": {
                "type": "string",
                "description": "Text to add, or new text for replace, or text to delete.",
            },
            "old_text": {
                "type": "string",
                "description": "Text to find (for replace action only).",
            },
        },
        "required": [],
    },
}


# =============================================================================
# Registry
# =============================================================================

from tools.registry import registry

registry.register(
    name="memory",
    toolset="memory",
    schema=MEMORY_SCHEMA,
    handler=lambda args, **kw: memory_tool(
        action=args.get("action"),
        target=args.get("target"),
        content=args.get("content"),
        old_text=args.get("old_text"),
        store=kw.get("store"),
    ),
    check_fn=check_memory_requirements,
)
