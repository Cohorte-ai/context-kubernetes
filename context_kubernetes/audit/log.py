"""Audit Log — immutable record of every system interaction.

Requirement R6 (Complete Auditability): every knowledge access,
every action, and every approval must be immutably logged with
attribution, timestamp, and outcome.

Two backends:
  - InMemoryAuditLog: for testing and prototype (list in memory)
  - FileAuditLog: append-only JSONL file (production-ready for single node)
  - PostgreSQL backend would be added for distributed deployment
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from context_kubernetes.models import AuditEvent


class InMemoryAuditLog:
    """
    In-memory audit log for testing.

    Append-only: events can be added and queried but never modified or deleted.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def log(self, event: AuditEvent) -> None:
        """Append an audit event."""
        if not event.event_id:
            event.event_id = f"evt-{int(time.time()*1000)}-{len(self._events)}"
        if not event.timestamp:
            event.timestamp = datetime.now(UTC)
        self._events.append(event)

    def query(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events with optional filters."""
        results = self._events

        if session_id:
            results = [e for e in results if e.session_id == session_id]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if since:
            results = [e for e in results if e.timestamp >= since]

        return results[-limit:]

    def count(self, event_type: str | None = None) -> int:
        """Count events, optionally filtered by type."""
        if event_type:
            return sum(1 for e in self._events if e.event_type == event_type)
        return len(self._events)

    def get_all(self) -> list[AuditEvent]:
        """Return all events (for testing)."""
        return list(self._events)


class FileAuditLog:
    """
    File-based append-only audit log.

    Writes events as JSONL (one JSON object per line) to a file.
    Append-only by design — the file is opened in append mode,
    events are never modified or deleted.

    For production: replace with PostgreSQL-backed log with
    immutable constraints and archive to object storage.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: AuditEvent) -> None:
        """Append an audit event to the log file."""
        if not event.event_id:
            event.event_id = f"evt-{int(time.time()*1000)}"
        if not event.timestamp:
            event.timestamp = datetime.now(UTC)

        line = event.model_dump_json() + "\n"
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line)

    def query(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query events from the log file."""
        if not self._path.exists():
            return []

        results: list[AuditEvent] = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = AuditEvent.model_validate_json(line)
                except Exception:
                    continue

                if session_id and event.session_id != session_id:
                    continue
                if user_id and event.user_id != user_id:
                    continue
                if event_type and event.event_type != event_type:
                    continue
                if since and event.timestamp < since:
                    continue

                results.append(event)

        return results[-limit:]

    def count(self, event_type: str | None = None) -> int:
        """Count events in the log file."""
        if not self._path.exists():
            return 0

        count = 0
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                if event_type:
                    try:
                        event = AuditEvent.model_validate_json(line)
                        if event.event_type == event_type:
                            count += 1
                    except Exception:
                        continue
                else:
                    count += 1
        return count

    def export_json(self, output_path: str | Path) -> int:
        """Export all events as a JSON array (for compliance reporting)."""
        events = self.query(limit=999999)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([e.model_dump(mode="json") for e in events], f, indent=2, default=str)
        return len(events)
