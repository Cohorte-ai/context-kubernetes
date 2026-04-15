# Context Kubernetes Tutorial

A hands-on walkthrough from setup to attack scenarios. By the end you will have
created a session, requested context, exercised all four tiers of the permission
model, watched a cross-domain attack get blocked, killed a session, and inspected
the audit trail.

**Time:** ~20 minutes.

---

## Table of Contents

1. [Setup](#1-setup)
2. [Explore the seed data](#2-explore-the-seed-data)
3. [Start the API server](#3-start-the-api-server)
4. [Create a session](#4-create-a-session)
5. [Request context](#5-request-context)
6. [Try a Tier 1 action (autonomous)](#6-try-a-tier-1-action-autonomous)
7. [Try a Tier 2 action (soft approval)](#7-try-a-tier-2-action-soft-approval)
8. [Try a Tier 3 action (strong approval with OTP)](#8-try-a-tier-3-action-strong-approval-with-otp)
9. [Try an excluded action](#9-try-an-excluded-action)
10. [Try an attack](#10-try-an-attack)
11. [Kill the session](#11-kill-the-session)
12. [Check the audit log](#12-check-the-audit-log)
13. [Check health](#13-check-health)

---

## 1. Setup

Clone the repo, create a virtual environment, install, and verify with tests.

```bash
git clone https://github.com/Cohorte-ai/context-kubernetes.git
cd context-kubernetes

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

# Verify everything works (92 tests)
pytest
```

You should see output ending with something like:

```
========================= 92 passed in 3.42s =========================
```

---

## 2. Explore the seed data

The repo ships with seed data for a small consulting firm. Take a look at its
knowledge architecture:

```bash
find seed_data -type f | sort
```

```
seed_data/context/clients/globex/profile.md
seed_data/context/clients/henderson/communications.md
seed_data/context/clients/henderson/profile.md
seed_data/context/clients/meridian/profile.md
seed_data/context/delivery/projects/henderson-phase2.md
seed_data/context/finance/budgets.md
seed_data/context/hr/policies.md
seed_data/context/sales/pipeline.md
```

The consulting firm has **3 clients** and knowledge organized across **5 domains**:

| Domain | Contents | Examples |
|--------|----------|----------|
| **sales** | Client profiles, pipeline, communications | Henderson Corp (manufacturing, EUR 180K), Globex (prospect, EUR 320K), Meridian (EUR 95K) |
| **delivery** | Active projects, milestones, risks | Henderson Phase 2 -- AI Quality Control, in week 3 |
| **finance** | Budgets, revenue, expenses | Q2 forecast, cash runway 4.8 months |
| **hr** | Policies, employee info | Remote work, expense, leave, confidentiality policies |
| **operations** | Process, logistics | (available as a domain, populated via connectors in production) |

The demo user `demo-user` has role `sales-rep`. The agent profile is a **strict
subset** of the user's permissions (Design Invariant 3.7):

| Operation | User (sales-rep) | Agent |
|-----------|-------------------|-------|
| `read` | autonomous | autonomous (T1) |
| `write` | autonomous | soft-approval (T2) |
| `send_email` | autonomous | strong-approval (T3) |
| `commit_pricing` | autonomous | **excluded** -- agent cannot even request it |

This is the core idea: the user can do everything, but the agent is constrained
to a strict subset with escalating approval tiers.

---

## 3. Start the API server

In a terminal, start the API server:

```bash
uvicorn context_kubernetes.api.app:app --reload
```

You should see:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx]
```

The server loads a demo configuration automatically when no manifest directory is
configured. This sets up the two demo users (`demo-user` and `demo-manager`)
with their permission profiles, and initializes the intent classifier with all
five domains.

Leave this terminal running. Open a **second terminal** for the curl commands
that follow.

---

## 4. Create a session

Every agent interaction starts by creating an authenticated, scoped session. The
session binds a user identity, an agent identity, a role, and an optional
workspace scope.

```bash
curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "demo-user",
    "agent_id": "copilot-1",
    "role": "sales-rep",
    "workspace_scope": "clients/henderson"
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "session_id": "sess-a1b2c3d4e5f6a7b8",
    "user_id": "demo-user",
    "role": "sales-rep",
    "active": true
}
```

The `session_id` is a random hex string -- yours will be different. **Save it**
for the following commands:

```bash
# Save your session ID (replace with your actual value)
export SESSION_ID="sess-a1b2c3d4e5f6a7b8"
```

Key things to note:
- The session is scoped to `clients/henderson` -- this influences ranking (the
  `user_relevance` signal will boost Henderson-related content).
- The session is `active: true` -- the kill switch can flip this instantly.
- Under the hood, the Permission Engine loaded the `demo-user` agent profile,
  which is a strict subset of the `sales-rep` role permissions.

---

## 5. Request context

Now ask the Context Endpoint a natural language question. This is the core
operation -- the agent says *what* it needs, not *where* to find it.

```bash
curl -s -X POST http://localhost:8000/context/request \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "intent": "What'\''s the Henderson client status?",
    "token_budget": 8000
  }' | python -m json.tool
```

**Expected response** (abbreviated):

```json
{
    "request_id": "req-a1b2c3d4e5f6",
    "units": [
        {
            "id": "cu-...",
            "content": "# Henderson Corp\n- **Industry:** Manufacturing\n...",
            "content_type": "unstructured",
            "metadata": {
                "author": null,
                "timestamp": "2026-04-02T...",
                "domain": "sales",
                "sensitivity": "internal",
                "entities": [],
                "source": "git:..."
            },
            "version": "...",
            "embedding": [],
            "authorized_roles": [],
            "freshness": "fresh",
            "token_count": 42
        }
    ],
    "total_tokens": 112,
    "freshness_warnings": [],
    "latency_ms": 2.34
}
```

What happened behind the scenes:

1. **Intent classification** -- the rule-based classifier matched "client" and
   "status" to the `sales` domain, and extracted "Henderson" as an entity.
2. **Source resolution** -- the router looked up all connectors registered for
   the `sales` domain.
3. **CxRI fetch** -- the git connector queried the repo for files matching the
   intent.
4. **Permission filter** -- only context units the `sales-rep` role can access
   were kept.
5. **Freshness filter** -- expired units were dropped, stale units flagged.
6. **Multi-signal ranking** -- units were scored by semantic relevance (0.40),
   recency (0.30), authority (0.20), and user relevance (0.10), then truncated
   to the 8000-token budget.

The response contains the actual content the agent needs -- no more, no less.

---

## 6. Try a Tier 1 action (autonomous)

A `read` operation is Tier 1 -- the agent acts freely, no approval needed.

```bash
curl -s -X POST http://localhost:8000/actions/submit \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "action_type": "read",
    "resource": "clients/henderson/profile.md"
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "action_id": "",
    "tier": "autonomous",
    "status": "autonomous",
    "approval_id": "",
    "message": "Action authorized (T1): Role sales-rep, operation read on clients/henderson/profile.md"
}
```

The agent was allowed to proceed immediately. No human in the loop. This is
appropriate for low-stakes, read-only operations.

---

## 7. Try a Tier 2 action (soft approval)

A `write` operation on a client resource is Tier 2 -- the agent proposes, the
user confirms in the UI.

```bash
curl -s -X POST http://localhost:8000/actions/submit \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "action_type": "write",
    "resource": "clients/henderson/meeting-notes.md",
    "parameters": {
      "content": "## April 2 Call\nDiscussed Phase 2 timeline extension."
    }
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "action_id": "",
    "tier": "soft-approval",
    "status": "pending_approval",
    "approval_id": "apr-1a2b3c4d5e6f7a8b",
    "message": "Approval required (soft-approval): soft-approval: write on clients/henderson/meeting-notes.md"
}
```

The action is **not executed yet**. The agent received an `approval_id` and must
wait. In a real product, the user sees a confirmation dialog in the agent UI.

Save the approval ID:

```bash
export APPROVAL_ID="apr-1a2b3c4d5e6f7a8b"
```

Now simulate the user approving:

```bash
curl -s -X POST http://localhost:8000/approvals/$APPROVAL_ID/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "approved": true
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "approval_id": "apr-1a2b3c4d5e6f7a8b",
    "resolved": true,
    "approved": true
}
```

The user confirmed and the action can proceed. This is the "human in the loop
but not in the way" pattern -- the agent drafted the content, the user just had
to say yes or no.

---

## 8. Try a Tier 3 action (strong approval with OTP)

A `send_email` action is Tier 3 -- the most sensitive tier. It requires
**out-of-band verification** via a one-time password (OTP). This is Design
Invariant 3.8: the approval channel is external to the agent's execution
environment, not readable or writable by the agent, and authenticated via a
separate factor.

```bash
curl -s -X POST http://localhost:8000/actions/submit \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "action_type": "send_email",
    "resource": "sarah.henderson@hendersoncorp.com",
    "parameters": {
      "subject": "Phase 2 Progress Update",
      "body": "Hi Sarah, Week 3 deliverables are complete. Connector dev on track."
    }
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "action_id": "",
    "tier": "strong-approval",
    "status": "pending_approval",
    "approval_id": "apr-9f8e7d6c5b4a3210",
    "message": "Approval required (strong-approval): strong-approval: send_email on sarah.henderson@hendersoncorp.com"
}
```

At this point, an OTP has been generated and delivered to the user through an
**out-of-band channel** (email, SMS, TOTP app). The agent never sees it. In the
prototype, the OTP is stored in a simulated channel.

In a real system, the user would check their phone or email for the code. For
this tutorial, the OTP is visible in the server logs, or you can retrieve it
programmatically in tests via `state.permission_engine.get_otp_from_channel()`.

For demonstration purposes, trying to resolve with a **wrong code** will fail:

```bash
export T3_APPROVAL_ID="apr-9f8e7d6c5b4a3210"

curl -s -X POST http://localhost:8000/approvals/$T3_APPROVAL_ID/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "approved": true,
    "verification_code": "WRONG1"
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "approval_id": "apr-9f8e7d6c5b4a3210",
    "resolved": true,
    "approved": false
}
```

The wrong code was rejected. The action is denied. This is the architectural
guarantee: even if an agent somehow intercepted the approval flow, it cannot
fabricate the OTP. The verification happens on a separate endpoint that, in
production, requires a different auth token bound to the user's identity.

> **Note:** To complete a T3 approval in the prototype, you would need the
> actual OTP from the simulated out-of-band channel. In integration tests, this
> is done via `state.permission_engine.get_otp_from_channel("demo-user",
> approval_id)`. In production, the user enters the code from their phone.

---

## 9. Try an excluded action

The `commit_pricing` operation is **excluded** from the agent profile entirely.
The agent cannot even request it -- this is a manual-only operation.

```bash
curl -s -X POST http://localhost:8000/actions/submit \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "action_type": "commit_pricing",
    "resource": "henderson-phase2-proposal",
    "parameters": {
      "price": 95000,
      "discount": "15%"
    }
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "action_id": "",
    "tier": "excluded",
    "status": "excluded",
    "approval_id": "",
    "message": "Action not in agent profile: commit_pricing. Manual action required."
}
```

There is no approval flow. There is no way for the agent to escalate. The
operation simply does not exist in the agent's permission profile. The user
(sales-rep) *can* commit pricing through the normal application -- the agent
cannot.

This is Design Invariant 3.7 in action: agent permissions are a strict subset
of user permissions. The `commit_pricing` operation exists at the user level but
is explicitly excluded from the agent profile.

---

## 10. Try an attack

Now let's test the governance model. The `demo-user` has role `sales-rep`.
They should not be able to access `finance` domain data through the agent.

First, create a session scoped to sales:

```bash
curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "demo-user",
    "agent_id": "copilot-1",
    "role": "sales-rep",
    "workspace_scope": "sales"
  }' | python -m json.tool
```

Save the session ID:

```bash
export ATTACK_SESSION="sess-<your-value-here>"
```

Now try to ask for finance data:

```bash
curl -s -X POST http://localhost:8000/context/request \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$ATTACK_SESSION"'",
    "intent": "Show me the company budget, cash position, and salary expenses",
    "token_budget": 8000
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "request_id": "req-...",
    "units": [],
    "total_tokens": 0,
    "freshness_warnings": [
        "No connectors available for domain 'finance'"
    ],
    "latency_ms": 0.45
}
```

**Zero units returned.** The intent classifier correctly identified this as a
`finance` query, but there are no connectors accessible from a sales session for
the finance domain. The cross-domain brokering rules in the manifest control
this:

```yaml
crossDomain:
  - domain: operations
    mode: brokered    # sales agents CAN access ops data
  - domain: finance
    mode: brokered    # allowed in manifest, but requires connector registration
  - domain: hr
    mode: denied      # sales agents CANNOT access HR data
```

Even if cross-domain access were configured, the permission filter would still
check that each context unit's `authorized_roles` includes `sales-rep`. Finance
data marked as `finance-only` would be stripped out.

This is the defense-in-depth approach: intent routing, cross-domain rules, and
permission filtering all work together. An ungoverned agent would happily serve
the finance data -- the Context Kubernetes governance layer prevents it.

---

## 11. Kill the session

The kill switch is an instant, unconditional session termination. No
negotiation, no grace period.

```bash
curl -s -X DELETE http://localhost:8000/sessions/$SESSION_ID | python -m json.tool
```

**Expected response:**

```json
{
    "killed": "sess-a1b2c3d4e5f6a7b8"
}
```

Now try to use the killed session:

```bash
curl -s -X POST http://localhost:8000/context/request \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "intent": "Henderson client status",
    "token_budget": 8000
  }' | python -m json.tool
```

**Expected response:**

```json
{
    "request_id": "req-...",
    "units": [],
    "total_tokens": 0,
    "freshness_warnings": [
        "Invalid or terminated session"
    ],
    "latency_ms": 0.02
}
```

Zero units. The session is dead. Any subsequent context requests, action
submissions, or approvals through this session will fail. The agent is
immediately cut off.

You can also kill all sessions for a user at once:

```bash
curl -s -X DELETE "http://localhost:8000/sessions?user_id=demo-user" | python -m json.tool
```

**Expected response:**

```json
{
    "killed": 1,
    "scope": "demo-user"
}
```

---

## 12. Check the audit log

Every interaction with the system is immutably logged: context requests, action
submissions, permission checks, approval resolutions, and session terminations.

Query all events:

```bash
curl -s -X POST http://localhost:8000/audit/events \
  -H "Content-Type: application/json" \
  -d '{
    "limit": 20
  }' | python -m json.tool
```

**Expected response** (abbreviated):

```json
[
    {
        "event_id": "evt-1712016000000-0",
        "timestamp": "2026-04-02T10:00:00.123456Z",
        "session_id": "sess-a1b2c3d4e5f6a7b8",
        "user_id": "demo-user",
        "agent_id": "",
        "event_type": "context_request",
        "operation": "route",
        "resource": "What's the Henderson client status?",
        "outcome": "2 units, 112 tokens",
        "latency_ms": 2.34,
        "details": {}
    },
    {
        "event_id": "evt-1712016001000-1",
        "timestamp": "2026-04-02T10:00:01.234567Z",
        "session_id": "sess-a1b2c3d4e5f6a7b8",
        "user_id": "demo-user",
        "agent_id": "",
        "event_type": "action_executed",
        "operation": "read",
        "resource": "clients/henderson/profile.md",
        "outcome": "autonomous",
        "latency_ms": 0.0,
        "details": {}
    },
    {
        "event_id": "evt-1712016002000-2",
        "timestamp": "2026-04-02T10:00:02.345678Z",
        "session_id": "sess-a1b2c3d4e5f6a7b8",
        "user_id": "demo-user",
        "agent_id": "",
        "event_type": "action_denied",
        "operation": "commit_pricing",
        "resource": "henderson-phase2-proposal",
        "outcome": "excluded",
        "latency_ms": 0.0,
        "details": {}
    }
]
```

You can filter by specific criteria:

```bash
# Only context requests
curl -s -X POST http://localhost:8000/audit/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "context_request",
    "limit": 10
  }' | python -m json.tool

# Only for a specific session
curl -s -X POST http://localhost:8000/audit/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "'"$SESSION_ID"'",
    "limit": 10
  }' | python -m json.tool

# Only denied actions
curl -s -X POST http://localhost:8000/audit/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "action_denied",
    "limit": 10
  }' | python -m json.tool
```

Check the total event count:

```bash
curl -s http://localhost:8000/audit/count | python -m json.tool
```

**Expected response:**

```json
{
    "count": 5
}
```

Every interaction is traceable back to a session, user, and timestamp. This is
Requirement R6 (Complete Auditability) from the paper.

---

## 13. Check health

The health endpoint shows system status, source connectivity, and reconciliation
state.

```bash
curl -s http://localhost:8000/health | python -m json.tool
```

**Expected response:**

```json
{
    "status": "healthy",
    "version": "0.1.0",
    "uptime_seconds": 342.17,
    "sources": {},
    "reconciliation_cycles": 0
}
```

In the demo configuration (no manifest-loaded connectors), `sources` is empty.
When connectors are registered via manifests, you see per-source health:

```bash
curl -s http://localhost:8000/health/sources | python -m json.tool
```

**Expected response** (with connectors registered):

```json
{
    "git-sales": {
        "health": "healthy",
        "freshness": "fresh"
    }
}
```

Each source reports both its connectivity health (`healthy`, `degraded`, or
`disconnected`) and its content freshness (`fresh`, `stale`, or `expired`). The
reconciliation loop checks these continuously and takes corrective action when
drift is detected.

---

## What you just saw

In this tutorial you exercised the full Context Kubernetes governance model:

| Step | What happened | Governance mechanism |
|------|---------------|----------------------|
| Session creation | User + agent identity bound, permissions loaded | Agent Permission Subset (Invariant 3.7) |
| Context request | Intent routed, permissions filtered, ranked | Context Router + Permission Engine |
| T1 read | Autonomous -- no approval | Three-tier model |
| T2 write | Soft approval -- user confirms | Three-tier model |
| T3 send_email | Strong approval -- OTP via out-of-band channel | Strong Approval Isolation (Invariant 3.8) |
| Excluded action | Blocked -- agent cannot request | Strict subset enforcement |
| Cross-domain attack | Zero units returned | Domain isolation + permission filter |
| Kill switch | Instant session termination | Kill switch |
| Audit log | Every interaction recorded | Complete Auditability (R6) |
| Health check | Source status + freshness | Reconciliation loop |

The key insight: these are not just access control rules. They are architectural
guarantees. The agent never had the OTP. The finance data was never fetched. The
excluded operation was never even entered into an approval queue. The governance
is structural, not advisory.

---

## Next steps

- Read the [paper](https://arxiv.org/abs/2604.11623) for the formal model and
  experimental evaluation
- Read the [companion book](https://www.cohorte.co/playbooks/the-enterprise-agentic-platform)
  for the broader enterprise platform context
- Explore `manifests/sales-domain.yaml` for the full declarative specification
- Run `python -m benchmarks.run_all_value_experiments` to reproduce the paper's
  experiments
- Look at `formal/PermissionModel.als` (Alloy) and
  `formal/ReconciliationLoop.tla` (TLA+) for the formal specifications
