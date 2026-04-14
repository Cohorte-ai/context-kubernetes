# Context Kubernetes — Next Steps

**Paper submitted to arXiv:** April 2026
**Repo:** https://github.com/Cohorte-ai/context-kubernetes
**Current state:** 24-page paper, ~7,000-line prototype, 92 tests, 8 experiments

---

## Track 1: Make the Experiment Results Undeniable

**Timeline:** 2 weeks
**Goal:** Transform V1 (governed vs ungoverned) from modest improvement to dramatic difference

### 1.1 Add LLM-Assisted Intent Routing (Week 1)

The prototype uses rule-based intent classification (70.2% domain accuracy). The architecture specifies LLM-assisted parsing. The code already has the hook (`IntentClassifier(llm_client=...)` in `context_kubernetes/router/intent.py`). Plug it in.

**Tasks:**
- [ ] Integrate gpt-4o-mini (or Claude Haiku) into the IntentClassifier
- [ ] Structured JSON output: `{primary_domain, entities, intent_type, time_scope, secondary_domains, confidence}`
- [ ] Fallback: if LLM confidence < 0.7 or LLM fails, fall back to rule-based (already implemented)
- [ ] Cache intent classifications for repeated queries (already implemented)
- [ ] Run all 47 queries through both pipelines
- [ ] Record: domain accuracy (expect 90%+), MRR improvement, latency delta

**Expected outcome:** Domain accuracy jumps from 70% to 90%+. The governed pipeline's precision advantage over ungoverned becomes dramatic — because correct domain routing means the permission and freshness filters operate on relevant candidates, not noise.

**How to measure:** Run `python -m benchmarks.exp1_routing_quality` with `--mode llm` flag. Compare rule-based vs LLM-assisted side by side. Report both in the paper as "floor" and "ceiling."

### 1.2 Expand Query Set to 200 (Week 2)

47 queries is thin. 200 queries with ground-truth labels is a benchmark.

**Tasks:**
- [ ] Expand `benchmarks/test_queries.py` to 200 queries across 5 domains
  - 50 sales, 50 delivery, 30 HR, 30 finance, 40 cross-domain
- [ ] Each query: expected domain, entities, relevant paths, authorized/unauthorized roles
- [ ] Two annotators label ground truth independently (you + one colleague)
- [ ] Compute inter-annotator agreement (Cohen's kappa)
- [ ] Re-run all experiments with the expanded set
- [ ] Report: relevance@5, relevance@10, MRR with confidence intervals

**Expected outcome:** Statistical significance. A reviewer can't dismiss "200 queries, κ=0.85" the way they can dismiss "47 queries, author-labeled."

### 1.3 Update arXiv Paper (End of Week 2)

- [ ] Add LLM-assisted results to Section 7 (Evaluation)
- [ ] Update Table 6 (governed vs ungoverned) with both rule-based and LLM-assisted rows
- [ ] Update abstract numbers if they change
- [ ] Update V1 discussion to show the quality gap between rule-based floor and LLM ceiling
- [ ] Submit as arXiv v2

---

## Track 2: Submit to Conference

**Timeline:** 2 months (targeting ICSA 2027, deadline ~November 2026)
**Goal:** Peer-reviewed publication

### 2.1 Independent Evaluation (Weeks 3-4)

The gap analysis (Table 8) is self-assessed. One independent evaluator transforms it from "author's opinion" to "validated finding."

**Tasks:**
- [ ] Identify 1 enterprise architect who has deployed Copilot Studio, Agentforce, or Bedrock
- [ ] Design evaluation rubric: 7 requirements × 6 platforms × 3 ratings (Addressed/Partial/Gap)
- [ ] Share rubric + platform documentation with evaluator
- [ ] Evaluator independently rates all platforms
- [ ] Compute agreement between author and evaluator ratings
- [ ] Update Table 8 with independent validation note
- [ ] If ratings differ: document the disagreement honestly — it's more credible than fake agreement

**Where to find evaluators:**
- OPIT colleagues with enterprise deployment experience
- Newsletter subscribers (15K) who work at enterprises deploying AI agents
- LinkedIn network: post asking for volunteer reviewers (offer co-authorship if contribution is substantial)

### 2.2 Formal Verification (Weeks 3-5, parallel)

TLA+ and Alloy specs are written but not model-checked.

**Tasks:**
- [ ] Install Java runtime: `brew install openjdk`
- [ ] Download TLA+ tools: https://github.com/tlaplus/tlaplus/releases
- [ ] Run TLC: `java -jar tla2tools.jar -config ReconciliationLoop.cfg ReconciliationLoop.tla`
- [ ] Download Alloy Analyzer: https://alloytools.org/download.html
- [ ] Run all 5 Alloy assertions: `check invariant_37_strict_subset` etc.
- [ ] Record: state space explored, counterexamples found (expect 0)
- [ ] Add results to paper Section 9.1 (Limitations): upgrade "tested empirically" to "verified by model-checking"

### 2.3 Conference Submission (Week 8)

- [ ] Incorporate Track 1 results (LLM-assisted, 200 queries)
- [ ] Incorporate independent evaluation results
- [ ] Incorporate formal verification results
- [ ] Tighten writing based on any feedback received on arXiv version
- [ ] Format for ICSA 2027 submission requirements
- [ ] Submit

**Backup venue:** IEEE Software (rolling submissions, no deadline, practitioner audience)

---

## Track 3: Build the Community

**Timeline:** Starting now, ongoing
**Goal:** Convert readers into users and contributors

### 3.1 Tutorial: "Your First Context Kubernetes Deployment" (Week 1)

Not the README (reference docs). A narrative walkthrough.

**Structure:**
1. Clone the repo, install, run tests (2 min)
2. Explore the seed data — a consulting firm with 3 clients (2 min)
3. Start the API server with `uvicorn`
4. Create a session via `curl POST /sessions`
5. Request context: "What's the Henderson client status?" → see the routed, filtered result
6. Submit an action: "Send email to client" → see the Tier 3 approval flow
7. Try an attack: query finance data from a sales session → see it blocked
8. Kill the session → see subsequent requests denied

**Deliverable:** `docs/tutorial.md` in the repo. Link from README.

### 3.2 Community Launch Post (Week 1)

Write one post. Adapt for three platforms.

**Hook:** "We built Context Kubernetes — the governance layer for AI agents accessing organizational knowledge. In five attack scenarios, flat permissions block 0/5 attacks. Basic RBAC blocks 4/5. The three-tier model blocks 5/5. Here's the paper and the code."

**Platforms:**
- [ ] Hacker News: title "Context Kubernetes: Declarative orchestration of enterprise knowledge for AI agents", link to paper
- [ ] r/MachineLearning: flair [Research], link to paper + repo
- [ ] LinkedIn: personal post with 3 key findings, link to paper + repo + book
- [ ] Twitter/X: thread format — 5 tweets, one per key finding

### 3.3 Good First Issues (Week 1)

Open these GitHub issues to signal the project welcomes contributors:

- [ ] **Issue: Add Slack CxRI connector** — Label: `good first issue`, `cxri`. Description: Implement the 6-operation CxRI interface for Slack (read channel messages, search, subscribe to new messages). Use the Git connector as a reference.

- [ ] **Issue: Add LLM-assisted intent classification** — Label: `enhancement`, `router`. Description: Integrate gpt-4o-mini or Claude Haiku into the IntentClassifier. The hook exists (`llm_client` parameter). Need: structured JSON output, confidence threshold, fallback to rule-based.

- [ ] **Issue: Docker Compose deployment** — Label: `good first issue`, `infra`. Description: Create `docker-compose.yml` that starts: FastAPI service, PostgreSQL (for structured data connector), Gitea (for git context repos), Redis (for session cache). One `docker compose up` to run the full stack.

- [ ] **Issue: OpenAPI schema export** — Label: `good first issue`, `api`. Description: Add `/openapi.json` endpoint and generate API documentation. FastAPI provides this automatically — just needs to be configured and tested.

- [ ] **Issue: Benchmark: add 150 more test queries** — Label: `help wanted`, `benchmarks`. Description: Expand `benchmarks/test_queries.py` from 47 to 200 queries. Need: diverse queries across 5 domains, ground-truth relevant paths, authorized/unauthorized role labels.

### 3.4 Newsletter Announcement (Week 2)

You have 15K subscribers. Use them.

**Content:** "I just published a paper and open-source prototype for Context Kubernetes — the missing governance layer for enterprise AI agents. Here's the core finding and why it matters for your company."

Link to: paper, repo, book, tutorial.

---

## Decision Points

| Decision | When | Options |
|---|---|---|
| LLM provider for routing | Week 1 | gpt-4o-mini (cheapest), Claude Haiku (fastest), local model (no API dependency) |
| Conference target | Week 4 | ICSA 2027 (architecture), EuroSys 2027 (systems), IEEE Software (practitioner) |
| Open source governance | Week 4 | Accept external PRs? CLA? Code of conduct? |
| Pilot deployment target | Month 2 | Own practice, OPIT research group, friendly client |

---

## Success Metrics (3 months)

| Metric | Target |
|---|---|
| arXiv version | v2 with LLM-assisted results |
| GitHub stars | 100+ |
| Conference submission | ICSA 2027 or IEEE Software |
| External contributors | 2+ PRs merged |
| Independent evaluation | 1+ external reviewer completed |
| Tutorial completion rate | Published and linked from README |
| Formal verification | TLA+ and Alloy model-checked, zero violations |
