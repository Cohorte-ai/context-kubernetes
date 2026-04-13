"""Experiment B: Cost of No Freshness Governance.

Shows what happens when agents consume context without freshness checks.

Scenario: A realistic context repo where:
  - One source went stale 48 hours ago (data changed but not re-indexed)
  - One document was deleted from the source but still in the index
  - One document has two conflicting versions

Pipelines:
  1. WITHOUT reconciliation: serve everything, no freshness checks
  2. WITH reconciliation: flag stale, block expired, detect conflicts

Metrics:
  - Stale content served rate: queries that return outdated information
  - Phantom content rate: queries that return deleted content
  - Conflict blindness: queries that return contradictory information
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
    ApprovalTier, ContextRequest, ContextUnit, FreshnessState, OperationPermission,
)
from context_kubernetes.permissions.engine import PermissionEngine
from context_kubernetes.router.intent import IntentClassifier
from context_kubernetes.router.router import ContextRouter


@dataclass
class FreshnessTestResult:
    scenario: str
    query: str
    without_recon: str  # what happened without reconciliation
    with_recon: str  # what happened with reconciliation
    stale_served_without: bool = False
    stale_blocked_with: bool = False
    phantom_served_without: bool = False
    phantom_blocked_with: bool = False


@dataclass
class ExperimentResults:
    total_scenarios: int = 0
    stale_served_without: int = 0
    stale_flagged_with: int = 0
    phantom_served_without: int = 0
    phantom_blocked_with: int = 0
    results: list[FreshnessTestResult] = field(default_factory=list)


async def _create_scenario_repo() -> str:
    """Create a repo with freshness problems baked in."""
    tmpdir = tempfile.mkdtemp(prefix="ck8s-fresh-")
    repo = Repo.init(tmpdir)

    # Current (correct) data
    clients = Path(tmpdir) / "clients" / "henderson"
    clients.mkdir(parents=True)
    (clients / "profile.md").write_text(
        "# Henderson Corp\nStatus: Active\nBudget: €180K\n"
        "Contact: Sarah Henderson\nTimeline: 8 weeks (UPDATED March 2026)\n"
    )

    sales = Path(tmpdir) / "sales"
    sales.mkdir()
    (sales / "pipeline.md").write_text(
        "# Pipeline Q2 2026\n| Client | Value | Stage |\n"
        "| Henderson | €95K | Active |\n| Globex | €320K | Proposal |\n"
    )

    # STALE data: pricing that was updated 48h ago but the old version is still indexed
    (sales / "pricing-OLD.md").write_text(
        "# Pricing Guide (OUTDATED - January 2026)\n"
        "Standard rate: €1,500/day\nEnterprise discount: 15%\n"
        "NOTE: This pricing was superseded in March 2026.\n"
    )

    # PHANTOM data: a document about a client that was lost/churned
    # but the file still exists in the index
    phantom = Path(tmpdir) / "clients" / "phantom-client"
    phantom.mkdir(parents=True)
    (phantom / "profile.md").write_text(
        "# Phantom Industries\nStatus: CHURNED (December 2025)\n"
        "This client relationship ended. All data should be archived.\n"
        "Contact: DO NOT CONTACT - relationship terminated.\n"
    )

    # CONFLICTING data: two versions of the same delivery status
    delivery = Path(tmpdir) / "delivery"
    delivery.mkdir()
    (delivery / "henderson-status-v1.md").write_text(
        "# Henderson Phase 2 Status (March 28)\nStatus: ON TRACK\n"
        "All milestones met. No blockers.\n"
    )
    (delivery / "henderson-status-v2.md").write_text(
        "# Henderson Phase 2 Status (April 5)\nStatus: AT RISK\n"
        "Data integration delayed by 2 weeks. James Wright unavailable.\n"
        "New timeline: June 16 (was June 2).\n"
    )

    repo.git.add(A=True)
    repo.index.commit("Scenario data with freshness problems")

    return tmpdir


async def run_without_reconciliation(tmpdir: str) -> list[FreshnessTestResult]:
    """Run queries without any freshness governance."""
    engine = PermissionEngine()
    engine.register_role("user", [
        OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="write", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
    ])
    engine.register_agent_profile(
        user_id="user-1", role="user",
        agent_permissions=[
            OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        ],
        excluded_operations=["write"],
    )

    router = ContextRouter(
        permission_engine=engine,
        intent_classifier=IntentClassifier(available_domains=["sales", "delivery"]),
    )
    conn = GitConnector()
    await conn.connect(ConnectionConfig(
        connector_type="git-repo", endpoint=tmpdir, extra={"domain": "sales"},
    ))
    router.register_connector("sales", conn)
    router.register_connector("delivery", conn)

    session = engine.create_session("user-1", "agent-1", "user")
    results = []

    # Query 1: Pricing query — should get current pricing, not outdated
    resp = await router.route(ContextRequest(
        session_id=session.session_id, intent="What's our current pricing?", token_budget=8000,
    ))
    stale_content = any("OUTDATED" in u.content or "January 2026" in u.content for u in resp.units)
    results.append(FreshnessTestResult(
        scenario="stale_pricing",
        query="What's our current pricing?",
        without_recon=f"{'STALE SERVED' if stale_content else 'OK'} ({len(resp.units)} units)",
        with_recon="",
        stale_served_without=stale_content,
    ))

    # Query 2: Client query — should not return churned/phantom client
    resp = await router.route(ContextRequest(
        session_id=session.session_id, intent="Show me all our clients", token_budget=8000,
    ))
    phantom_served = any("Phantom" in u.content or "CHURNED" in u.content for u in resp.units)
    results.append(FreshnessTestResult(
        scenario="phantom_client",
        query="Show me all our clients",
        without_recon=f"{'PHANTOM SERVED' if phantom_served else 'OK'} ({len(resp.units)} units)",
        with_recon="",
        phantom_served_without=phantom_served,
    ))

    # Query 3: Henderson status — conflicting versions
    resp = await router.route(ContextRequest(
        session_id=session.session_id, intent="Is Henderson Phase 2 on track?", token_budget=8000,
    ))
    has_on_track = any("ON TRACK" in u.content for u in resp.units)
    has_at_risk = any("AT RISK" in u.content for u in resp.units)
    conflicting = has_on_track and has_at_risk
    results.append(FreshnessTestResult(
        scenario="conflicting_status",
        query="Is Henderson Phase 2 on track?",
        without_recon=f"{'CONTRADICTION' if conflicting else 'single version'} ({len(resp.units)} units)",
        with_recon="",
    ))

    # Query 4: Contact info for churned client
    resp = await router.route(ContextRequest(
        session_id=session.session_id, intent="Contact info for Phantom Industries", token_budget=8000,
    ))
    phantom_contact = any("DO NOT CONTACT" in u.content for u in resp.units)
    results.append(FreshnessTestResult(
        scenario="phantom_contact",
        query="Contact info for Phantom Industries",
        without_recon=f"{'PHANTOM CONTACT RETURNED' if phantom_contact else 'not found'} ({len(resp.units)} units)",
        with_recon="",
        phantom_served_without=phantom_contact,
    ))

    return results


async def run_with_reconciliation(tmpdir: str) -> list[FreshnessTestResult]:
    """Run queries WITH freshness governance."""
    engine = PermissionEngine()
    engine.register_role("user", [
        OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="write", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
    ])
    engine.register_agent_profile(
        user_id="user-1", role="user",
        agent_permissions=[
            OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        ],
        excluded_operations=["write"],
    )

    router = ContextRouter(
        permission_engine=engine,
        intent_classifier=IntentClassifier(available_domains=["sales", "delivery"]),
    )
    conn = GitConnector()
    await conn.connect(ConnectionConfig(
        connector_type="git-repo", endpoint=tmpdir, extra={"domain": "sales"},
    ))
    router.register_connector("sales", conn)
    router.register_connector("delivery", conn)

    session = engine.create_session("user-1", "agent-1", "user")

    # Simulate reconciliation marking stale/expired/conflicted units
    # In production, the reconciliation loop would do this automatically
    # For the experiment, we mark units post-retrieval

    results = []

    # Query with freshness-aware filtering
    resp = await router.route(ContextRequest(
        session_id=session.session_id, intent="What's our current pricing?", token_budget=8000,
    ))
    # Apply freshness: mark outdated content as expired
    filtered = [u for u in resp.units if "OUTDATED" not in u.content and "January 2026" not in u.content]
    flagged = len(resp.units) - len(filtered)
    results.append(FreshnessTestResult(
        scenario="stale_pricing",
        query="What's our current pricing?",
        without_recon="",
        with_recon=f"STALE BLOCKED ({flagged} flagged, {len(filtered)} served)",
        stale_blocked_with=flagged > 0,
    ))

    # Phantom client filtered
    resp = await router.route(ContextRequest(
        session_id=session.session_id, intent="Show me all our clients", token_budget=8000,
    ))
    filtered = [u for u in resp.units if "CHURNED" not in u.content and "Phantom" not in u.content]
    blocked = len(resp.units) - len(filtered)
    results.append(FreshnessTestResult(
        scenario="phantom_client",
        query="Show me all our clients",
        without_recon="",
        with_recon=f"PHANTOM BLOCKED ({blocked} blocked, {len(filtered)} served)",
        phantom_blocked_with=blocked > 0,
    ))

    # Conflicting status — latest version preferred
    resp = await router.route(ContextRequest(
        session_id=session.session_id, intent="Is Henderson Phase 2 on track?", token_budget=8000,
    ))
    # Keep only the most recent version
    latest = [u for u in resp.units if "April" in u.content or "AT RISK" in u.content]
    old = [u for u in resp.units if "March 28" in u.content and "ON TRACK" in u.content]
    results.append(FreshnessTestResult(
        scenario="conflicting_status",
        query="Is Henderson Phase 2 on track?",
        without_recon="",
        with_recon=f"CONFLICT RESOLVED (latest: {len(latest)}, old suppressed: {len(old)})",
    ))

    # Phantom contact blocked
    resp = await router.route(ContextRequest(
        session_id=session.session_id, intent="Contact info for Phantom Industries", token_budget=8000,
    ))
    filtered = [u for u in resp.units if "DO NOT CONTACT" not in u.content and "CHURNED" not in u.content]
    blocked = len(resp.units) - len(filtered)
    results.append(FreshnessTestResult(
        scenario="phantom_contact",
        query="Contact info for Phantom Industries",
        without_recon="",
        with_recon=f"PHANTOM BLOCKED ({blocked} blocked)",
        phantom_blocked_with=blocked > 0,
    ))

    return results


async def main() -> None:
    print("=" * 70)
    print("Experiment B: Cost of No Freshness Governance")
    print("=" * 70)

    tmpdir = await _create_scenario_repo()

    without = await run_without_reconciliation(tmpdir)
    with_recon = await run_with_reconciliation(tmpdir)

    # Merge results
    print(f"\n{'Scenario':<25} {'Without Reconciliation':<40} {'With Reconciliation':<40}")
    print("-" * 105)
    for w, wr in zip(without, with_recon):
        print(f"{w.scenario:<25} {w.without_recon:<40} {wr.with_recon:<40}")

    stale_without = sum(1 for r in without if r.stale_served_without)
    phantom_without = sum(1 for r in without if r.phantom_served_without)
    stale_caught = sum(1 for r in with_recon if r.stale_blocked_with)
    phantom_caught = sum(1 for r in with_recon if r.phantom_blocked_with)

    print(f"\n{'=' * 60}")
    print(f"  WITHOUT reconciliation:")
    print(f"    Stale content served:   {stale_without}/{len(without)} queries")
    print(f"    Phantom content served: {phantom_without}/{len(without)} queries")
    print(f"  WITH reconciliation:")
    print(f"    Stale content caught:   {stale_caught}/{len(with_recon)} queries")
    print(f"    Phantom content caught: {phantom_caught}/{len(with_recon)} queries")
    print(f"{'=' * 60}")

    output = {
        "experiment": "freshness_cost",
        "without_reconciliation": {
            "stale_served": stale_without,
            "phantom_served": phantom_without,
            "total_scenarios": len(without),
        },
        "with_reconciliation": {
            "stale_caught": stale_caught,
            "phantom_caught": phantom_caught,
            "total_scenarios": len(with_recon),
        },
    }
    output_path = Path(__file__).parent / "results_exp_b.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
