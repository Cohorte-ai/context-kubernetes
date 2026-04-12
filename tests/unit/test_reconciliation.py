"""Tests for the Reconciliation Loop — freshness, drift detection, corrective actions."""

import time
import tempfile

import pytest
from git import Repo

from context_kubernetes.cxri.connectors.git_connector import GitConnector
from context_kubernetes.cxri.interface import ConnectionConfig, HealthStatus
from context_kubernetes.models import DriftType, FreshnessState
from context_kubernetes.reconciliation.loop import ReconciliationLoop


class MockConnector(GitConnector):
    """A connector we can control for testing."""

    def __init__(self, healthy: bool = True):
        super().__init__()
        self._mock_healthy = healthy

    async def health(self) -> HealthStatus:
        return HealthStatus.HEALTHY if self._mock_healthy else HealthStatus.DISCONNECTED

    def set_healthy(self, healthy: bool) -> None:
        self._mock_healthy = healthy


class TestReconciliationLoop:
    @pytest.mark.asyncio
    async def test_healthy_source_no_drift(self):
        """A healthy, fresh source should produce no drift events."""
        loop = ReconciliationLoop(interval_seconds=1)
        connector = MockConnector(healthy=True)

        loop.register_source("git-sales", "sales", connector, max_age="24h")

        state = await loop.reconcile_once()
        assert state.cycle_count == 1
        assert len(state.drift_events) == 0

    @pytest.mark.asyncio
    async def test_disconnected_source_detected(self):
        """A disconnected source should be detected as drift."""
        loop = ReconciliationLoop(interval_seconds=1, max_consecutive_failures=1)
        connector = MockConnector(healthy=False)

        loop.register_source("git-sales", "sales", connector, max_age="24h")

        state = await loop.reconcile_once()
        disconnected = [d for d in state.drift_events if d.drift_type == DriftType.SOURCE_DISCONNECTED]
        assert len(disconnected) == 1
        assert disconnected[0].source == "git-sales"

    @pytest.mark.asyncio
    async def test_stale_source_detected(self):
        """A source past its max_age should be flagged as stale."""
        loop = ReconciliationLoop(interval_seconds=1)
        connector = MockConnector(healthy=True)

        loop.register_source("git-sales", "sales", connector, max_age="1s")
        # Force stale by backdating last_sync
        loop._state.sources["git-sales"].last_sync = time.time() - 10

        state = await loop.reconcile_once()
        stale = [d for d in state.drift_events if d.drift_type == DriftType.CONTEXT_STALE]
        assert len(stale) == 1

    @pytest.mark.asyncio
    async def test_expired_source_detected(self):
        """A source past 2x max_age should be expired."""
        loop = ReconciliationLoop(interval_seconds=1)
        connector = MockConnector(healthy=True)

        loop.register_source("git-sales", "sales", connector, max_age="1s")
        # Force expired (> 2x max_age)
        loop._state.sources["git-sales"].last_sync = time.time() - 100

        freshness = loop.get_freshness()
        assert freshness["git-sales"] == FreshnessState.EXPIRED

    @pytest.mark.asyncio
    async def test_mark_synced_resets_freshness(self):
        """Marking a source as synced should reset its freshness."""
        loop = ReconciliationLoop(interval_seconds=1)
        connector = MockConnector(healthy=True)

        loop.register_source("git-sales", "sales", connector, max_age="1s")
        loop._state.sources["git-sales"].last_sync = time.time() - 100

        assert loop.get_freshness()["git-sales"] == FreshnessState.EXPIRED

        loop.mark_synced("git-sales")
        assert loop.get_freshness()["git-sales"] == FreshnessState.FRESH

    @pytest.mark.asyncio
    async def test_source_recovery_detected(self):
        """A source that recovers should emit a recovery event."""
        loop = ReconciliationLoop(interval_seconds=1, max_consecutive_failures=1)
        connector = MockConnector(healthy=False)
        loop.register_source("git-sales", "sales", connector, max_age="24h")

        recovered = []
        loop.on("source_recovered", lambda data: recovered.append(data))

        # First cycle: disconnected — accumulates failures
        await loop.reconcile_once()
        # Manually set failures > 0 to ensure recovery is detected
        loop._state.sources["git-sales"].consecutive_failures = 2

        # Fix the connector
        connector.set_healthy(True)

        # Second cycle: recovered (health returns HEALTHY, consecutive_failures was > 0)
        await loop.reconcile_once()
        assert len(recovered) == 1
        assert recovered[0]["source"] == "git-sales"

    @pytest.mark.asyncio
    async def test_callbacks_fire_on_disconnect(self):
        """Callbacks should fire when a source disconnects."""
        loop = ReconciliationLoop(interval_seconds=1, max_consecutive_failures=1)
        connector = MockConnector(healthy=False)
        loop.register_source("git-sales", "sales", connector, max_age="24h")

        events = []
        loop.on("source_disconnected", lambda data: events.append(data))

        await loop.reconcile_once()
        assert len(events) == 1
        assert events[0]["source"] == "git-sales"

    @pytest.mark.asyncio
    async def test_callbacks_fire_on_stale(self):
        """Callbacks should fire when content becomes stale."""
        loop = ReconciliationLoop(interval_seconds=1)
        connector = MockConnector(healthy=True)
        loop.register_source("git-sales", "sales", connector, max_age="10s", stale_action="flag")
        # Set last_sync to 15s ago: past max_age (10s) but within 2x max_age (20s) = STALE
        loop._state.sources["git-sales"].last_sync = time.time() - 15

        events = []
        loop.on("context_stale", lambda data: events.append(data))

        await loop.reconcile_once()
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_cycle_timing(self):
        """Reconciliation cycle should track timing."""
        loop = ReconciliationLoop(interval_seconds=1)
        connector = MockConnector(healthy=True)
        loop.register_source("git-sales", "sales", connector, max_age="24h")

        state = await loop.reconcile_once()
        assert state.last_cycle_duration_ms > 0
        assert state.last_cycle_at > 0

    @pytest.mark.asyncio
    async def test_multiple_sources(self):
        """Should monitor multiple sources independently."""
        loop = ReconciliationLoop(interval_seconds=1, max_consecutive_failures=1)

        healthy_conn = MockConnector(healthy=True)
        broken_conn = MockConnector(healthy=False)

        loop.register_source("git-sales", "sales", healthy_conn, max_age="24h")
        loop.register_source("pg-finance", "finance", broken_conn, max_age="1h")

        state = await loop.reconcile_once()

        health = loop.get_source_health()
        assert health["git-sales"] == HealthStatus.HEALTHY
        assert health["pg-finance"] == HealthStatus.DISCONNECTED

    def test_parse_duration(self):
        """Duration parsing should handle all formats."""
        from context_kubernetes.reconciliation.loop import _parse_duration
        assert _parse_duration("30s") == 30
        assert _parse_duration("15m") == 900
        assert _parse_duration("24h") == 86400
        assert _parse_duration("7d") == 604800
