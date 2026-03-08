"""Smoke tests for RustSessionDB — verifies parity with Python SessionDB.

Skipped entirely when hermes_rs is not installed.
"""

import pytest

try:
    from hermes_rs import RustSessionDB
    HAS_RUST_DB = True
except ImportError:
    HAS_RUST_DB = False

from hermes_state import SessionDB

pytestmark = pytest.mark.skipif(not HAS_RUST_DB, reason="hermes_rs not available")


@pytest.fixture()
def rust_db(tmp_path):
    db = RustSessionDB(str(tmp_path / "rust.db"))
    yield db
    db.close()


@pytest.fixture()
def py_db(tmp_path):
    db = SessionDB(db_path=tmp_path / "python.db")
    yield db
    db.close()


# =========================================================================
# Basic smoke tests (Rust-only)
# =========================================================================

class TestRustSmoke:
    def test_create_and_get_session(self, rust_db):
        sid = rust_db.create_session(session_id="s1", source="cli", model="gpt-4")
        assert sid == "s1"
        session = rust_db.get_session("s1")
        assert session["source"] == "cli"
        assert session["model"] == "gpt-4"
        assert session["ended_at"] is None

    def test_append_and_get_messages(self, rust_db):
        rust_db.create_session(session_id="s1", source="cli")
        rust_db.append_message("s1", role="user", content="Hello")
        rust_db.append_message("s1", role="assistant", content="Hi!")

        messages = rust_db.get_messages("s1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi!"

    def test_search_messages(self, rust_db):
        rust_db.create_session(session_id="s1", source="cli")
        rust_db.append_message("s1", role="user", content="Deploy with Docker")

        results = rust_db.search_messages("Docker")
        assert len(results) >= 1
        snippets = [r.get("snippet", "") for r in results]
        assert any("Docker" in s or "docker" in s for s in snippets)

    def test_export_session(self, rust_db):
        rust_db.create_session(session_id="s1", source="cli", model="test")
        rust_db.append_message("s1", role="user", content="Hello")

        export = rust_db.export_session("s1")
        assert export is not None
        assert export["source"] == "cli"
        assert len(export["messages"]) == 1

    def test_export_nonexistent(self, rust_db):
        assert rust_db.export_session("nope") is None

    def test_delete_session(self, rust_db):
        rust_db.create_session(session_id="s1", source="cli")
        rust_db.append_message("s1", role="user", content="Hello")

        assert rust_db.delete_session("s1") is True
        assert rust_db.get_session("s1") is None
        assert rust_db.message_count(session_id="s1") == 0

    def test_delete_nonexistent(self, rust_db):
        assert rust_db.delete_session("nope") is False

    def test_close_is_idempotent(self, rust_db):
        rust_db.close()
        rust_db.close()  # should not raise

    def test_append_messages_batch(self, rust_db):
        """Test the batch append_messages method (Rust-only API)."""
        rust_db.create_session(session_id="s1", source="cli")
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "tool", "content": "result", "tool_name": "search"},
        ]
        ids = rust_db.append_messages("s1", msgs)
        assert len(ids) == 3

        session = rust_db.get_session("s1")
        assert session["message_count"] == 3
        assert session["tool_call_count"] == 1


# =========================================================================
# Cross-backend parity tests
# =========================================================================

class TestParity:
    """Verify that both backends produce equivalent results for identical ops."""

    def _run_ops(self, db):
        """Execute a standard sequence of operations and return results."""
        db.create_session(session_id="s1", source="cli", model="gpt-4")
        db.create_session(session_id="s2", source="telegram")

        db.append_message("s1", role="user", content="How do I use Docker?")
        db.append_message("s1", role="assistant", content="Use docker compose.")
        db.append_message("s2", role="user", content="Rust is great")

        db.update_system_prompt("s1", "You are helpful.")
        db.update_token_counts("s1", input_tokens=100, output_tokens=50)
        db.end_session("s2", end_reason="done")

        return {
            "session_count": db.session_count(),
            "session_count_cli": db.session_count(source="cli"),
            "message_count": db.message_count(),
            "message_count_s1": db.message_count(session_id="s1"),
            "s1": db.get_session("s1"),
            "s2": db.get_session("s2"),
            "s1_messages": db.get_messages("s1"),
            "search_results_count": len(db.search_messages("Docker")),
            "search_filtered_count": len(
                db.search_messages("Docker", source_filter=["telegram"])
            ),
            "sessions_all": len(db.search_sessions()),
            "sessions_cli": len(db.search_sessions(source="cli")),
            "export_s1_msg_count": len(db.export_session("s1")["messages"]),
            "export_all_count": len(db.export_all()),
            "export_all_cli_count": len(db.export_all(source="cli")),
        }

    def test_counts_match(self, py_db, rust_db):
        py_res = self._run_ops(py_db)
        rust_res = self._run_ops(rust_db)

        assert py_res["session_count"] == rust_res["session_count"]
        assert py_res["session_count_cli"] == rust_res["session_count_cli"]
        assert py_res["message_count"] == rust_res["message_count"]
        assert py_res["message_count_s1"] == rust_res["message_count_s1"]

    def test_session_fields_match(self, py_db, rust_db):
        py_res = self._run_ops(py_db)
        rust_res = self._run_ops(rust_db)

        # Compare session fields (excluding timestamps which will differ)
        for key in ["source", "model", "system_prompt", "input_tokens",
                     "output_tokens", "message_count", "tool_call_count"]:
            assert py_res["s1"][key] == rust_res["s1"][key], f"s1.{key} mismatch"

        assert py_res["s2"]["end_reason"] == rust_res["s2"]["end_reason"]
        assert py_res["s2"]["ended_at"] is not None
        assert rust_res["s2"]["ended_at"] is not None

    def test_messages_match(self, py_db, rust_db):
        py_res = self._run_ops(py_db)
        rust_res = self._run_ops(rust_db)

        assert len(py_res["s1_messages"]) == len(rust_res["s1_messages"])
        for pm, rm in zip(py_res["s1_messages"], rust_res["s1_messages"]):
            assert pm["role"] == rm["role"]
            assert pm["content"] == rm["content"]

    def test_search_counts_match(self, py_db, rust_db):
        py_res = self._run_ops(py_db)
        rust_res = self._run_ops(rust_db)

        assert py_res["search_results_count"] == rust_res["search_results_count"]
        assert py_res["search_filtered_count"] == rust_res["search_filtered_count"]

    def test_listing_counts_match(self, py_db, rust_db):
        py_res = self._run_ops(py_db)
        rust_res = self._run_ops(rust_db)

        assert py_res["sessions_all"] == rust_res["sessions_all"]
        assert py_res["sessions_cli"] == rust_res["sessions_cli"]

    def test_export_counts_match(self, py_db, rust_db):
        py_res = self._run_ops(py_db)
        rust_res = self._run_ops(rust_db)

        assert py_res["export_s1_msg_count"] == rust_res["export_s1_msg_count"]
        assert py_res["export_all_count"] == rust_res["export_all_count"]
        assert py_res["export_all_cli_count"] == rust_res["export_all_cli_count"]
