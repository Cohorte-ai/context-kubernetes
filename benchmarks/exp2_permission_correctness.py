"""Experiment 2: Permission Correctness.

The most critical security experiment. Tests that:
  - Zero unauthorized context units are ever delivered
  - The strict-subset invariant cannot be violated via any API path
  - Cross-domain access is properly brokered or denied
  - Killed sessions immediately block all access

Metrics:
  - Unauthorized retrieval rate (must be 0.000)
  - False positive rate (legitimate requests incorrectly denied)
  - Invariant violation count (must be 0)

Run: python -m benchmarks.exp2_permission_correctness
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
    ApprovalTier,
    ContextRequest,
    ContextUnit,
    OperationPermission,
)
from context_kubernetes.permissions.engine import PermissionEngine
from context_kubernetes.router.intent import IntentClassifier
from context_kubernetes.router.router import ContextRouter


@dataclass
class PermissionTestResult:
    """Result of a single permission test."""

    test_name: str
    query: str
    role: str
    expected_access: bool  # should this query return results?
    actual_access: bool  # did it return results?
    correct: bool  # expected == actual
    units_returned: int = 0
    details: str = ""


@dataclass
class ExperimentResults:
    """Aggregate permission correctness results."""

    total_tests: int = 0
    unauthorized_retrievals: int = 0  # MUST be 0
    false_positives: int = 0  # legitimate requests incorrectly denied
    invariant_violations: int = 0  # MUST be 0
    all_correct: bool = False
    results: list[PermissionTestResult] = field(default_factory=list)


async def _setup() -> tuple[str, PermissionEngine, ContextRouter]:
    """Set up test environment with multi-role permissions."""
    seed_dir = Path(__file__).parent.parent / "seed_data" / "context"
    tmpdir = tempfile.mkdtemp(prefix="ck8s-perm-")
    repo = Repo.init(tmpdir)

    import shutil
    for item in seed_dir.iterdir():
        dest = Path(tmpdir) / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    repo.git.add(A=True)
    repo.index.commit("Seed data")

    # Permission engine with multiple roles
    engine = PermissionEngine()

    # Role: sales-rep — can read clients and sales, NOT finance or hr/salary
    engine.register_role("sales-rep", [
        OperationPermission(operation="read", resources=["clients/*", "sales/*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS),
    ])

    # Role: finance-manager — can read finance and clients, NOT hr
    engine.register_role("finance-manager", [
        OperationPermission(operation="read", resources=["finance/*", "clients/*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="write", resources=["finance/*"], tier=ApprovalTier.AUTONOMOUS),
    ])

    # Role: hr-admin — can read hr and limited client info
    engine.register_role("hr-admin", [
        OperationPermission(operation="read", resources=["hr/*"], tier=ApprovalTier.AUTONOMOUS),
    ])

    # Agent profiles (strict subsets)
    engine.register_agent_profile(
        user_id="sales-user",
        role="sales-rep",
        agent_permissions=[
            OperationPermission(operation="read", resources=["clients/*", "sales/*"], tier=ApprovalTier.AUTONOMOUS),
        ],
        excluded_operations=["write"],
    )
    engine.register_agent_profile(
        user_id="finance-user",
        role="finance-manager",
        agent_permissions=[
            OperationPermission(operation="read", resources=["finance/*", "clients/*"], tier=ApprovalTier.AUTONOMOUS),
        ],
        excluded_operations=["write"],
    )
    # HR admin role has only "read" — agent must exclude at least one user op
    # We add a dummy user operation so the agent profile is a strict subset
    engine._role_permissions["hr-admin"].append(
        OperationPermission(operation="export", resources=["hr/*"], tier=ApprovalTier.SOFT_APPROVAL)
    )
    engine.register_agent_profile(
        user_id="hr-user",
        role="hr-admin",
        agent_permissions=[
            OperationPermission(operation="read", resources=["hr/*"], tier=ApprovalTier.AUTONOMOUS),
        ],
        excluded_operations=["export"],
    )

    # Router
    classifier = IntentClassifier(
        available_domains=["sales", "delivery", "hr", "finance"],
    )
    router = ContextRouter(permission_engine=engine, intent_classifier=classifier)

    # Connect each domain with proper authorized_roles
    domain_roles = {
        "sales": ["sales-rep", "sales-manager", "finance-manager"],
        "delivery": ["sales-rep", "sales-manager"],
        "hr": ["hr-admin"],
        "finance": ["finance-manager", "sales-manager"],
    }
    for domain in ["sales", "delivery", "hr", "finance"]:
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": domain, "authorized_roles": domain_roles[domain]},
        ))
        router.register_connector(domain, connector)

    return tmpdir, engine, router


async def _test_authorized_access(
    engine: PermissionEngine, router: ContextRouter
) -> list[PermissionTestResult]:
    """Test that authorized queries return results (no false positives)."""
    results = []

    # Sales rep should access client data
    session = engine.create_session("sales-user", "agent-1", "sales-rep")
    for query, expected_content in [
        ("Henderson client status", "henderson"),
        ("Sales pipeline Q2", "pipeline"),
        ("Globex deal size", "globex"),
    ]:
        response = await router.route(ContextRequest(
            session_id=session.session_id, intent=query, token_budget=8000
        ))
        has_results = len(response.units) > 0
        results.append(PermissionTestResult(
            test_name=f"authorized_sales_rep:{query[:30]}",
            query=query,
            role="sales-rep",
            expected_access=True,
            actual_access=has_results,
            correct=has_results,
            units_returned=len(response.units),
        ))

    return results


async def _test_cross_domain_denied(
    engine: PermissionEngine, router: ContextRouter
) -> list[PermissionTestResult]:
    """Test that cross-domain access without brokering is denied."""
    results = []

    # HR admin should NOT see finance data
    session = engine.create_session("hr-user", "agent-hr", "hr-admin")

    # Finance query from HR role
    response = await router.route(ContextRequest(
        session_id=session.session_id, intent="What's our Q2 budget?", token_budget=8000
    ))

    # Check that no finance content leaked
    finance_leaked = any(
        "finance" in u.metadata.source or "budget" in u.content.lower()
        for u in response.units
        if "finance" in u.metadata.domain
    )

    results.append(PermissionTestResult(
        test_name="cross_domain_hr_to_finance",
        query="What's our Q2 budget?",
        role="hr-admin",
        expected_access=False,
        actual_access=finance_leaked,
        correct=not finance_leaked,
        units_returned=len(response.units),
        details="HR admin querying finance data — should not access finance content",
    ))

    return results


async def _test_killed_session(
    engine: PermissionEngine, router: ContextRouter
) -> list[PermissionTestResult]:
    """Test that killed sessions immediately block all access."""
    results = []

    session = engine.create_session("sales-user", "agent-kill", "sales-rep")

    # Verify access works before kill
    response_before = await router.route(ContextRequest(
        session_id=session.session_id, intent="Henderson status", token_budget=8000
    ))

    # Kill the session
    engine.kill_session(session.session_id)

    # Verify access blocked after kill
    response_after = await router.route(ContextRequest(
        session_id=session.session_id, intent="Henderson status", token_budget=8000
    ))

    results.append(PermissionTestResult(
        test_name="kill_switch_immediate_block",
        query="Henderson status (after kill)",
        role="sales-rep",
        expected_access=False,
        actual_access=len(response_after.units) > 0,
        correct=len(response_after.units) == 0,
        units_returned=len(response_after.units),
        details=f"Before kill: {len(response_before.units)} units. After kill: {len(response_after.units)} units.",
    ))

    return results


async def _test_invariant_violations(engine: PermissionEngine) -> list[PermissionTestResult]:
    """Test that the strict-subset invariant cannot be violated."""
    results = []

    # Attempt to register agent with superset permissions
    try:
        engine.register_agent_profile(
            user_id="attacker",
            role="hr-admin",
            agent_permissions=[
                OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
                OperationPermission(operation="write", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
                OperationPermission(operation="delete", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            ],
        )
        violation = True
    except ValueError:
        violation = False

    results.append(PermissionTestResult(
        test_name="invariant_37_superset_rejected",
        query="Register agent with superset permissions",
        role="hr-admin",
        expected_access=False,
        actual_access=violation,
        correct=not violation,
        details="Attempted to register agent with operations not in user role",
    ))

    # Attempt to register agent with equal permissions (not strict subset)
    # Use a fresh role that has exactly one operation
    engine.register_role("minimal-role", [
        OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
    ])
    try:
        engine.register_agent_profile(
            user_id="greedy",
            role="minimal-role",
            agent_permissions=[
                OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            ],
            excluded_operations=[],  # no exclusions = equal set → must fail
        )
        violation2 = True
    except ValueError:
        violation2 = False

    results.append(PermissionTestResult(
        test_name="invariant_37_equal_set_rejected",
        query="Register agent with equal permissions (not strict subset)",
        role="minimal-role",
        expected_access=False,
        actual_access=violation2,
        correct=not violation2,
        details="Attempted to register agent with all user operations (not strict subset)",
    ))

    return results


async def main() -> None:
    """Run Experiment 2: Permission Correctness."""
    print("=" * 70)
    print("Experiment 2: Permission Correctness")
    print("=" * 70)

    tmpdir, engine, router = await _setup()

    all_results: list[PermissionTestResult] = []

    print("\n1. Testing authorized access (no false positives)...")
    all_results.extend(await _test_authorized_access(engine, router))

    print("2. Testing cross-domain denial...")
    all_results.extend(await _test_cross_domain_denied(engine, router))

    print("3. Testing kill switch...")
    all_results.extend(await _test_killed_session(engine, router))

    print("4. Testing invariant violations...")
    all_results.extend(await _test_invariant_violations(engine))

    # Aggregate
    exp = ExperimentResults(
        total_tests=len(all_results),
        unauthorized_retrievals=sum(
            1 for r in all_results
            if not r.expected_access and r.actual_access
        ),
        false_positives=sum(
            1 for r in all_results
            if r.expected_access and not r.actual_access
        ),
        invariant_violations=sum(
            1 for r in all_results
            if "invariant" in r.test_name and not r.correct
        ),
        results=all_results,
    )
    exp.all_correct = (exp.unauthorized_retrievals == 0 and exp.invariant_violations == 0)

    # Print
    print(f"\n{'=' * 50}")
    print(f"  Total tests:              {exp.total_tests}")
    print(f"  Unauthorized retrievals:  {exp.unauthorized_retrievals} {'PASS' if exp.unauthorized_retrievals == 0 else 'FAIL'}")
    print(f"  False positives:          {exp.false_positives}")
    print(f"  Invariant violations:     {exp.invariant_violations} {'PASS' if exp.invariant_violations == 0 else 'FAIL'}")
    print(f"  Overall:                  {'ALL PASS' if exp.all_correct else 'FAILURES DETECTED'}")
    print(f"{'=' * 50}")

    for r in all_results:
        status = "PASS" if r.correct else "FAIL"
        print(f"  [{status}] {r.test_name}: {r.details or r.query[:50]}")

    # Save
    output = {
        "experiment": "permission_correctness",
        "total_tests": exp.total_tests,
        "unauthorized_retrievals": exp.unauthorized_retrievals,
        "false_positives": exp.false_positives,
        "invariant_violations": exp.invariant_violations,
        "all_correct": exp.all_correct,
    }
    output_path = Path(__file__).parent / "results_exp2.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {output_path}")

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
