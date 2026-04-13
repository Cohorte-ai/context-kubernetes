"""Experiment A: Governed vs. Ungoverned Context Quality.

The VALUE experiment. Shows what goes wrong without governance
and what goes right with it.

Two pipelines process the same 47 queries:
  1. UNGOVERNED (naive RAG): embed query → cosine similarity → top-k
     No permission filtering. No freshness checks. No domain routing.
     No token budget intelligence. Just dump the closest vectors.

  2. GOVERNED (Context Kubernetes): intent classification → domain routing
     → permission filtering → freshness filtering → multi-signal ranking
     → token budget enforcement.

Metrics:
  - Relevance precision: fraction of delivered units that are relevant
  - Noise ratio: fraction of delivered units that are irrelevant
  - Leaked content: units delivered that the user's role shouldn't see
  - Token waste: tokens spent on irrelevant or unauthorized content
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
from context_kubernetes.models import (
    ApprovalTier, ContextRequest, ContextUnit, OperationPermission,
)
from context_kubernetes.permissions.engine import PermissionEngine
from context_kubernetes.router.intent import IntentClassifier
from context_kubernetes.router.router import ContextRouter
from benchmarks.test_queries import ALL_QUERIES, BenchmarkQuery


@dataclass
class PipelineResult:
    query: str
    units_returned: int
    relevant_units: int
    irrelevant_units: int
    leaked_units: int  # units the role shouldn't see
    total_tokens: int
    relevant_tokens: int
    wasted_tokens: int


@dataclass
class ExperimentResults:
    pipeline: str
    num_queries: int = 0
    avg_precision: float = 0.0
    avg_noise_ratio: float = 0.0
    avg_leak_rate: float = 0.0
    total_tokens_used: int = 0
    total_tokens_wasted: int = 0
    token_waste_pct: float = 0.0
    total_leaks: int = 0
    results: list[PipelineResult] = field(default_factory=list)


def _is_relevant(unit: ContextUnit, query: BenchmarkQuery) -> bool:
    """Check if a context unit is relevant to the query's ground truth."""
    source = unit.metadata.source.replace("git:", "")
    return any(
        relevant_path in source or source in relevant_path
        for relevant_path in query.relevant_paths
    )


def _is_leaked(unit: ContextUnit, authorized_role: str, domain_roles: dict) -> bool:
    """Check if a context unit was leaked (role shouldn't see it)."""
    # Determine which domain this unit belongs to based on its source path
    source = unit.metadata.source.lower()
    for domain, roles in domain_roles.items():
        if domain in source:
            if authorized_role not in roles:
                return True
    return False


async def _setup() -> tuple[str, PermissionEngine, ContextRouter, list[GitConnector]]:
    """Set up test environment."""
    seed_dir = Path(__file__).parent.parent / "seed_data" / "context"
    tmpdir = tempfile.mkdtemp(prefix="ck8s-val-")
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

    # Permission engine with role-based access
    engine = PermissionEngine()
    engine.register_role("sales-rep", [
        OperationPermission(operation="read", resources=["clients/*", "sales/*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS),
    ])
    engine.register_agent_profile(
        user_id="test-user", role="sales-rep",
        agent_permissions=[
            OperationPermission(operation="read", resources=["clients/*", "sales/*"], tier=ApprovalTier.AUTONOMOUS),
        ],
        excluded_operations=["write"],
    )

    # Domain → authorized roles
    domain_roles = {
        "clients": ["sales-rep", "sales-manager", "finance-manager"],
        "sales": ["sales-rep", "sales-manager"],
        "delivery": ["sales-rep", "sales-manager", "delivery-lead"],
        "hr": ["hr-admin"],
        "finance": ["finance-manager", "sales-manager"],
    }

    # Governed router with domain-specific connectors
    router = ContextRouter(
        permission_engine=engine,
        intent_classifier=IntentClassifier(
            available_domains=["sales", "delivery", "hr", "finance"],
        ),
    )

    connectors = []
    for domain in ["sales", "delivery", "hr", "finance"]:
        conn = GitConnector()
        await conn.connect(ConnectionConfig(
            connector_type="git-repo", endpoint=tmpdir,
            extra={"domain": domain, "authorized_roles": domain_roles.get(domain, [])},
        ))
        router.register_connector(domain, conn)
        connectors.append(conn)

    router.set_cross_domain_rules("sales", {"delivery", "finance"})

    # Ungoverned connector: sees ALL files, no domain tagging, no auth
    ungoverned_conn = GitConnector()
    await ungoverned_conn.connect(ConnectionConfig(
        connector_type="git-repo", endpoint=tmpdir,
        extra={"domain": "all"},  # no authorization tagging
    ))
    connectors.append(ungoverned_conn)

    return tmpdir, engine, router, connectors


async def run_governed(
    router: ContextRouter, engine: PermissionEngine,
    queries: list[BenchmarkQuery], domain_roles: dict,
) -> ExperimentResults:
    """Run queries through the governed pipeline."""
    session = engine.create_session("test-user", "agent-gov", "sales-rep")
    results = ExperimentResults(pipeline="governed")

    for bq in queries:
        response = await router.route(ContextRequest(
            session_id=session.session_id, intent=bq.query, token_budget=8000,
        ))

        relevant = sum(1 for u in response.units if _is_relevant(u, bq))
        irrelevant = len(response.units) - relevant
        leaked = sum(1 for u in response.units if _is_leaked(u, "sales-rep", domain_roles))
        relevant_tokens = sum(u.token_count for u in response.units if _is_relevant(u, bq))
        wasted = response.total_tokens - relevant_tokens

        results.results.append(PipelineResult(
            query=bq.query,
            units_returned=len(response.units),
            relevant_units=relevant,
            irrelevant_units=irrelevant,
            leaked_units=leaked,
            total_tokens=response.total_tokens,
            relevant_tokens=relevant_tokens,
            wasted_tokens=wasted,
        ))

    return _aggregate(results)


async def run_ungoverned(
    ungoverned_conn: GitConnector,
    queries: list[BenchmarkQuery], domain_roles: dict,
) -> ExperimentResults:
    """Run queries through the ungoverned pipeline (naive RAG)."""
    results = ExperimentResults(pipeline="ungoverned")

    for bq in queries:
        # Naive RAG: just search all content by keywords, no permissions
        units = await ungoverned_conn.query(bq.query, max_results=20)

        relevant = sum(1 for u in units if _is_relevant(u, bq))
        irrelevant = len(units) - relevant
        leaked = sum(1 for u in units if _is_leaked(u, "sales-rep", domain_roles))
        total_tokens = sum(u.token_count for u in units)
        relevant_tokens = sum(u.token_count for u in units if _is_relevant(u, bq))
        wasted = total_tokens - relevant_tokens

        results.results.append(PipelineResult(
            query=bq.query,
            units_returned=len(units),
            relevant_units=relevant,
            irrelevant_units=irrelevant,
            leaked_units=leaked,
            total_tokens=total_tokens,
            relevant_tokens=relevant_tokens,
            wasted_tokens=wasted,
        ))

    return _aggregate(results)


def _aggregate(results: ExperimentResults) -> ExperimentResults:
    n = len(results.results)
    results.num_queries = n
    if n == 0:
        return results

    precisions = []
    noise_ratios = []
    leak_rates = []

    for r in results.results:
        if r.units_returned > 0:
            precisions.append(r.relevant_units / r.units_returned)
            noise_ratios.append(r.irrelevant_units / r.units_returned)
            leak_rates.append(r.leaked_units / r.units_returned)
        else:
            precisions.append(0.0)
            noise_ratios.append(0.0)
            leak_rates.append(0.0)

    results.avg_precision = sum(precisions) / n
    results.avg_noise_ratio = sum(noise_ratios) / n
    results.avg_leak_rate = sum(leak_rates) / n
    results.total_tokens_used = sum(r.total_tokens for r in results.results)
    results.total_tokens_wasted = sum(r.wasted_tokens for r in results.results)
    results.token_waste_pct = (
        results.total_tokens_wasted / results.total_tokens_used * 100
        if results.total_tokens_used > 0 else 0
    )
    results.total_leaks = sum(r.leaked_units for r in results.results)

    return results


def _print(r: ExperimentResults) -> None:
    print(f"\n  Pipeline: {r.pipeline}")
    print(f"  Queries: {r.num_queries}")
    print(f"  Avg relevance precision:  {r.avg_precision:.1%}")
    print(f"  Avg noise ratio:          {r.avg_noise_ratio:.1%}")
    print(f"  Avg leak rate:            {r.avg_leak_rate:.1%}")
    print(f"  Total tokens used:        {r.total_tokens_used:,}")
    print(f"  Total tokens wasted:      {r.total_tokens_wasted:,} ({r.token_waste_pct:.1f}%)")
    print(f"  Total content leaks:      {r.total_leaks}")


async def main() -> ExperimentResults:
    print("=" * 70)
    print("Experiment A: Governed vs. Ungoverned Context Quality")
    print("=" * 70)

    tmpdir, engine, router, connectors = await _setup()
    ungoverned_conn = connectors[-1]

    domain_roles = {
        "clients": ["sales-rep", "sales-manager", "finance-manager"],
        "sales": ["sales-rep", "sales-manager"],
        "delivery": ["sales-rep", "sales-manager", "delivery-lead"],
        "hr": ["hr-admin"],
        "finance": ["finance-manager", "sales-manager"],
    }

    governed = await run_governed(router, engine, ALL_QUERIES, domain_roles)
    ungoverned = await run_ungoverned(ungoverned_conn, ALL_QUERIES, domain_roles)

    _print(ungoverned)
    _print(governed)

    # Delta
    print(f"\n  {'=' * 50}")
    print(f"  IMPROVEMENT (governed over ungoverned):")
    print(f"  Precision:    +{(governed.avg_precision - ungoverned.avg_precision):.1%}")
    print(f"  Noise:        {(governed.avg_noise_ratio - ungoverned.avg_noise_ratio):+.1%}")
    print(f"  Leaks:        {ungoverned.total_leaks} → {governed.total_leaks}")
    print(f"  Token waste:  {ungoverned.token_waste_pct:.1f}% → {governed.token_waste_pct:.1f}%")
    print(f"  {'=' * 50}")

    output = {
        "experiment": "governed_vs_ungoverned",
        "ungoverned": {
            "precision": round(ungoverned.avg_precision, 4),
            "noise_ratio": round(ungoverned.avg_noise_ratio, 4),
            "leak_rate": round(ungoverned.avg_leak_rate, 4),
            "total_leaks": ungoverned.total_leaks,
            "token_waste_pct": round(ungoverned.token_waste_pct, 1),
        },
        "governed": {
            "precision": round(governed.avg_precision, 4),
            "noise_ratio": round(governed.avg_noise_ratio, 4),
            "leak_rate": round(governed.avg_leak_rate, 4),
            "total_leaks": governed.total_leaks,
            "token_waste_pct": round(governed.token_waste_pct, 1),
        },
    }
    output_path = Path(__file__).parent / "results_exp_a.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    return governed


if __name__ == "__main__":
    asyncio.run(main())
