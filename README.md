# Context Kubernetes

**Declarative Orchestration of Enterprise Knowledge for Agentic AI Systems**

Context Kubernetes is the orchestration layer for organizational knowledge in the age of AI agents. It provides declarative, vendor-neutral governance for delivering the right knowledge, to the right agent, with the right permissions, at the right freshness, within the right cost envelope.

## Architecture

```
AGENTS (any framework, any LLM)
    │
Context API (15 operations · HTTPS + WSS · JWT)
    │
CONTEXT KUBERNETES
    ├── Context Registry    (metadata store)
    ├── Context Router      (intent-based routing)
    ├── Permission Engine   (3-tier agent approval)
    ├── Freshness Manager   (TTL monitoring)
    ├── Trust Policy Engine (guardrails, DLP, audit)
    ├── Context Operators   (domain intelligence)
    └── LLM Gateway         (prompt inspection, cost metering)
    │
Context Runtime Interface (CxRI · 6 operations per connector)
    │
CONTEXT SOURCES (Git repos, databases, email, SaaS APIs, ERP)
```

## Core Abstractions

| Abstraction | Description |
|---|---|
| **Context Unit** | Smallest addressable element of organizational knowledge |
| **Context Domain** | Isolation boundary (sales, HR, legal, ops) |
| **Context Store** | Backing storage accessed through CxRI |
| **Context Endpoint** | Stable, intent-based interface for knowledge access |
| **Context Operator** | Domain-specific intelligence controller |
| **CxRI** | Standard 6-operation adapter to any data source |

## Key Design Invariants

1. **Agent permissions are a strict subset of user permissions.** No mechanism exists for an agent to exceed its user's authority.
2. **Strong approval is architecturally isolated.** Tier 3 approval channels are external to the agent's execution environment, not readable/writable by the agent, and require a separate authentication factor.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Manifest Example

Knowledge architecture is defined as code in YAML manifests:

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
        commit-to-pricing: excluded

  freshness:
    defaults: {maxAge: 24h, staleAction: flag}

  routing:
    intentParsing: llm-assisted
    tokenBudget: 8000
```

## Paper

This implementation accompanies the paper:

> **Context Kubernetes: Declarative Orchestration of Enterprise Knowledge for Agentic AI Systems**
> Charafeddine Mouzouni, 2026.

## License

Apache 2.0
