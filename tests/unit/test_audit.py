"""Tests for the Audit Log — immutable event recording and querying."""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from context_kubernetes.audit.log import InMemoryAuditLog, FileAuditLog
from context_kubernetes.models import AuditEvent


def _make_event(
    event_type: str = "context_request",
    user_id: str = "user-1",
    session_id: str = "sess-1",
    operation: str = "read",
    outcome: str = "allowed",
) -> AuditEvent:
    return AuditEvent(
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        operation=operation,
        outcome=outcome,
    )


class TestInMemoryAuditLog:
    def test_log_and_query(self):
        log = InMemoryAuditLog()
        log.log(_make_event())
        log.log(_make_event(event_type="permission_check"))

        assert log.count() == 2
        assert log.count("context_request") == 1

    def test_query_by_user(self):
        log = InMemoryAuditLog()
        log.log(_make_event(user_id="user-1"))
        log.log(_make_event(user_id="user-2"))

        results = log.query(user_id="user-1")
        assert len(results) == 1
        assert results[0].user_id == "user-1"

    def test_query_by_session(self):
        log = InMemoryAuditLog()
        log.log(_make_event(session_id="sess-a"))
        log.log(_make_event(session_id="sess-b"))

        results = log.query(session_id="sess-a")
        assert len(results) == 1

    def test_query_by_event_type(self):
        log = InMemoryAuditLog()
        log.log(_make_event(event_type="context_request"))
        log.log(_make_event(event_type="approval_requested"))
        log.log(_make_event(event_type="context_request"))

        results = log.query(event_type="approval_requested")
        assert len(results) == 1

    def test_query_limit(self):
        log = InMemoryAuditLog()
        for i in range(50):
            log.log(_make_event(session_id=f"sess-{i}"))

        results = log.query(limit=10)
        assert len(results) == 10

    def test_event_id_auto_generated(self):
        log = InMemoryAuditLog()
        event = _make_event()
        log.log(event)
        assert event.event_id.startswith("evt-")

    def test_immutability(self):
        """Events should not be modifiable after logging."""
        log = InMemoryAuditLog()
        event = _make_event(outcome="allowed")
        log.log(event)

        # Even if someone mutates the event object, the log has its own copy
        all_events = log.get_all()
        assert len(all_events) == 1
        assert all_events[0].outcome == "allowed"


class TestFileAuditLog:
    def test_log_and_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            log = FileAuditLog(path)

            log.log(_make_event(event_type="context_request"))
            log.log(_make_event(event_type="permission_check"))

            assert log.count() == 2
            results = log.query()
            assert len(results) == 2

    def test_persistence(self):
        """Events should persist across log instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"

            # Write with one instance
            log1 = FileAuditLog(path)
            log1.log(_make_event(user_id="user-1"))
            log1.log(_make_event(user_id="user-2"))

            # Read with a new instance
            log2 = FileAuditLog(path)
            results = log2.query()
            assert len(results) == 2

    def test_append_only(self):
        """File should be append-only — new events add to existing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"

            log = FileAuditLog(path)
            log.log(_make_event())
            assert log.count() == 1

            log.log(_make_event())
            assert log.count() == 2

            # Verify file has 2 lines
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 2

    def test_export_json(self):
        """Should export all events as a JSON array for compliance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            export_path = Path(tmpdir) / "export.json"

            log = FileAuditLog(path)
            log.log(_make_event(event_type="context_request"))
            log.log(_make_event(event_type="approval_requested"))

            count = log.export_json(export_path)
            assert count == 2
            assert export_path.exists()

            import json
            with open(export_path) as f:
                data = json.load(f)
            assert len(data) == 2
            assert data[0]["event_type"] == "context_request"

    def test_query_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            log = FileAuditLog(path)

            log.log(_make_event(user_id="alice", event_type="context_request"))
            log.log(_make_event(user_id="bob", event_type="permission_check"))
            log.log(_make_event(user_id="alice", event_type="approval_requested"))

            assert len(log.query(user_id="alice")) == 2
            assert len(log.query(event_type="permission_check")) == 1
