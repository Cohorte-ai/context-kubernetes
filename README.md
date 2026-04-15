<p align="center">
  <h1 align="center">Context Kubernetes</h1>
  <p align="center">
    <strong>Declarative Orchestration of Enterprise Knowledge for Agentic AI Systems</strong>
  </p>
  <p align="center">
    <a href="https://arxiv.org/abs/2604.11623"><img src="https://img.shields.io/badge/arXiv-2604.11623-b31b1b" alt="arXiv"></a>
    <a href="https://github.com/Cohorte-ai/context-kubernetes/actions"><img src="https://img.shields.io/badge/tests-92%20passing-brightgreen" alt="Tests"></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
    <a href="https://www.cohorte.co/playbooks/the-enterprise-agentic-platform"><img src="https://img.shields.io/badge/book-The%20Enterprise%20Agentic%20Platform-orange" alt="Book"></a>
  </p>
</p>

---

**Context Kubernetes** is the orchestration layer for organizational knowledge in the age of AI agents. Just as Kubernetes orchestrates containers, Context Kubernetes orchestrates the delivery of the right knowledge, to the right agent, with the right permissions, at the right freshness, within the right cost envelope.

This repository contains the prototype implementation and experimental evaluation accompanying the paper:

> **Context Kubernetes: Declarative Orchestration of Enterprise Knowledge for Agentic AI Systems**
> Charafeddine Mouzouni, OPIT & Cohorte AI, 2026. [[arXiv:2604.11623]](https://arxiv.org/abs/2604.11623)

For the broader enterprise agentic platform context, see the companion book: [**The Enterprise Agentic Platform**](https://www.cohorte.co/playbooks/the-enterprise-agentic-platform).

---

## Key Results

| Experiment | Finding |
|---|---|
| **Permission correctness** | Zero unauthorized context deliveries. Zero false positives. Zero invariant violations. |
| **Approval isolation** | 8/8 tests pass. Design Invariant 3.8 architecturally enforced. No surveyed enterprise platform does this. |
| **Three-tier vs. RBAC** | No governance: 0/5 attacks blocked. Basic RBAC: 4/5. Context Kubernetes: **5/5**. |
| **Governed vs. ungoverned** | Ungoverned agents leak cross-domain data in 26% of queries. Governed routing reduces noise by 14pp. |
| **Freshness** | Without reconciliation: phantom content served, contradictory info delivered. With: blocked in <1ms. |

## Architecture

```
AGENTS  (any framework, any LLM)
    |
    |  Context API  (15 operations · HTTPS + WSS · JWT)
    |
CONTEXT KUBERNETES
    |-- Context Registry        metadata store (analogous to etcd)
    |-- Context Router          intent-based routing (analogous to kube-scheduler)
    |-- Permission Engine       3-tier agent approval model
    |-- Freshness Manager       TTL monitoring + reconciliation loop
    |-- Trust Policy Engine     guardrails, DLP, audit logging
    |-- Context Operators       domain-specific intelligence (analogous to K8s Operators)
    |-- LLM Gateway             prompt inspection, cost metering
    |
    |  Context Runtime Interface (CxRI · 6 operations per connector)
    |
CONTEXT SOURCES  (Git repos · PostgreSQL · Gmail · SaaS APIs · ERP)
```

## Core Abstractions

| Abstraction | Kubernetes Analog | Description |
|---|---|---|
| **Context Unit** | Pod | Smallest addressable element of organizational knowledge |
| **Context Domain** | Namespace | Isolation boundary (sales, HR, legal, ops) with scoped access |
| **Context Store** | Persistent Volume | Backing storage accessed exclusively through CxRI |
| **Context Endpoint** | Service | Stable, intent-based interface — agents ask *what*, not *where* |
| **Context Operator** | Operator | Domain-specific intelligence controller |
| **CxRI** | CRI | Standard 6-operation adapter to any data source |

## Design Invariants

**Invariant 3.7 — Agent Permission Subset.** Agent permissions are always a strict subset of user permissions. No API exists for an agent to exceed its user's authority. For every shared operation, the agent's required approval tier is equal to or more restrictive than the user's.

**Invariant 3.8 — Strong Approval Isolation.** For Tier 3 (high-stakes) actions, the approval channel is: (1) external to the agent's execution environment, (2) not readable or writable by the agent, and (3) authenticated via a separate factor. A [survey of four enterprise platforms](context_kubernetes/permissions/engine.py) (Microsoft Copilot Studio, Salesforce Agentforce, AWS Bedrock, Google Vertex AI) found that none architecturally enforces all three conditions.

## Quick Start

```bash
git clone https://github.com/Cohorte-ai/context-kubernetes.git
cd context-kubernetes
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run all 92 tests
pytest

# Run the value experiments
python -m benchmarks.run_all_value_experiments

# Start the API server
uvicorn context_kubernetes.api.app:app --reload
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/sessions` | Create authenticated agent session |
| `DELETE` | `/sessions/{id}` | Kill switch: terminate session |
| `DELETE` | `/sessions` | Kill switch: terminate all sessions |
| `POST` | `/context/request` | Request context by intent (the core endpoint) |
| `POST` | `/actions/submit` | Submit action with three-tier classification |
| `POST` | `/approvals/{id}/resolve` | Resolve pending approval (T2 or T3 with OTP) |
| `POST` | `/audit/events` | Query audit log |
| `GET` | `/audit/count` | Count audit events |
| `GET` | `/health` | System health check |
| `GET` | `/health/sources` | Source health and freshness |

## Manifest Example

Knowledge architecture is defined as code — version-controlled, diffable, auditable:

```yaml
apiVersion: context/v1
kind: ContextDomain
metadata:
  name: sales
  namespace: acme-corp

spec:
  sources:
    - name: client-context
      type: git-repo
      refresh: realtime
    - name: pipeline
      type: connector
      config: {system: postgresql}
      refresh: 1h

  access:
    agentPermissions:
      read: autonomous
      write:
        default: soft-approval
        paths:
          "*/contracts/*": strong-approval
      execute:
        send-external-email: strong-approval
        commit-to-pricing: excluded    # agent cannot even request this

  freshness:
    defaults: {maxAge: 24h, staleAction: flag}

  routing:
    intentParsing: llm-assisted
    tokenBudget: 8000
    priority:
      - {signal: semantic_relevance, weight: 0.40}
      - {signal: recency,           weight: 0.30}
      - {signal: authority,          weight: 0.20}
      - {signal: user_relevance,     weight: 0.10}
```

## Project Structure

```
context-kubernetes/
├── context_kubernetes/         # Source code
│   ├── api/                    # FastAPI service (10 endpoints)
│   ├── config/                 # Manifest parser
│   ├── cxri/                   # Context Runtime Interface
│   │   └── connectors/         # Git, PostgreSQL connectors
│   ├── permissions/            # Permission Engine (3-tier model)
│   ├── reconciliation/         # Reconciliation loop
│   ├── router/                 # Context Router (intent + ranking)
│   ├── audit/                  # Audit log
│   └── models.py               # Core domain models (6 abstractions)
├── benchmarks/                 # 8 experiments (5 correctness + 3 value)
├── formal/                     # TLA+ and Alloy specifications
├── manifests/                  # Example YAML manifests
├── seed_data/                  # Realistic test company data
└── tests/                      # 92 automated tests
    ├── unit/                   # Unit tests
    └── integration/            # API integration tests
```

## Formal Specifications

| Spec | Tool | What It Verifies |
|---|---|---|
| `formal/ReconciliationLoop.tla` | TLA+ | Safety: no expired content served. Liveness: stale detected within bounded time. |
| `formal/PermissionModel.als` | Alloy | Agent permissions are a strict subset. No self-escalation. No self-approval. |

## Citation

```bibtex
@article{mouzouni2026contextk8s,
  title={Context Kubernetes: Declarative Orchestration of Enterprise Knowledge
         for Agentic AI Systems},
  author={Mouzouni, Charafeddine},
  journal={arXiv preprint arXiv:2604.11623},
  year={2026}
}
```

## Related

- [**The Enterprise Agentic Platform**](https://www.cohorte.co/playbooks/the-enterprise-agentic-platform) — The companion book introducing the broader context for enterprise agentic systems
- [**theaios-trustgate**](https://github.com/Cohorte-ai/trustgate) — Black-box AI reliability certification via self-consistency sampling and conformal prediction

## License

[Apache 2.0](LICENSE)
