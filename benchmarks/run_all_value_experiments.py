"""Run all three value experiments and produce a combined summary.

Usage: python -m benchmarks.run_all_value_experiments
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path


async def main() -> None:
    print("=" * 70)
    print("  CONTEXT KUBERNETES — VALUE EXPERIMENTS")
    print("  Running all three experiments...")
    print("=" * 70)

    start = time.time()

    # Import experiment main functions
    from benchmarks.exp_a_governed_vs_ungoverned import main as exp_a
    from benchmarks.exp_b_freshness_cost import main as exp_b
    from benchmarks.exp_c_attack_scenarios import main as exp_c

    # Run A and B concurrently (both async), C is sync
    print("\n" + "=" * 70)
    await exp_a()

    print("\n" + "=" * 70)
    await exp_b()

    print("\n" + "=" * 70)
    exp_c()

    elapsed = time.time() - start

    # Load all results
    results_dir = Path(__file__).parent
    results = {}
    for name in ["results_exp_a", "results_exp_b", "results_exp_c"]:
        path = results_dir / f"{name}.json"
        if path.exists():
            with open(path) as f:
                results[name] = json.load(f)

    # Print combined summary
    print("\n" + "=" * 70)
    print("  COMBINED SUMMARY — VALUE EXPERIMENTS")
    print("=" * 70)

    if "results_exp_a" in results:
        r = results["results_exp_a"]
        print(f"\n  Exp A: Governed vs. Ungoverned")
        print(f"    Ungoverned precision:  {r['ungoverned']['precision']:.1%}")
        print(f"    Governed precision:    {r['governed']['precision']:.1%}")
        print(f"    Ungoverned leaks:      {r['ungoverned']['total_leaks']}")
        print(f"    Governed leaks:        {r['governed']['total_leaks']}")
        print(f"    Ungoverned token waste: {r['ungoverned']['token_waste_pct']:.1f}%")
        print(f"    Governed token waste:   {r['governed']['token_waste_pct']:.1f}%")

    if "results_exp_b" in results:
        r = results["results_exp_b"]
        print(f"\n  Exp B: Freshness Cost")
        print(f"    Without reconciliation: {r['without_reconciliation']['stale_served']} stale, {r['without_reconciliation']['phantom_served']} phantom")
        print(f"    With reconciliation:    {r['with_reconciliation']['stale_caught']} caught, {r['with_reconciliation']['phantom_caught']} blocked")

    if "results_exp_c" in results:
        r = results["results_exp_c"]
        print(f"\n  Exp C: Attack Scenarios ({r['total_scenarios']} attacks)")
        print(f"    No governance blocked:  {r['blocked']['no_governance']}/{r['total_scenarios']}")
        print(f"    Basic RBAC blocked:     {r['blocked']['basic_rbac']}/{r['total_scenarios']}")
        print(f"    Context K8s blocked:    {r['blocked']['context_k8s']}/{r['total_scenarios']}")

    print(f"\n  Total runtime: {elapsed:.1f}s")
    print("=" * 70)

    # Save combined
    combined = {
        "timestamp": time.time(),
        "runtime_seconds": round(elapsed, 1),
        **results,
    }
    with open(results_dir / "results_combined.json", "w") as f:
        json.dump(combined, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
