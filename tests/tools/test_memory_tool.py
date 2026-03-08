"""Tests for the memory tool — persistent cross-session memory."""

import json
import os
import tempfile

import pytest

from tools.memory_tool import MemoryStore, memory_tool, MEMORY_SCHEMA


@pytest.fixture
def store(tmp_path):
    """Create a MemoryStore with temp directories."""
    return MemoryStore(
        hermes_home=str(tmp_path / "home"),
        project_dir=str(tmp_path / "project"),
    )


class TestMemoryStore:
    def test_empty_read(self, store):
        store.load_from_disk()
        assert store.get_memory("global") == ""
        assert store.get_memory("project") == ""
        assert store.get_user_profile() == ""

    def test_add_global(self, store):
        store.add("User prefers vim", scope="global")
        assert "User prefers vim" in store.get_memory("global")

    def test_add_project(self, store):
        store.add("Uses React", scope="project")
        assert "Uses React" in store.get_memory("project")

    def test_replace(self, store):
        store.add("Uses Python 3.10", scope="global")
        store.replace("3.10", "3.12", scope="global")
        assert "3.12" in store.get_memory("global")
        assert "3.10" not in store.get_memory("global")

    def test_delete(self, store):
        store.add("temporary note", scope="global")
        store.delete("temporary note", scope="global")
        assert "temporary note" not in store.get_memory("global")

    def test_add_user(self, store):
        store.add_user("Name: Andy")
        assert "Name: Andy" in store.get_user_profile()

    def test_persistence(self, tmp_path):
        """Verify writes persist to disk and are readable by a new store."""
        store1 = MemoryStore(
            hermes_home=str(tmp_path / "home"),
            project_dir=str(tmp_path / "project"),
        )
        store1.add("persistent fact", scope="global")
        store1.add("project context", scope="project")

        store2 = MemoryStore(
            hermes_home=str(tmp_path / "home"),
            project_dir=str(tmp_path / "project"),
        )
        store2.load_from_disk()
        assert "persistent fact" in store2.get_memory("global")
        assert "project context" in store2.get_memory("project")

    def test_swarm_sharing(self, tmp_path):
        """Simulate two swarm agents sharing project memory via filesystem."""
        agent_a = MemoryStore(
            hermes_home=str(tmp_path / "home"),
            project_dir=str(tmp_path / "project"),
        )
        agent_b = MemoryStore(
            hermes_home=str(tmp_path / "home"),
            project_dir=str(tmp_path / "project"),
        )

        # Agent A writes
        agent_a.add("Frontend uses Vite", scope="project")

        # Agent B reads (simulates load_from_disk on tool call)
        agent_b.load_from_disk()
        assert "Frontend uses Vite" in agent_b.get_memory("project")

        # Agent B adds
        agent_b.add("Backend uses FastAPI", scope="project")

        # Agent A re-reads
        agent_a.load_from_disk()
        assert "Backend uses FastAPI" in agent_a.get_memory("project")

    def test_char_limit_enforcement(self, tmp_path):
        store = MemoryStore(
            hermes_home=str(tmp_path / "home"),
            project_dir=str(tmp_path / "project"),
            memory_char_limit=50,
        )
        store.add("A" * 60, scope="global")
        assert len(store.get_memory("global")) <= 50

    def test_format_for_system_prompt(self, store):
        store.add("some global memory", scope="global")
        store.add("some project memory", scope="project")
        prompt = store.format_for_system_prompt("memory")
        assert "<global-memory>" in prompt
        assert "<project-memory>" in prompt
        assert "some global memory" in prompt
        assert "some project memory" in prompt

    def test_format_for_system_prompt_user(self, store):
        store.add_user("Likes dark mode")
        prompt = store.format_for_system_prompt("user")
        assert "<user-profile>" in prompt
        assert "Likes dark mode" in prompt

    def test_format_for_injection(self, store):
        store.add("important fact", scope="global")
        injection = store.format_for_injection()
        assert "preserved across compression" in injection
        assert "important fact" in injection

    def test_format_for_injection_empty(self, store):
        assert store.format_for_injection() is None


class TestMemoryTool:
    def test_read_empty(self, store):
        result = json.loads(memory_tool(action="read", store=store))
        assert result["global_memory"] == ""
        assert result["global_chars"] == 0

    def test_add_and_read(self, store):
        memory_tool(action="add", target="global", content="test fact", store=store)
        result = json.loads(memory_tool(action="read", target="global", store=store))
        assert "test fact" in result["global_memory"]

    def test_add_project(self, store):
        memory_tool(action="add", target="project", content="proj fact", store=store)
        result = json.loads(memory_tool(action="read", target="project", store=store))
        assert "proj fact" in result["project_memory"]

    def test_replace(self, store):
        memory_tool(action="add", target="global", content="old value", store=store)
        memory_tool(
            action="replace", target="global",
            content="new value", old_text="old value", store=store,
        )
        result = json.loads(memory_tool(action="read", target="global", store=store))
        assert "new value" in result["global_memory"]
        assert "old value" not in result["global_memory"]

    def test_delete(self, store):
        memory_tool(action="add", target="global", content="removeme", store=store)
        memory_tool(action="delete", target="global", content="removeme", store=store)
        result = json.loads(memory_tool(action="read", target="global", store=store))
        assert result["global_memory"] == ""

    def test_no_store_error(self):
        result = json.loads(memory_tool(action="read", store=None))
        assert "error" in result

    def test_no_content_error(self, store):
        result = json.loads(memory_tool(action="add", store=store))
        assert "error" in result

    def test_no_old_text_error(self, store):
        result = json.loads(memory_tool(action="replace", content="new", store=store))
        assert "error" in result

    def test_unknown_action_error(self, store):
        result = json.loads(memory_tool(action="explode", store=store))
        assert "error" in result

    def test_user_profile(self, store):
        memory_tool(action="add", target="user", content="Prefers tabs", store=store)
        result = json.loads(memory_tool(action="read", target="user", store=store))
        assert "Prefers tabs" in result["user_profile"]

    def test_global_read_includes_project(self, store):
        """Global read should also show project memory for full context."""
        memory_tool(action="add", target="project", content="proj data", store=store)
        result = json.loads(memory_tool(action="read", target="global", store=store))
        assert "project_memory" in result
        assert "proj data" in result["project_memory"]


class TestMemorySchema:
    def test_schema_has_required_fields(self):
        assert MEMORY_SCHEMA["name"] == "memory"
        assert "description" in MEMORY_SCHEMA
        assert "parameters" in MEMORY_SCHEMA

    def test_schema_actions(self):
        actions = MEMORY_SCHEMA["parameters"]["properties"]["action"]["enum"]
        assert set(actions) == {"read", "add", "replace", "delete"}

    def test_schema_targets(self):
        targets = MEMORY_SCHEMA["parameters"]["properties"]["target"]["enum"]
        assert set(targets) == {"global", "project", "user"}
