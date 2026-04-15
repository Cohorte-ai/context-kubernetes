"""Track 1 Full Experiment: Rule-Based vs LLM-Assisted Routing.

Runs the complete routing quality + governed vs ungoverned comparison
with BOTH intent classification modes side by side.

This is the experiment that transforms V1 from "modest" to "dramatic."

Usage:
  python -m benchmarks.exp_track1_full

Requires: OPENAI_API_KEY environment variable set.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

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
from context_kubernetes.router.ranking import RankingEngine
from context_kubernetes.router.router import ContextRouter

from benchmarks.test_queries import BenchmarkQuery
from benchmarks.test_queries_expanded import ALL_QUERIES_200 as ALL_QUERIES


@dataclass
class RoutingResult:
    condition: str
    num_queries: int = 0
    domain_accuracy: float = 0.0
    avg_mrr: float = 0.0
    avg_relevance_at_5: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0


@dataclass
class GovernanceResult:
    condition: str
    num_queries: int = 0
    avg_precision: float = 0.0
    avg_noise_ratio: float = 0.0
    avg_leak_rate: float = 0.0
    total_leaks: int = 0
    token_waste_pct: float = 0.0


def _setup_repo() -> str:
    """Create git repo from seed data."""
    seed_dir = Path(__file__).parent.parent / "seed_data" / "context"
    tmpdir = tempfile.mkdtemp(prefix="ck8s-track1-")
    repo = Repo.init(tmpdir)
    for item in seed_dir.iterdir():
        dest = Path(tmpdir) / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    repo.git.add(A=True)
    repo.index.commit("Seed")
    return tmpdir


def _setup_engine() -> PermissionEngine:
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
    return engine


async def _connect_repo(tmpdir: str, domain_roles: dict | None = None) -> list[GitConnector]:
    """Connect git connectors for all domains."""
    connectors = []
    for domain in ["sales", "delivery", "hr", "finance"]:
        conn = GitConnector()
        extra = {"domain": domain}
        if domain_roles:
            extra["authorized_roles"] = domain_roles.get(domain, [])
        await conn.connect(ConnectionConfig(
            connector_type="git-repo", endpoint=tmpdir, extra=extra,
        ))
        connectors.append((domain, conn))
    return connectors


def _compute_relevance_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant or k == 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for path in top_k if any(r in path for r in relevant))
    return hits / min(k, len(relevant))


def _compute_mrr(retrieved: list[str], relevant: set[str]) -> float:
    for i, path in enumerate(retrieved):
        if any(r in path for r in relevant):
            return 1.0 / (i + 1)
    return 0.0


def _is_relevant(unit, query: BenchmarkQuery) -> bool:
    source = unit.metadata.source.replace("git:", "")
    return any(rp in source or source in rp for rp in query.relevant_paths)


def _is_leaked(unit, role: str, domain_roles: dict) -> bool:
    source = unit.metadata.source.lower()
    for domain, roles in domain_roles.items():
        if domain in source and role not in roles:
            return True
    return False


# -----------------------------------------------------------------------
# Routing Quality (C1 equivalent)
# -----------------------------------------------------------------------

async def run_routing_quality(
    router: ContextRouter,
    engine: PermissionEngine,
    queries: list[BenchmarkQuery],
    condition: str,
) -> RoutingResult:
    """Measure routing quality: domain accuracy, MRR, relevance@k."""
    session = engine.create_session("bench-user", f"agent-{condition}", "sales-rep")
    result = RoutingResult(condition=condition)
    latencies = []
    domain_correct = 0
    mrrs = []
    rel5s = []

    for bq in queries:
        start = time.time()
        response = await router.route(ContextRequest(
            session_id=session.session_id, intent=bq.query, token_budget=8000,
        ))
        latency = (time.time() - start) * 1000
        latencies.append(latency)

        retrieved = [u.metadata.source for u in response.units]
        relevant = set(bq.relevant_paths)

        # Domain accuracy from audit log
        audit = router.get_audit_log()
        if audit:
            last = audit[-1]
            if "intent" in last.details:
                predicted = last.details["intent"].get("domain", "")
                if predicted == bq.domain:
                    domain_correct += 1

        mrrs.append(_compute_mrr(retrieved, relevant))
        rel5s.append(_compute_relevance_at_k(retrieved, relevant, 5))

    n = len(queries)
    result.num_queries = n
    result.domain_accuracy = domain_correct / n if n > 0 else 0
    result.avg_mrr = sum(mrrs) / n if n > 0 else 0
    result.avg_relevance_at_5 = sum(rel5s) / n if n > 0 else 0
    result.avg_latency_ms = sum(latencies) / n if n > 0 else 0
    sorted_lat = sorted(latencies)
    result.p50_latency_ms = sorted_lat[int(n * 0.50)] if n > 0 else 0
    result.p95_latency_ms = sorted_lat[min(int(n * 0.95), n - 1)] if n > 0 else 0

    return result


# -----------------------------------------------------------------------
# Governed vs Ungoverned (V1 equivalent)
# -----------------------------------------------------------------------

async def run_governance_comparison(
    governed_router: ContextRouter,
    ungoverned_conn: GitConnector,
    engine: PermissionEngine,
    queries: list[BenchmarkQuery],
    domain_roles: dict,
    condition_prefix: str,
) -> tuple[GovernanceResult, GovernanceResult]:
    """Compare governed vs ungoverned context delivery."""
    session = engine.create_session("bench-user", f"agent-gov-{condition_prefix}", "sales-rep")

    gov = GovernanceResult(condition=f"{condition_prefix}_governed")
    ungov = GovernanceResult(condition=f"{condition_prefix}_ungoverned")

    for bq in queries:
        # Governed
        resp = await governed_router.route(ContextRequest(
            session_id=session.session_id, intent=bq.query, token_budget=8000,
        ))
        g_relevant = sum(1 for u in resp.units if _is_relevant(u, bq))
        g_leaked = sum(1 for u in resp.units if _is_leaked(u, "sales-rep", domain_roles))
        g_total = len(resp.units)
        g_tokens = resp.total_tokens
        g_rel_tokens = sum(u.token_count for u in resp.units if _is_relevant(u, bq))

        # Ungoverned
        ungov_units = await ungoverned_conn.query(bq.query, max_results=20)
        u_relevant = sum(1 for u in ungov_units if _is_relevant(u, bq))
        u_leaked = sum(1 for u in ungov_units if _is_leaked(u, "sales-rep", domain_roles))
        u_total = len(ungov_units)
        u_tokens = sum(u.token_count for u in ungov_units)
        u_rel_tokens = sum(u.token_count for u in ungov_units if _is_relevant(u, bq))

        # Accumulate governed
        gov.total_leaks += g_leaked
        if g_total > 0:
            gov.avg_precision += g_relevant / g_total
            gov.avg_noise_ratio += (g_total - g_relevant) / g_total
            gov.avg_leak_rate += g_leaked / g_total

        # Accumulate ungoverned
        ungov.total_leaks += u_leaked
        if u_total > 0:
            ungov.avg_precision += u_relevant / u_total
            ungov.avg_noise_ratio += (u_total - u_relevant) / u_total
            ungov.avg_leak_rate += u_leaked / u_total

    n = len(queries)
    gov.num_queries = n
    ungov.num_queries = n

    if n > 0:
        gov.avg_precision /= n
        gov.avg_noise_ratio /= n
        gov.avg_leak_rate /= n
        ungov.avg_precision /= n
        ungov.avg_noise_ratio /= n
        ungov.avg_leak_rate /= n

    return gov, ungov


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

async def main() -> None:
    print("=" * 70)
    print("  TRACK 1: Rule-Based vs LLM-Assisted — Full Comparison")
    print("=" * 70)

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set. Create a .env file or export the variable.")
        return

    tmpdir = _setup_repo()
    engine = _setup_engine()

    domain_roles = {
        "clients": ["sales-rep", "sales-manager", "finance-manager"],
        "sales": ["sales-rep", "sales-manager"],
        "delivery": ["sales-rep", "sales-manager", "delivery-lead"],
        "hr": ["hr-admin"],
        "finance": ["finance-manager", "sales-manager"],
    }

    # Connect governed connectors (with auth roles)
    gov_connectors = await _connect_repo(tmpdir, domain_roles)

    # Ungoverned connector (no auth)
    ungov_conn = GitConnector()
    await ungov_conn.connect(ConnectionConfig(
        connector_type="git-repo", endpoint=tmpdir, extra={"domain": "all"},
    ))

    # --- MODE 1: Rule-based ---
    print("\n" + "=" * 50)
    print("  MODE 1: Rule-Based Intent Classification")
    print("=" * 50)

    rule_classifier = IntentClassifier(
        llm_client=None,
        available_domains=["sales", "delivery", "hr", "finance"],
    )
    rule_router = ContextRouter(permission_engine=engine, intent_classifier=rule_classifier)
    for domain, conn in gov_connectors:
        rule_router.register_connector(domain, conn)
    rule_router.set_cross_domain_rules("sales", {"delivery", "finance"})

    rule_routing = await run_routing_quality(rule_router, engine, ALL_QUERIES, "rule-based")
    rule_gov, rule_ungov = await run_governance_comparison(
        rule_router, ungov_conn, engine, ALL_QUERIES, domain_roles, "rule-based"
    )

    # --- MODE 2: LLM-assisted ---
    print("\n" + "=" * 50)
    print("  MODE 2: LLM-Assisted Intent Classification (gpt-4o-mini)")
    print("=" * 50)

    from openai import AsyncOpenAI
    llm_client = AsyncOpenAI()

    llm_classifier = IntentClassifier(
        llm_client=llm_client,
        llm_model="gpt-4o-mini",
        confidence_threshold=0.7,
        available_domains=["sales", "delivery", "hr", "finance"],
    )

    # Need fresh engine + router (sessions are per-router)
    engine2 = _setup_engine()
    llm_router = ContextRouter(permission_engine=engine2, intent_classifier=llm_classifier)
    gov_connectors2 = await _connect_repo(tmpdir, domain_roles)
    for domain, conn in gov_connectors2:
        llm_router.register_connector(domain, conn)
    llm_router.set_cross_domain_rules("sales", {"delivery", "finance"})

    llm_routing = await run_routing_quality(llm_router, engine2, ALL_QUERIES, "llm-assisted")
    llm_gov, llm_ungov = await run_governance_comparison(
        llm_router, ungov_conn, engine2, ALL_QUERIES, domain_roles, "llm-assisted"
    )

    # --- RESULTS ---
    print("\n" + "=" * 70)
    print("  RESULTS: Rule-Based vs LLM-Assisted")
    print("=" * 70)

    print(f"\n  {'Metric':<35} {'Rule-Based':>12} {'LLM-Assisted':>14} {'Delta':>10}")
    print(f"  {'-'*71}")

    print(f"  {'Domain accuracy':<35} {rule_routing.domain_accuracy:>11.1%} {llm_routing.domain_accuracy:>13.1%} {(llm_routing.domain_accuracy - rule_routing.domain_accuracy):>+9.1%}")
    print(f"  {'MRR':<35} {rule_routing.avg_mrr:>12.3f} {llm_routing.avg_mrr:>14.3f} {(llm_routing.avg_mrr - rule_routing.avg_mrr):>+10.3f}")
    print(f"  {'Relevance@5':<35} {rule_routing.avg_relevance_at_5:>12.3f} {llm_routing.avg_relevance_at_5:>14.3f} {(llm_routing.avg_relevance_at_5 - rule_routing.avg_relevance_at_5):>+10.3f}")
    print(f"  {'Avg latency (ms)':<35} {rule_routing.avg_latency_ms:>11.1f} {llm_routing.avg_latency_ms:>13.1f} {(llm_routing.avg_latency_ms - rule_routing.avg_latency_ms):>+9.1f}")
    print(f"  {'P95 latency (ms)':<35} {rule_routing.p95_latency_ms:>11.1f} {llm_routing.p95_latency_ms:>13.1f}")

    print(f"\n  {'--- Governed vs Ungoverned ---'}")
    print(f"  {'Metric':<35} {'Rule Gov':>12} {'LLM Gov':>14} {'Ungoverned':>12}")
    print(f"  {'-'*73}")
    print(f"  {'Precision':<35} {rule_gov.avg_precision:>11.1%} {llm_gov.avg_precision:>13.1%} {rule_ungov.avg_precision:>11.1%}")
    print(f"  {'Noise ratio':<35} {rule_gov.avg_noise_ratio:>11.1%} {llm_gov.avg_noise_ratio:>13.1%} {rule_ungov.avg_noise_ratio:>11.1%}")
    print(f"  {'Leak rate':<35} {rule_gov.avg_leak_rate:>11.1%} {llm_gov.avg_leak_rate:>13.1%} {rule_ungov.avg_leak_rate:>11.1%}")
    print(f"  {'Total leaks':<35} {rule_gov.total_leaks:>12} {llm_gov.total_leaks:>14} {rule_ungov.total_leaks:>12}")

    print(f"\n  {'='*70}")
    print(f"  KEY FINDING:")
    print(f"  Rule-based domain accuracy: {rule_routing.domain_accuracy:.1%}")
    print(f"  LLM-assisted domain accuracy: {llm_routing.domain_accuracy:.1%}")
    print(f"  Improvement: {(llm_routing.domain_accuracy - rule_routing.domain_accuracy):+.1%}")
    print(f"")
    print(f"  Ungoverned leaks: {rule_ungov.total_leaks}")
    print(f"  Governed (rule-based) leaks: {rule_gov.total_leaks}")
    print(f"  Governed (LLM-assisted) leaks: {llm_gov.total_leaks}")
    print(f"  {'='*70}")

    # Save results
    output = {
        "experiment": "track1_rule_vs_llm",
        "queries": len(ALL_QUERIES),
        "routing": {
            "rule_based": {
                "domain_accuracy": round(rule_routing.domain_accuracy, 4),
                "mrr": round(rule_routing.avg_mrr, 4),
                "relevance_at_5": round(rule_routing.avg_relevance_at_5, 4),
                "avg_latency_ms": round(rule_routing.avg_latency_ms, 1),
                "p95_latency_ms": round(rule_routing.p95_latency_ms, 1),
            },
            "llm_assisted": {
                "domain_accuracy": round(llm_routing.domain_accuracy, 4),
                "mrr": round(llm_routing.avg_mrr, 4),
                "relevance_at_5": round(llm_routing.avg_relevance_at_5, 4),
                "avg_latency_ms": round(llm_routing.avg_latency_ms, 1),
                "p95_latency_ms": round(llm_routing.p95_latency_ms, 1),
            },
        },
        "governance": {
            "ungoverned": {
                "precision": round(rule_ungov.avg_precision, 4),
                "noise_ratio": round(rule_ungov.avg_noise_ratio, 4),
                "leak_rate": round(rule_ungov.avg_leak_rate, 4),
                "total_leaks": rule_ungov.total_leaks,
            },
            "governed_rule_based": {
                "precision": round(rule_gov.avg_precision, 4),
                "noise_ratio": round(rule_gov.avg_noise_ratio, 4),
                "leak_rate": round(rule_gov.avg_leak_rate, 4),
                "total_leaks": rule_gov.total_leaks,
            },
            "governed_llm_assisted": {
                "precision": round(llm_gov.avg_precision, 4),
                "noise_ratio": round(llm_gov.avg_noise_ratio, 4),
                "leak_rate": round(llm_gov.avg_leak_rate, 4),
                "total_leaks": llm_gov.total_leaks,
            },
        },
    }

    output_path = Path(__file__).parent / "results_track1.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")

    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
