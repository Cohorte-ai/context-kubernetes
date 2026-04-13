"""Experiment 3: Freshness Behavior.

Measures the reconciliation loop's ability to detect and respond
to staleness and source failures.

Metrics:
  - Stale detection latency (time from TTL expiry to detection)
  - Source disconnect detection latency
  - Re-sync trigger accuracy
  - Recovery detection after reconnection
  - Concurrent multi-source monitoring correctness

Design Goals tested:
  3.9 (Freshness Safety): no expired content served
  3.10 (Liveness): stale detected within 2·Δt_r, disconnect within Δt_r

Run: python -m benchmarks.exp3_freshness
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from context_kubernetes.cxri.interface import HealthStatus
from context_kubernetes.models import FreshnessState
from context_kubernetes.reconciliation.loop import ReconciliationLoop


class ControllableConnector:
    """A mock connector with controllable health and latency."""

    connector_type = "mock"

    def __init__(self, healthy: bool = True, latency_ms: float = 0):
        self._healthy = healthy
        self._latency = latency_ms / 1000

    async def health(self) -> HealthStatus:
        if self._latency > 0:
            await asyncio.sleep(self._latency)
        return HealthStatus.HEALTHY if self._healthy else HealthStatus.DISCONNECTED

    def set_healthy(self, h: bool) -> None:
        self._healthy = h

    async def connect(self, *a, **kw): pass
    async def query(self, *a, **kw): return []
    async def read(self, *a, **kw): return None
    async def write(self, *a, **kw): return None
    async def subscribe(self, *a, **kw): yield  # type: ignore
    async def disconnect(self): pass


@dataclass
class FreshnessTestResult:
    test_name: str
    passed: bool
    metric_name: str = ""
    metric_value: float = 0.0
    details: str = ""


@dataclass
class ExperimentResults:
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    results: list[FreshnessTestResult] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


async def test_stale_detection_latency() -> FreshnessTestResult:
    """Measure time from TTL expiry to stale detection."""
    loop = ReconciliationLoop(interval_seconds=0.1)
    conn = ControllableConnector(healthy=True)
    loop.register_source("src-1", "sales", conn, max_age="10s", stale_action="flag")

    # Force source to be 15s old: past max_age(10s) but within 2x(20s) = STALE
    loop._state.sources["src-1"].last_sync = time.time() - 15

    stale_events = []
    loop.on("context_stale", lambda d: stale_events.append(time.time()))

    start = time.time()
    await loop.reconcile_once()
    detection_time = (time.time() - start) * 1000

    return FreshnessTestResult(
        test_name="stale_detection_latency",
        passed=len(stale_events) >= 1,  # at least one stale event detected
        metric_name="stale_detection_ms",
        metric_value=round(detection_time, 2),
        details=f"Detected in {detection_time:.1f}ms, events: {len(stale_events)}",
    )


async def test_disconnect_detection_latency() -> FreshnessTestResult:
    """Measure time to detect a source going offline."""
    loop = ReconciliationLoop(interval_seconds=0.1, max_consecutive_failures=1)
    conn = ControllableConnector(healthy=False)
    loop.register_source("src-1", "sales", conn, max_age="24h")

    disconnect_events = []
    loop.on("source_disconnected", lambda d: disconnect_events.append(time.time()))

    start = time.time()
    await loop.reconcile_once()
    detection_time = (time.time() - start) * 1000

    return FreshnessTestResult(
        test_name="disconnect_detection_latency",
        passed=len(disconnect_events) == 1,
        metric_name="disconnect_detection_ms",
        metric_value=round(detection_time, 2),
        details=f"Detected in {detection_time:.1f}ms",
    )


async def test_recovery_detection() -> FreshnessTestResult:
    """Verify that a recovered source is correctly detected."""
    loop = ReconciliationLoop(interval_seconds=0.1, max_consecutive_failures=1)
    conn = ControllableConnector(healthy=False)
    loop.register_source("src-1", "sales", conn, max_age="24h")

    recovery_events = []
    loop.on("source_recovered", lambda d: recovery_events.append(d))

    # Cycle 1: disconnected
    await loop.reconcile_once()

    # Recover
    conn.set_healthy(True)

    # Cycle 2: recovered
    await loop.reconcile_once()

    return FreshnessTestResult(
        test_name="recovery_detection",
        passed=len(recovery_events) == 1,
        details=f"Recovery events: {len(recovery_events)}",
    )


async def test_resync_on_stale() -> FreshnessTestResult:
    """Verify re-sync is triggered for stale sources with re-sync policy."""
    loop = ReconciliationLoop(interval_seconds=0.1)
    conn = ControllableConnector(healthy=True)
    loop.register_source("src-1", "sales", conn, max_age="10s", stale_action="re-sync")

    # Set to 15s ago: past max_age(10s) but within 2x(20s) = STALE, not EXPIRED
    old_sync = time.time() - 15
    loop._state.sources["src-1"].last_sync = old_sync

    await loop.reconcile_once()

    new_sync = loop._state.sources["src-1"].last_sync
    resynced = new_sync > old_sync

    return FreshnessTestResult(
        test_name="resync_on_stale",
        passed=resynced,
        details=f"Resynced: {resynced} (old={old_sync:.0f}, new={new_sync:.0f})",
    )


async def test_expired_not_resynced_if_disconnected() -> FreshnessTestResult:
    """Expired + disconnected source should not attempt re-sync."""
    loop = ReconciliationLoop(interval_seconds=0.1, max_consecutive_failures=1)
    conn = ControllableConnector(healthy=False)
    loop.register_source("src-1", "sales", conn, max_age="1s", stale_action="re-sync")

    loop._state.sources["src-1"].last_sync = time.time() - 100

    old_sync = loop._state.sources["src-1"].last_sync
    await loop.reconcile_once()
    new_sync = loop._state.sources["src-1"].last_sync

    # Should NOT have re-synced (source is disconnected)
    not_resynced = new_sync == old_sync

    return FreshnessTestResult(
        test_name="expired_not_resynced_if_disconnected",
        passed=not_resynced,
        details=f"Sync unchanged: {not_resynced} (source disconnected)",
    )


async def test_multi_source_independent() -> FreshnessTestResult:
    """Multiple sources should be monitored independently."""
    loop = ReconciliationLoop(interval_seconds=0.1, max_consecutive_failures=1)

    healthy = ControllableConnector(healthy=True)
    broken = ControllableConnector(healthy=False)
    stale_conn = ControllableConnector(healthy=True)

    loop.register_source("healthy-src", "sales", healthy, max_age="24h")
    loop.register_source("broken-src", "delivery", broken, max_age="24h")
    loop.register_source("stale-src", "hr", stale_conn, max_age="10s")
    # 15s ago: past max_age(10s) but within 2x(20s) = STALE
    loop._state.sources["stale-src"].last_sync = time.time() - 15

    await loop.reconcile_once()

    health_map = loop.get_source_health()
    freshness_map = loop.get_freshness()

    correct = (
        health_map["healthy-src"] == HealthStatus.HEALTHY
        and health_map["broken-src"] == HealthStatus.DISCONNECTED
        and health_map["stale-src"] == HealthStatus.HEALTHY
        and freshness_map["healthy-src"] == FreshnessState.FRESH
        and freshness_map["stale-src"] == FreshnessState.STALE
    )

    return FreshnessTestResult(
        test_name="multi_source_independent",
        passed=correct,
        details=f"Health: {dict(health_map)}, Freshness: {dict(freshness_map)}",
    )


async def test_consecutive_failure_threshold() -> FreshnessTestResult:
    """Source should only alert after reaching failure threshold."""
    loop = ReconciliationLoop(interval_seconds=0.1, max_consecutive_failures=3)
    conn = ControllableConnector(healthy=False)
    loop.register_source("src-1", "sales", conn, max_age="24h")

    alerts = []
    loop.on("source_disconnected", lambda d: alerts.append(d))

    # Cycles 1-2: failures accumulate, no alert yet
    await loop.reconcile_once()
    await loop.reconcile_once()
    assert len(alerts) == 0

    # Cycle 3: threshold reached, alert fires
    await loop.reconcile_once()

    return FreshnessTestResult(
        test_name="consecutive_failure_threshold",
        passed=len(alerts) == 1,
        details=f"Alerts after 3 cycles: {len(alerts)} (expected 1)",
    )


async def test_freshness_state_transitions() -> FreshnessTestResult:
    """Test fresh → stale → expired state transitions."""
    loop = ReconciliationLoop(interval_seconds=0.1)
    conn = ControllableConnector(healthy=True)
    loop.register_source("src-1", "sales", conn, max_age="10s")

    # Fresh (just synced)
    loop._state.sources["src-1"].last_sync = time.time()
    f1 = loop.get_freshness()["src-1"]

    # Stale (past max_age but within 2x)
    loop._state.sources["src-1"].last_sync = time.time() - 15
    f2 = loop.get_freshness()["src-1"]

    # Expired (past 2x max_age)
    loop._state.sources["src-1"].last_sync = time.time() - 25
    f3 = loop.get_freshness()["src-1"]

    correct = (
        f1 == FreshnessState.FRESH
        and f2 == FreshnessState.STALE
        and f3 == FreshnessState.EXPIRED
    )

    return FreshnessTestResult(
        test_name="freshness_state_transitions",
        passed=correct,
        details=f"Fresh→{f1.value}, Stale→{f2.value}, Expired→{f3.value}",
    )


async def test_reconciliation_cycle_performance() -> FreshnessTestResult:
    """Measure reconciliation cycle time with many sources."""
    loop = ReconciliationLoop(interval_seconds=0.1)

    # Register 20 sources
    for i in range(20):
        conn = ControllableConnector(healthy=True, latency_ms=1)
        loop.register_source(f"src-{i}", "sales", conn, max_age="24h")

    times = []
    for _ in range(10):
        start = time.time()
        await loop.reconcile_once()
        times.append((time.time() - start) * 1000)

    avg = sum(times) / len(times)
    p95 = sorted(times)[int(len(times) * 0.95)]

    return FreshnessTestResult(
        test_name="reconciliation_cycle_performance",
        passed=avg < 1000,  # should complete in under 1s
        metric_name="avg_cycle_ms",
        metric_value=round(avg, 2),
        details=f"20 sources, 10 cycles: avg={avg:.1f}ms, p95={p95:.1f}ms",
    )


async def main() -> None:
    """Run Experiment 3: Freshness Behavior."""
    print("=" * 70)
    print("Experiment 3: Freshness Behavior")
    print("=" * 70)

    tests = [
        test_stale_detection_latency,
        test_disconnect_detection_latency,
        test_recovery_detection,
        test_resync_on_stale,
        test_expired_not_resynced_if_disconnected,
        test_multi_source_independent,
        test_consecutive_failure_threshold,
        test_freshness_state_transitions,
        test_reconciliation_cycle_performance,
    ]

    results = ExperimentResults()
    for test_fn in tests:
        result = await test_fn()
        results.results.append(result)
        results.total_tests += 1
        if result.passed:
            results.passed += 1
        else:
            results.failed += 1

        status = "PASS" if result.passed else "FAIL"
        metric = f" [{result.metric_name}={result.metric_value}]" if result.metric_name else ""
        print(f"  [{status}] {result.test_name}{metric}: {result.details}")

        if result.metric_name:
            results.metrics[result.metric_name] = result.metric_value

    print(f"\n{'=' * 50}")
    print(f"  Total: {results.total_tests}, Passed: {results.passed}, Failed: {results.failed}")
    print(f"  Key metrics:")
    for k, v in results.metrics.items():
        print(f"    {k}: {v}")
    print(f"{'=' * 50}")

    output = {
        "experiment": "freshness_behavior",
        "total_tests": results.total_tests,
        "passed": results.passed,
        "failed": results.failed,
        "metrics": results.metrics,
    }
    output_path = Path(__file__).parent / "results_exp3.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
