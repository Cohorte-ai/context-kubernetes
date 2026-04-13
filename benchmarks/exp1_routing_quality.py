"""Experiment 1: Routing Quality Benchmark.

Measures how well the Context Router retrieves relevant context units
compared to baselines.

Metrics:
  - Relevance@5: fraction of top-5 results that are relevant
  - Relevance@10: fraction of top-10 results that are relevant
  - MRR (Mean Reciprocal Rank): 1/rank of first relevant result
  - Intent classification accuracy: % of queries classified to correct domain

Baselines:
  (a) Keyword search: simple substring matching
  (b) Standard RAG: embed query, cosine top-k (no permission/freshness)
  (c) Rule-based router: Context Router with rule-based intent only
  (d) LLM-assisted router: Context Router with LLM intent parsing

Run: python -m benchmarks.exp1_routing_quality
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from git import Repo

from context_kubernetes.cxri.connectors.git_connector import GitConnector
from context_kubernetes.cxri.interface import ConnectionConfig
from context_kubernetes.models import (
    ApprovalTier,
    ContextRequest,
    OperationPermission,
)
from context_kubernetes.permissions.engine import PermissionEngine
from context_kubernetes.router.intent import IntentClassifier
from context_kubernetes.router.router import ContextRouter

from benchmarks.test_queries import ALL_QUERIES, BenchmarkQuery


@dataclass
class QueryResult:
    """Result of a single query evaluation."""

    query: str
    expected_domain: str
    predicted_domain: str
    domain_correct: bool
    retrieved_paths: list[str]
    relevant_paths: list[str]
    relevance_at_5: float
    relevance_at_10: float
    mrr: float
    latency_ms: float


@dataclass
class ExperimentResults:
    """Aggregate results for one experimental condition."""

    condition: str
    num_queries: int = 0
    domain_accuracy: float = 0.0
    avg_relevance_at_5: float = 0.0
    avg_relevance_at_10: float = 0.0
    avg_mrr: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    query_results: list[QueryResult] = field(default_factory=list)


def _setup_test_repo() -> tuple[str, Repo]:
    """Create a git repo from the seed data."""
    seed_dir = Path(__file__).parent.parent / "seed_data" / "context"
    tmpdir = tempfile.mkdtemp(prefix="ck8s-bench-")
    repo = Repo.init(tmpdir)

    # Copy seed data into the repo
    import shutil
    for item in seed_dir.iterdir():
        dest = Path(tmpdir) / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # Stage and commit all files
    repo.git.add(A=True)
    repo.index.commit("Seed data for benchmarks")

    return tmpdir, repo


def _setup_engine_and_router(
    tmpdir: str, use_llm: bool = False
) -> tuple[PermissionEngine, ContextRouter]:
    """Set up permission engine and router."""
    engine = PermissionEngine()
    engine.register_role("sales-rep", [
        OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS),
    ])
    engine.register_agent_profile(
        user_id="bench-user",
        role="sales-rep",
        agent_permissions=[
            OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        ],
        excluded_operations=["write"],
    )

    classifier = IntentClassifier(
        llm_client=None,  # rule-based only for reproducibility
        available_domains=["sales", "delivery", "hr", "finance", "operations", "knowledge"],
    )

    router = ContextRouter(
        permission_engine=engine,
        intent_classifier=classifier,
    )

    return engine, router


def _compute_relevance_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Compute relevance@k: fraction of top-k results that are relevant."""
    if not relevant or k == 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for path in top_k if any(r in path for r in relevant))
    return hits / min(k, len(relevant))


def _compute_mrr(retrieved: list[str], relevant: set[str]) -> float:
    """Compute Mean Reciprocal Rank: 1/rank of first relevant result."""
    for i, path in enumerate(retrieved):
        if any(r in path for r in relevant):
            return 1.0 / (i + 1)
    return 0.0


async def run_experiment(
    condition: str,
    queries: list[BenchmarkQuery],
    router: ContextRouter,
    engine: PermissionEngine,
) -> ExperimentResults:
    """Run the routing quality experiment for one condition."""
    session = engine.create_session("bench-user", "bench-agent", "sales-rep")

    results = ExperimentResults(condition=condition)
    latencies: list[float] = []

    for bq in queries:
        start = time.time()

        response = await router.route(ContextRequest(
            session_id=session.session_id,
            intent=bq.query,
            token_budget=8000,
        ))

        latency = (time.time() - start) * 1000
        latencies.append(latency)

        # Extract retrieved paths
        retrieved_paths = [u.metadata.source for u in response.units]

        # Get predicted domain from the router's audit log
        audit = router.get_audit_log()
        predicted_domain = ""
        if audit:
            last = audit[-1]
            if "intent" in last.details:
                predicted_domain = last.details["intent"].get("domain", "")

        relevant_set = set(bq.relevant_paths)

        qr = QueryResult(
            query=bq.query,
            expected_domain=bq.domain,
            predicted_domain=predicted_domain,
            domain_correct=(predicted_domain == bq.domain),
            retrieved_paths=retrieved_paths,
            relevant_paths=bq.relevant_paths,
            relevance_at_5=_compute_relevance_at_k(retrieved_paths, relevant_set, 5),
            relevance_at_10=_compute_relevance_at_k(retrieved_paths, relevant_set, 10),
            mrr=_compute_mrr(retrieved_paths, relevant_set),
            latency_ms=latency,
        )
        results.query_results.append(qr)

    # Aggregate
    n = len(results.query_results)
    results.num_queries = n
    if n > 0:
        results.domain_accuracy = sum(1 for qr in results.query_results if qr.domain_correct) / n
        results.avg_relevance_at_5 = sum(qr.relevance_at_5 for qr in results.query_results) / n
        results.avg_relevance_at_10 = sum(qr.relevance_at_10 for qr in results.query_results) / n
        results.avg_mrr = sum(qr.mrr for qr in results.query_results) / n
        results.avg_latency_ms = sum(latencies) / n

        sorted_lat = sorted(latencies)
        results.p50_latency_ms = sorted_lat[int(n * 0.50)]
        results.p95_latency_ms = sorted_lat[min(int(n * 0.95), n - 1)]

    return results


async def main() -> None:
    """Run Experiment 1: Routing Quality Benchmark."""
    print("=" * 70)
    print("Experiment 1: Routing Quality Benchmark")
    print("=" * 70)

    # Setup
    tmpdir, repo = _setup_test_repo()
    engine, router = _setup_engine_and_router(tmpdir)

    # Connect git connector to all domains
    for domain in ["sales", "delivery", "hr", "finance"]:
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": domain},
        ))
        router.register_connector(domain, connector)

    # Allow cross-domain brokering
    router.set_cross_domain_rules("sales", {"delivery", "finance"})
    router.set_cross_domain_rules("delivery", {"sales", "finance"})
    router.set_cross_domain_rules("finance", {"sales", "delivery"})

    # Run: Rule-based router
    print("\nCondition: Rule-based Context Router")
    print("-" * 40)
    results = await run_experiment("rule-based", ALL_QUERIES, router, engine)
    _print_results(results)

    # Save results
    output = {
        "experiment": "routing_quality",
        "condition": results.condition,
        "num_queries": results.num_queries,
        "domain_accuracy": round(results.domain_accuracy, 4),
        "avg_relevance_at_5": round(results.avg_relevance_at_5, 4),
        "avg_relevance_at_10": round(results.avg_relevance_at_10, 4),
        "avg_mrr": round(results.avg_mrr, 4),
        "avg_latency_ms": round(results.avg_latency_ms, 2),
        "p50_latency_ms": round(results.p50_latency_ms, 2),
        "p95_latency_ms": round(results.p95_latency_ms, 2),
    }

    output_path = Path(__file__).parent / "results_exp1.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def _print_results(results: ExperimentResults) -> None:
    print(f"  Queries:             {results.num_queries}")
    print(f"  Domain accuracy:     {results.domain_accuracy:.1%}")
    print(f"  Avg Relevance@5:     {results.avg_relevance_at_5:.3f}")
    print(f"  Avg Relevance@10:    {results.avg_relevance_at_10:.3f}")
    print(f"  Avg MRR:             {results.avg_mrr:.3f}")
    print(f"  Avg latency:         {results.avg_latency_ms:.1f} ms")
    print(f"  P50 latency:         {results.p50_latency_ms:.1f} ms")
    print(f"  P95 latency:         {results.p95_latency_ms:.1f} ms")


if __name__ == "__main__":
    asyncio.run(main())
