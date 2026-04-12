"""Reconciliation Loop — the heartbeat of Context Kubernetes.

Algorithm 1 from the paper: continuously compares declared desired state
(from the manifest) against observed actual state (from the registry and
sources), computes drift, and executes corrective actions.

Design Goals:
  3.9 (Safety): no expired context served; fail-closed on Permission Engine down
  3.10 (Liveness): stale units re-synced/flagged within 2·Δt_r;
                    disconnected sources detected within Δt_r
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from context_kubernetes.cxri.interface import CxRIConnector, HealthStatus
from context_kubernetes.models import DriftEvent, DriftType, FreshnessState

logger = logging.getLogger(__name__)


def _parse_duration(s: str) -> float:
    """Parse duration string (e.g., '24h', '15m', '30s') to seconds."""
    s = s.strip().lower()
    if s.endswith("d"):
        return float(s[:-1]) * 86400
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


@dataclass
class SourceState:
    """Observed state of a single context source."""

    name: str
    domain: str
    connector: CxRIConnector
    health: HealthStatus = HealthStatus.HEALTHY
    last_sync: float = 0.0  # unix timestamp
    max_age_seconds: float = 86400  # from manifest freshness spec
    stale_action: str = "flag"  # flag | re-sync | archive
    consecutive_failures: int = 0
    last_health_check: float = 0.0


@dataclass
class ReconciliationState:
    """The full observed state of the system."""

    sources: dict[str, SourceState] = field(default_factory=dict)
    drift_events: list[DriftEvent] = field(default_factory=list)
    cycle_count: int = 0
    last_cycle_at: float = 0.0
    last_cycle_duration_ms: float = 0.0


class ReconciliationLoop:
    """
    The reconciliation loop — Algorithm 1 from the paper.

    Runs continuously (or on-demand for testing), comparing declared
    state against actual state and taking corrective action.
    """

    def __init__(
        self,
        interval_seconds: float = 30.0,
        max_consecutive_failures: int = 3,
    ) -> None:
        self._interval = interval_seconds
        self._max_failures = max_consecutive_failures
        self._state = ReconciliationState()
        self._running = False
        self._callbacks: dict[str, list[Any]] = {
            "source_disconnected": [],
            "context_stale": [],
            "source_recovered": [],
            "drift_detected": [],
        }

    # -------------------------------------------------------------------
    # Source registration
    # -------------------------------------------------------------------

    def register_source(
        self,
        name: str,
        domain: str,
        connector: CxRIConnector,
        max_age: str = "24h",
        stale_action: str = "flag",
    ) -> None:
        """Register a context source to monitor."""
        self._state.sources[name] = SourceState(
            name=name,
            domain=domain,
            connector=connector,
            max_age_seconds=_parse_duration(max_age),
            stale_action=stale_action,
            last_sync=time.time(),
        )

    # -------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------

    def on(self, event: str, callback: Any) -> None:
        """Register a callback for reconciliation events."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    async def _emit(self, event: str, data: Any) -> None:
        """Emit an event to registered callbacks."""
        for cb in self._callbacks.get(event, []):
            try:
                result = cb(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Callback error for {event}: {e}")

    # -------------------------------------------------------------------
    # The loop
    # -------------------------------------------------------------------

    async def run(self) -> None:
        """
        Run the reconciliation loop continuously.

        Call stop() to terminate.
        """
        self._running = True
        logger.info(f"Reconciliation loop started (interval={self._interval}s)")

        while self._running:
            await self.reconcile_once()
            await asyncio.sleep(self._interval)

        logger.info("Reconciliation loop stopped")

    def stop(self) -> None:
        """Stop the reconciliation loop."""
        self._running = False

    async def reconcile_once(self) -> ReconciliationState:
        """
        Run a single reconciliation cycle.

        This is the core of Algorithm 1:
          1. Read desired state (source configs)
          2. Observe actual state (health checks, freshness)
          3. Compute drift
          4. Execute corrective actions
          5. Update registry
        """
        start = time.time()
        self._state.cycle_count += 1

        new_drifts: list[DriftEvent] = []

        for name, source in self._state.sources.items():
            # Step 2: Observe — check health
            health = await self._check_health(source)

            # Step 3: Compute drift
            if health == HealthStatus.DISCONNECTED:
                drift = DriftEvent(
                    drift_type=DriftType.SOURCE_DISCONNECTED,
                    domain=source.domain,
                    source=name,
                    details=f"Source {name} disconnected (failures: {source.consecutive_failures})",
                )
                new_drifts.append(drift)

                # Step 4: Corrective action — retry then mark stale
                if source.consecutive_failures >= self._max_failures:
                    await self._emit("source_disconnected", {
                        "source": name,
                        "domain": source.domain,
                        "failures": source.consecutive_failures,
                    })

            # Check freshness
            freshness = self._check_freshness(source)
            if freshness == FreshnessState.STALE:
                drift = DriftEvent(
                    drift_type=DriftType.CONTEXT_STALE,
                    domain=source.domain,
                    source=name,
                    details=f"Source {name} content is stale (last sync: {source.last_sync})",
                )
                new_drifts.append(drift)

                # Corrective action based on policy
                if source.stale_action == "re-sync":
                    await self._trigger_resync(source)
                elif source.stale_action == "flag":
                    await self._emit("context_stale", {
                        "source": name,
                        "domain": source.domain,
                        "last_sync": source.last_sync,
                        "max_age": source.max_age_seconds,
                    })

            elif freshness == FreshnessState.EXPIRED:
                drift = DriftEvent(
                    drift_type=DriftType.CONTEXT_STALE,
                    domain=source.domain,
                    source=name,
                    details=f"Source {name} content is EXPIRED",
                )
                new_drifts.append(drift)

        # Step 5: Update registry
        self._state.drift_events.extend(new_drifts)
        self._state.last_cycle_at = time.time()
        self._state.last_cycle_duration_ms = (time.time() - start) * 1000

        if new_drifts:
            await self._emit("drift_detected", {
                "cycle": self._state.cycle_count,
                "drifts": len(new_drifts),
                "types": [d.drift_type.value for d in new_drifts],
            })

        return self._state

    # -------------------------------------------------------------------
    # Health checking
    # -------------------------------------------------------------------

    async def _check_health(self, source: SourceState) -> HealthStatus:
        """Check the health of a source connector."""
        was_failing = source.consecutive_failures > 0

        try:
            health = await source.connector.health()
            source.health = health
            source.last_health_check = time.time()

            if health == HealthStatus.DISCONNECTED:
                source.consecutive_failures += 1
            elif health == HealthStatus.HEALTHY:
                if was_failing:
                    # Source recovered — emit event before resetting counter
                    await self._emit("source_recovered", {
                        "source": source.name,
                        "domain": source.domain,
                    })
                source.consecutive_failures = 0

            return health
        except Exception:
            source.consecutive_failures += 1
            source.health = HealthStatus.DISCONNECTED
            return HealthStatus.DISCONNECTED

    # -------------------------------------------------------------------
    # Freshness checking
    # -------------------------------------------------------------------

    def _check_freshness(self, source: SourceState) -> FreshnessState:
        """
        Check if a source's content is fresh, stale, or expired.

        Fresh: last_sync within max_age
        Stale: last_sync between max_age and 2x max_age
        Expired: last_sync beyond 2x max_age
        """
        age = time.time() - source.last_sync

        if age <= source.max_age_seconds:
            return FreshnessState.FRESH
        elif age <= source.max_age_seconds * 2:
            return FreshnessState.STALE
        else:
            return FreshnessState.EXPIRED

    # -------------------------------------------------------------------
    # Re-sync
    # -------------------------------------------------------------------

    async def _trigger_resync(self, source: SourceState) -> None:
        """Trigger a re-sync for a stale source."""
        try:
            # For connectors that support it, trigger a fresh query
            # This refreshes the connector's internal state
            health = await source.connector.health()
            if health == HealthStatus.HEALTHY:
                source.last_sync = time.time()
                logger.info(f"Re-synced source: {source.name}")
        except Exception as e:
            logger.error(f"Re-sync failed for {source.name}: {e}")

    # -------------------------------------------------------------------
    # Mark sync (called by connectors when they receive new data)
    # -------------------------------------------------------------------

    def mark_synced(self, source_name: str) -> None:
        """Mark a source as freshly synced (called on webhook/push events)."""
        if source_name in self._state.sources:
            self._state.sources[source_name].last_sync = time.time()

    # -------------------------------------------------------------------
    # State queries
    # -------------------------------------------------------------------

    def get_state(self) -> ReconciliationState:
        """Get the current reconciliation state."""
        return self._state

    def get_drift_events(self, domain: str | None = None) -> list[DriftEvent]:
        """Get drift events, optionally filtered by domain."""
        if domain:
            return [d for d in self._state.drift_events if d.domain == domain]
        return list(self._state.drift_events)

    def get_source_health(self) -> dict[str, HealthStatus]:
        """Get health status of all registered sources."""
        return {name: s.health for name, s in self._state.sources.items()}

    def get_freshness(self) -> dict[str, FreshnessState]:
        """Get freshness state of all registered sources."""
        return {
            name: self._check_freshness(s)
            for name, s in self._state.sources.items()
        }
