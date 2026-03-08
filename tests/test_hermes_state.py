"""Tests for SessionDB — SQLite CRUD, FTS5 search, export.

Tests are split into two groups:
  1. Tests using the parametrized `session_db` fixture from conftest.py run
     against both the Python SessionDB *and* the Rust RustSessionDB (when available).
  2. Tests that access Python-internal attributes (db._conn) use a dedicated
     `py_db` fixture and only exercise the Python implementation.
"""

import time
import pytest
from pathlib import Path

from hermes_state import SessionDB


@pytest.fixture()
def py_db(tmp_path):
    """Create a Python-only SessionDB for tests that need _conn access."""
    db_path = tmp_path / "test_state.db"
    session_db = SessionDB(db_path=db_path)
    yield session_db
    session_db.close()


# =========================================================================
# Session lifecycle (both backends)
# =========================================================================

class TestSessionLifecycle:
    def test_create_and_get_session(self, session_db):
        sid = session_db.create_session(
            session_id="s1",
            source="cli",
            model="test-model",
        )
        assert sid == "s1"

        session = session_db.get_session("s1")
        assert session is not None
        assert session["source"] == "cli"
        assert session["model"] == "test-model"
        assert session["ended_at"] is None

    def test_get_nonexistent_session(self, session_db):
        assert session_db.get_session("nonexistent") is None

    def test_end_session(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.end_session("s1", end_reason="user_exit")

        session = session_db.get_session("s1")
        assert isinstance(session["ended_at"], float)
        assert session["end_reason"] == "user_exit"

    def test_update_system_prompt(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.update_system_prompt("s1", "You are a helpful assistant.")

        session = session_db.get_session("s1")
        assert session["system_prompt"] == "You are a helpful assistant."

    def test_update_token_counts(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.update_token_counts("s1", input_tokens=100, output_tokens=50)
        session_db.update_token_counts("s1", input_tokens=200, output_tokens=100)

        session = session_db.get_session("s1")
        assert session["input_tokens"] == 300
        assert session["output_tokens"] == 150

    def test_parent_session(self, session_db):
        session_db.create_session(session_id="parent", source="cli")
        session_db.create_session(session_id="child", source="cli", parent_session_id="parent")

        child = session_db.get_session("child")
        assert child["parent_session_id"] == "parent"


# =========================================================================
# Message storage (both backends)
# =========================================================================

class TestMessageStorage:
    def test_append_and_get_messages(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="Hello")
        session_db.append_message("s1", role="assistant", content="Hi there!")

        messages = session_db.get_messages("s1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"

    def test_message_increments_session_count(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="Hello")
        session_db.append_message("s1", role="assistant", content="Hi")

        session = session_db.get_session("s1")
        assert session["message_count"] == 2

    def test_tool_message_increments_tool_count(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="tool", content="result", tool_name="web_search")

        session = session_db.get_session("s1")
        assert session["tool_call_count"] == 1

    def test_tool_calls_serialization(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        tool_calls = [{"id": "call_1", "function": {"name": "web_search", "arguments": "{}"}}]
        session_db.append_message("s1", role="assistant", tool_calls=tool_calls)

        messages = session_db.get_messages("s1")
        assert messages[0]["tool_calls"] == tool_calls

    def test_get_messages_as_conversation(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="Hello")
        session_db.append_message("s1", role="assistant", content="Hi!")

        conv = session_db.get_messages_as_conversation("s1")
        assert len(conv) == 2
        assert conv[0] == {"role": "user", "content": "Hello"}
        assert conv[1] == {"role": "assistant", "content": "Hi!"}

    def test_finish_reason_stored(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="assistant", content="Done", finish_reason="stop")

        messages = session_db.get_messages("s1")
        assert messages[0]["finish_reason"] == "stop"


# =========================================================================
# FTS5 search (both backends)
# =========================================================================

class TestFTS5Search:
    def test_search_finds_content(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="How do I deploy with Docker?")
        session_db.append_message("s1", role="assistant", content="Use docker compose up.")

        results = session_db.search_messages("docker")
        assert len(results) == 2
        # At least one result should mention docker
        snippets = [r.get("snippet", "") for r in results]
        assert any("docker" in s.lower() or "Docker" in s for s in snippets)

    def test_search_empty_query(self, session_db):
        assert session_db.search_messages("") == []
        assert session_db.search_messages("   ") == []

    def test_search_with_source_filter(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="CLI question about Python")

        session_db.create_session(session_id="s2", source="telegram")
        session_db.append_message("s2", role="user", content="Telegram question about Python")

        results = session_db.search_messages("Python", source_filter=["telegram"])
        # Should only find the telegram message
        sources = [r["source"] for r in results]
        assert all(s == "telegram" for s in sources)

    def test_search_with_role_filter(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="What is FastAPI?")
        session_db.append_message("s1", role="assistant", content="FastAPI is a web framework.")

        results = session_db.search_messages("FastAPI", role_filter=["assistant"])
        roles = [r["role"] for r in results]
        assert all(r == "assistant" for r in roles)

    def test_search_returns_context(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="Tell me about Kubernetes")
        session_db.append_message("s1", role="assistant", content="Kubernetes is an orchestrator.")

        results = session_db.search_messages("Kubernetes")
        assert len(results) == 2
        assert "context" in results[0]
        assert isinstance(results[0]["context"], list)
        assert len(results[0]["context"]) > 0


# =========================================================================
# Session search and listing (both backends)
# =========================================================================

class TestSearchSessions:
    def test_list_all_sessions(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.create_session(session_id="s2", source="telegram")

        sessions = session_db.search_sessions()
        assert len(sessions) == 2

    def test_filter_by_source(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.create_session(session_id="s2", source="telegram")

        sessions = session_db.search_sessions(source="cli")
        assert len(sessions) == 1
        assert sessions[0]["source"] == "cli"

    def test_pagination(self, session_db):
        for i in range(5):
            session_db.create_session(session_id=f"s{i}", source="cli")

        page1 = session_db.search_sessions(limit=2)
        page2 = session_db.search_sessions(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["id"] != page2[0]["id"]


# =========================================================================
# Counts (both backends)
# =========================================================================

class TestCounts:
    def test_session_count(self, session_db):
        assert session_db.session_count() == 0
        session_db.create_session(session_id="s1", source="cli")
        session_db.create_session(session_id="s2", source="telegram")
        assert session_db.session_count() == 2

    def test_session_count_by_source(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.create_session(session_id="s2", source="telegram")
        session_db.create_session(session_id="s3", source="cli")
        assert session_db.session_count(source="cli") == 2
        assert session_db.session_count(source="telegram") == 1

    def test_message_count_total(self, session_db):
        assert session_db.message_count() == 0
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="Hello")
        session_db.append_message("s1", role="assistant", content="Hi")
        assert session_db.message_count() == 2

    def test_message_count_per_session(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.create_session(session_id="s2", source="cli")
        session_db.append_message("s1", role="user", content="A")
        session_db.append_message("s2", role="user", content="B")
        session_db.append_message("s2", role="user", content="C")
        assert session_db.message_count(session_id="s1") == 1
        assert session_db.message_count(session_id="s2") == 2


# =========================================================================
# Delete and export (both backends)
# =========================================================================

class TestDeleteAndExport:
    def test_delete_session(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.append_message("s1", role="user", content="Hello")

        assert session_db.delete_session("s1") is True
        assert session_db.get_session("s1") is None
        assert session_db.message_count(session_id="s1") == 0

    def test_delete_nonexistent(self, session_db):
        assert session_db.delete_session("nope") is False

    def test_export_session(self, session_db):
        session_db.create_session(session_id="s1", source="cli", model="test")
        session_db.append_message("s1", role="user", content="Hello")
        session_db.append_message("s1", role="assistant", content="Hi")

        export = session_db.export_session("s1")
        assert isinstance(export, dict)
        assert export["source"] == "cli"
        assert len(export["messages"]) == 2

    def test_export_nonexistent(self, session_db):
        assert session_db.export_session("nope") is None

    def test_export_all(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.create_session(session_id="s2", source="telegram")
        session_db.append_message("s1", role="user", content="A")

        exports = session_db.export_all()
        assert len(exports) == 2

    def test_export_all_with_source(self, session_db):
        session_db.create_session(session_id="s1", source="cli")
        session_db.create_session(session_id="s2", source="telegram")

        exports = session_db.export_all(source="cli")
        assert len(exports) == 1
        assert exports[0]["source"] == "cli"


# =========================================================================
# Prune (Python-only — requires _conn for backdating)
# =========================================================================

class TestPruneSessions:
    def test_prune_old_ended_sessions(self, py_db):
        # Create and end an "old" session
        py_db.create_session(session_id="old", source="cli")
        py_db.end_session("old", end_reason="done")
        # Manually backdate started_at
        py_db._conn.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?",
            (time.time() - 100 * 86400, "old"),
        )
        py_db._conn.commit()

        # Create a recent session
        py_db.create_session(session_id="new", source="cli")

        pruned = py_db.prune_sessions(older_than_days=90)
        assert pruned == 1
        assert py_db.get_session("old") is None
        session = py_db.get_session("new")
        assert session is not None
        assert session["id"] == "new"

    def test_prune_skips_active_sessions(self, py_db):
        py_db.create_session(session_id="active", source="cli")
        # Backdate but don't end
        py_db._conn.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?",
            (time.time() - 200 * 86400, "active"),
        )
        py_db._conn.commit()

        pruned = py_db.prune_sessions(older_than_days=90)
        assert pruned == 0
        assert py_db.get_session("active") is not None

    def test_prune_with_source_filter(self, py_db):
        for sid, src in [("old_cli", "cli"), ("old_tg", "telegram")]:
            py_db.create_session(session_id=sid, source=src)
            py_db.end_session(sid, end_reason="done")
            py_db._conn.execute(
                "UPDATE sessions SET started_at = ? WHERE id = ?",
                (time.time() - 200 * 86400, sid),
            )
        py_db._conn.commit()

        pruned = py_db.prune_sessions(older_than_days=90, source="cli")
        assert pruned == 1
        assert py_db.get_session("old_cli") is None
        assert py_db.get_session("old_tg") is not None


# =========================================================================
# Schema and WAL mode (Python-only — requires _conn)
# =========================================================================

class TestSchemaInit:
    def test_wal_mode(self, py_db):
        cursor = py_db._conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, py_db):
        cursor = py_db._conn.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1

    def test_tables_exist(self, py_db):
        cursor = py_db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "sessions" in tables
        assert "messages" in tables
        assert "schema_version" in tables

    def test_schema_version(self, py_db):
        cursor = py_db._conn.execute("SELECT version FROM schema_version")
        version = cursor.fetchone()[0]
        assert version == 2
