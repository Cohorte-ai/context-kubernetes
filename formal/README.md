# Formal Specifications

Formal verification artifacts for Context Kubernetes design invariants.

## ReconciliationLoop.tla (TLA+)

Models the reconciliation loop and verifies:

- **Safety S1**: No EXPIRED context unit is ever served
- **Safety S2**: If Permission Engine is down, all requests denied (fail-closed)
- **Liveness L1**: Stale sources detected within 2·Δt_r
- **Liveness L2**: Disconnected sources detected within Δt_r

### Run with TLC

```bash
# Install TLA+ tools: https://github.com/tlaplus/tlaplus/releases
java -jar tla2tools.jar -config ReconciliationLoop.cfg ReconciliationLoop.tla
```

Model parameters: 3 sources, MaxAge=3 ticks, ReconcileInterval=2 ticks.

## PermissionModel.als (Alloy)

Models the permission model and verifies:

- **Invariant 3.7a**: Agent permissions ⊂ user permissions (strict subset)
- **Invariant 3.7b**: No agent can have operations not in user's role (no escalation)
- **Invariant 3.7c**: Agent tier ≥ user tier for shared operations (monotonicity)
- **Invariant 3.8**: No agent process can access the strong approval channel

### Run with Alloy Analyzer

```bash
# Install Alloy: https://alloytools.org/download.html
# Open PermissionModel.als in Alloy Analyzer
# Execute > Check each assertion
```

Scope: 3 users, 3 agents, 6 permissions, 4 operations, 3 resources.

## Expected Results

All invariants and properties should hold with zero counterexamples.
If a counterexample is found, it indicates a design flaw that must be fixed
before production deployment.
