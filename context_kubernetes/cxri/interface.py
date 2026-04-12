"""CxRI: The Context Runtime Interface.

Definition 3.5 from the paper:

    connect(φ) → Connection
    query(conn, q) → {u₁, ..., uₙ}
    read(conn, path) → u
    write(conn, path, c) → Result
    subscribe(conn, path) → Stream
    health(conn) → Status

Every context source — git repos, PostgreSQL, Gmail, Salesforce, Slack —
implements this interface. The orchestration layer never talks to raw systems.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

from context_kubernetes.models import ContextUnit


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


@dataclass
class ConnectionConfig:
    """Connection specification φ for a context store."""

    connector_type: str  # "git", "postgresql", "gmail", etc.
    endpoint: str  # URL, connection string, or path
    credentials_ref: str = ""  # vault reference, e.g. "vault://gmail/oauth"
    scope: str = ""  # optional query scope filter
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class WriteResult:
    """Result of a write operation."""

    success: bool
    version: str = ""  # new version after write (e.g., git commit hash)
    message: str = ""


@dataclass
class ChangeEvent:
    """A single change detected by subscribe()."""

    path: str
    change_type: str  # "created" | "modified" | "deleted"
    timestamp: float
    new_version: str = ""


class CxRIConnector(ABC):
    """
    Abstract base class for all CxRI connectors.

    Analogous to Kubernetes' Container Runtime Interface (CRI):
    it abstracts away the specifics of each backing system, allowing
    the orchestration layer to work with any data source through
    a uniform interface.

    Every connector implementation must handle:
    - Authentication to the source system
    - Data format translation to ContextUnit
    - Error handling and retry logic
    - Rate limiting (respecting the source system's limits)
    """

    connector_type: str = "base"

    @abstractmethod
    async def connect(self, config: ConnectionConfig) -> None:
        """
        Establish connection to the context store.

        Raises ConnectionError if the store is unreachable.
        """
        ...

    @abstractmethod
    async def query(self, intent: str, **filters: Any) -> list[ContextUnit]:
        """
        Query the store by semantic intent.

        Returns context units matching the intent, ordered by relevance.
        The connector handles translating the intent into source-specific queries.
        """
        ...

    @abstractmethod
    async def read(self, path: str) -> ContextUnit | None:
        """
        Read a specific context unit by path.

        Returns None if the path does not exist.
        """
        ...

    @abstractmethod
    async def write(self, path: str, content: str, message: str = "") -> WriteResult:
        """
        Write content to the store at the given path.

        For git stores, `message` becomes the commit message.
        Returns a WriteResult with the new version identifier.
        """
        ...

    @abstractmethod
    async def subscribe(self, path_pattern: str) -> AsyncIterator[ChangeEvent]:
        """
        Subscribe to changes at paths matching the pattern.

        Yields ChangeEvents as they occur. For git stores, this
        is triggered by webhooks on push. For databases, by
        LISTEN/NOTIFY or polling.
        """
        ...
        # Make this a valid async generator signature
        if False:
            yield  # pragma: no cover

    @abstractmethod
    async def health(self) -> HealthStatus:
        """
        Check the health of the connection.

        Returns HEALTHY, DEGRADED, or DISCONNECTED.
        Called by the Freshness Manager during reconciliation.
        """
        ...

    async def disconnect(self) -> None:
        """Clean up connection resources."""
        pass

    async def __aenter__(self) -> CxRIConnector:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
