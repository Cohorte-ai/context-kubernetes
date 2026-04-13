"""Experiment 4: Latency Overhead.

Measures end-to-end latency for context requests under varying conditions.

Conditions:
  (a) Single query — warm vs cold cache
  (b) Simple intent (single domain) vs cross-domain
  (c) Scaling: 1, 10, 50 concurrent queries

Metrics:
  - p50, p95, p99 latency (ms)
  - Throughput (queries/second)
  - Overhead vs direct file read

Run: python -m benchmarks.exp4_latency
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from git import Repo

from context_kubernetes.cxri.connectors.git_connector import GitConnector
from context_kubernetes.cxri.interface import ConnectionConfig
from context_kubernetes.models import ApprovalTier, ContextRequest, OperationPermission
from context_kubernetes.permissions.engine import PermissionEngine
from context_kubernetes.router.intent import IntentClassifier
from context_kubernetes.router.router import ContextRouter


@dataclass
class LatencyResult:
    condition: str
    num_queries: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    avg_ms: float
    min_ms: float
    max_ms: float
    throughput_qps: float  # queries per second


def _percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


async def _setup() -> tuple[str, PermissionEngine, ContextRouter]:
    seed_dir = Path(__file__).parent.parent / "seed_data" / "context"
    tmpdir = tempfile.mkdtemp(prefix="ck8s-lat-")
    repo = Repo.init(tmpdir)

    import shutil
    for item in seed_dir.iterdir():
        dest = Path(tmpdir) / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    repo.git.add(A=True)
    repo.index.commit("Seed")

    engine = PermissionEngine()
    engine.register_role("sales-rep", [
        OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS),
    ])
    engine.register_agent_profile(
        user_id="bench-user", role="sales-rep",
        agent_permissions=[
            OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        ],
        excluded_operations=["write"],
    )

    router = ContextRouter(
        permission_engine=engine,
        intent_classifier=IntentClassifier(
            available_domains=["sales", "delivery", "hr", "finance"],
        ),
    )

    for domain in ["sales", "delivery", "hr", "finance"]:
        conn = GitConnector()
        await conn.connect(ConnectionConfig(
            connector_type="git-repo", endpoint=tmpdir,
            extra={"domain": domain},
        ))
        router.register_connector(domain, conn)

    router.set_cross_domain_rules("sales", {"delivery", "finance"})

    return tmpdir, engine, router


async def measure_latency(
    router: ContextRouter, engine: PermissionEngine,
    queries: list[str], condition: str,
) -> LatencyResult:
    """Run queries sequentially and measure latency."""
    session = engine.create_session("bench-user", "agent-lat", "sales-rep")
    latencies: list[float] = []

    for query in queries:
        start = time.time()
        await router.route(ContextRequest(
            session_id=session.session_id, intent=query, token_budget=8000,
        ))
        latencies.append((time.time() - start) * 1000)

    total_time = sum(latencies) / 1000
    return LatencyResult(
        condition=condition,
        num_queries=len(latencies),
        p50_ms=round(_percentile(latencies, 0.50), 2),
        p95_ms=round(_percentile(latencies, 0.95), 2),
        p99_ms=round(_percentile(latencies, 0.99), 2),
        avg_ms=round(sum(latencies) / len(latencies), 2),
        min_ms=round(min(latencies), 2),
        max_ms=round(max(latencies), 2),
        throughput_qps=round(len(latencies) / total_time, 1) if total_time > 0 else 0,
    )


async def measure_concurrent(
    router: ContextRouter, engine: PermissionEngine,
    query: str, concurrency: int,
) -> LatencyResult:
    """Run N concurrent queries and measure latency."""
    session = engine.create_session("bench-user", f"agent-c{concurrency}", "sales-rep")

    async def single_query() -> float:
        start = time.time()
        await router.route(ContextRequest(
            session_id=session.session_id, intent=query, token_budget=8000,
        ))
        return (time.time() - start) * 1000

    start = time.time()
    latencies = await asyncio.gather(*[single_query() for _ in range(concurrency)])
    wall_time = time.time() - start

    return LatencyResult(
        condition=f"concurrent_{concurrency}",
        num_queries=concurrency,
        p50_ms=round(_percentile(list(latencies), 0.50), 2),
        p95_ms=round(_percentile(list(latencies), 0.95), 2),
        p99_ms=round(_percentile(list(latencies), 0.99), 2),
        avg_ms=round(sum(latencies) / len(latencies), 2),
        min_ms=round(min(latencies), 2),
        max_ms=round(max(latencies), 2),
        throughput_qps=round(concurrency / wall_time, 1),
    )


async def measure_direct_read(tmpdir: str, num_reads: int = 50) -> LatencyResult:
    """Baseline: direct file read without any routing."""
    files = list(Path(tmpdir).rglob("*.md"))
    latencies: list[float] = []

    for i in range(num_reads):
        f = files[i % len(files)]
        start = time.time()
        _ = f.read_text()
        latencies.append((time.time() - start) * 1000)

    return LatencyResult(
        condition="direct_file_read",
        num_queries=num_reads,
        p50_ms=round(_percentile(latencies, 0.50), 2),
        p95_ms=round(_percentile(latencies, 0.95), 2),
        p99_ms=round(_percentile(latencies, 0.99), 2),
        avg_ms=round(sum(latencies) / len(latencies), 2),
        min_ms=round(min(latencies), 2),
        max_ms=round(max(latencies), 2),
        throughput_qps=round(num_reads / (sum(latencies) / 1000), 1),
    )


def _print_result(r: LatencyResult) -> None:
    print(f"  {r.condition}:")
    print(f"    Queries: {r.num_queries}, Avg: {r.avg_ms:.1f}ms, "
          f"P50: {r.p50_ms:.1f}ms, P95: {r.p95_ms:.1f}ms, P99: {r.p99_ms:.1f}ms")
    print(f"    Min: {r.min_ms:.1f}ms, Max: {r.max_ms:.1f}ms, "
          f"Throughput: {r.throughput_qps:.1f} qps")


async def main() -> None:
    print("=" * 70)
    print("Experiment 4: Latency Overhead")
    print("=" * 70)

    tmpdir, engine, router = await _setup()
    all_results: list[LatencyResult] = []

    # Baseline: direct file read
    print("\n1. Baseline: Direct file read")
    r = await measure_direct_read(tmpdir)
    all_results.append(r)
    _print_result(r)

    # Cold cache: first batch of queries
    print("\n2. Cold cache: first-time queries")
    cold_queries = [
        "Henderson client status",
        "Sales pipeline Q2",
        "Globex proposal",
        "Remote work policy",
        "Q2 budget forecast",
    ] * 10  # 50 queries
    r = await measure_latency(router, engine, cold_queries, "cold_cache")
    all_results.append(r)
    _print_result(r)

    # Warm cache: repeat same queries
    print("\n3. Warm cache: repeated queries (intent cache populated)")
    r = await measure_latency(router, engine, cold_queries, "warm_cache")
    all_results.append(r)
    _print_result(r)

    # Simple vs cross-domain
    print("\n4. Simple single-domain queries")
    simple = ["Henderson client profile", "Sales pipeline", "HR vacation policy"] * 15
    r = await measure_latency(router, engine, simple, "simple_single_domain")
    all_results.append(r)
    _print_result(r)

    print("\n5. Cross-domain queries")
    cross = ["Henderson delivery timeline for the deal", "Budget impact of Henderson delay"] * 20
    r = await measure_latency(router, engine, cross, "cross_domain")
    all_results.append(r)
    _print_result(r)

    # Concurrency scaling
    for c in [1, 10, 50]:
        print(f"\n6. Concurrent: {c} simultaneous queries")
        r = await measure_concurrent(router, engine, "Henderson status", c)
        all_results.append(r)
        _print_result(r)

    # Summary
    print(f"\n{'=' * 60}")
    print("Summary — Latency overhead vs direct read:")
    direct = all_results[0]
    for r in all_results[1:]:
        overhead = r.avg_ms - direct.avg_ms
        print(f"  {r.condition}: +{overhead:.1f}ms overhead (avg)")
    print(f"{'=' * 60}")

    # Save
    output = {
        "experiment": "latency_overhead",
        "results": [
            {
                "condition": r.condition,
                "num_queries": r.num_queries,
                "avg_ms": r.avg_ms,
                "p50_ms": r.p50_ms,
                "p95_ms": r.p95_ms,
                "p99_ms": r.p99_ms,
                "throughput_qps": r.throughput_qps,
            }
            for r in all_results
        ],
    }
    output_path = Path(__file__).parent / "results_exp4.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
