import sqlite3

import pytest

from jarvis.store import AuditLog, ContextStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "jarvis-test.db"


class TestContextStore:
    def test_record_and_recent(self, db_path):
        store = ContextStore(db_path)
        store.record("explain hash maps", "alfred", "work", result_summary="ok")
        store.record("capture this note", "friday", "personal-token")
        rows = store.recent(limit=10)
        assert len(rows) == 2
        # most recent first
        assert rows[0]["agent"] == "friday"
        assert rows[1]["agent"] == "alfred"
        store.close()

    def test_recent_respects_limit(self, db_path):
        store = ContextStore(db_path)
        for i in range(5):
            store.record(f"request {i}", "friday", "personal-token")
        rows = store.recent(limit=2)
        assert len(rows) == 2
        store.close()

    def test_is_reachable(self, db_path):
        store = ContextStore(db_path)
        assert store.is_reachable() is True
        store.close()

    def test_persists_across_instances(self, db_path):
        store1 = ContextStore(db_path)
        store1.record("hello", "friday", "personal-token")
        store1.close()

        store2 = ContextStore(db_path)
        rows = store2.recent()
        assert len(rows) == 1
        store2.close()


class TestAuditLog:
    def test_record_allowed_and_refused(self, db_path):
        log = AuditLog(db_path)
        log.record("ultron", "private", True, reason="ok")
        log.record("friday", "private", False, reason="tier conflict")
        rows = log.recent(limit=10)
        assert len(rows) == 2
        assert rows[0]["agent"] == "friday"
        assert rows[0]["allowed"] == 0
        assert rows[1]["allowed"] == 1
        log.close()

    def test_detail_round_trips_as_json(self, db_path):
        log = AuditLog(db_path)
        log.record("friday", "work", True, detail={"matched_keywords": ["note"]})
        row = log.recent(limit=1)[0]
        import json

        assert json.loads(row["detail"]) == {"matched_keywords": ["note"]}
        log.close()

    def test_context_and_audit_share_file_but_separate_tables(self, db_path):
        ctx = ContextStore(db_path)
        audit = AuditLog(db_path)
        ctx.record("hi", "friday", "personal-token")
        audit.record("friday", "personal-token", True)

        conn = sqlite3.connect(str(db_path))
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "context_entries" in tables
        assert "audit_entries" in tables
        conn.close()
        ctx.close()
        audit.close()
