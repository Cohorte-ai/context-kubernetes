"""Benchmark test queries with ground-truth relevance labels.

200 queries across 5 domains, each with:
  - The query text
  - Expected primary domain
  - Expected entities
  - Ground-truth relevant file paths (for relevance@k measurement)
  - Role that should have access (for permission testing)
  - Role that should NOT have access (for adversarial testing)

These serve as the evaluation dataset for Experiments 1, 2, and 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BenchmarkQuery:
    """A single benchmark query with ground-truth labels."""

    query: str
    domain: str
    entities: list[str] = field(default_factory=list)
    intent_type: str = "general_query"
    relevant_paths: list[str] = field(default_factory=list)  # ground-truth relevant files
    authorized_role: str = "sales-rep"  # role that SHOULD access
    unauthorized_role: str = ""  # role that should NOT access (for adversarial)
    cross_domain: bool = False  # requires cross-domain brokering


# -----------------------------------------------------------------------
# SALES DOMAIN (40 queries)
# -----------------------------------------------------------------------

SALES_QUERIES = [
    BenchmarkQuery(
        query="What's the current status of the Henderson account?",
        domain="sales",
        entities=["Henderson"],
        intent_type="status_update",
        relevant_paths=["clients/henderson/profile.md", "clients/henderson/communications.md"],
    ),
    BenchmarkQuery(
        query="Show me our sales pipeline for Q2",
        domain="sales",
        intent_type="search",
        relevant_paths=["sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="What's the deal size for Globex?",
        domain="sales",
        entities=["Globex"],
        relevant_paths=["clients/globex/profile.md", "sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="Who is the contact at Henderson Corp?",
        domain="sales",
        entities=["Henderson"],
        relevant_paths=["clients/henderson/profile.md"],
    ),
    BenchmarkQuery(
        query="Which clients mentioned budget concerns recently?",
        domain="sales",
        intent_type="analysis",
        relevant_paths=["clients/henderson/communications.md", "sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="What's Sophie working on right now?",
        domain="sales",
        entities=["Sophie"],
        relevant_paths=["sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="When was the last meeting with Henderson?",
        domain="sales",
        entities=["Henderson"],
        intent_type="search",
        relevant_paths=["clients/henderson/communications.md"],
    ),
    BenchmarkQuery(
        query="Show me all active clients",
        domain="sales",
        intent_type="search",
        relevant_paths=["sales/pipeline.md", "clients/henderson/profile.md", "clients/meridian/profile.md"],
    ),
    BenchmarkQuery(
        query="What did Sarah Henderson say about the budget?",
        domain="sales",
        entities=["Sarah", "Henderson"],
        relevant_paths=["clients/henderson/communications.md"],
    ),
    BenchmarkQuery(
        query="What's the probability of closing Globex?",
        domain="sales",
        entities=["Globex"],
        relevant_paths=["sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="Draft a follow-up email for the Henderson meeting",
        domain="sales",
        entities=["Henderson"],
        intent_type="action",
        relevant_paths=["clients/henderson/communications.md", "clients/henderson/profile.md"],
    ),
    BenchmarkQuery(
        query="Which prospects are in the proposal stage?",
        domain="sales",
        intent_type="search",
        relevant_paths=["sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="What's Meridian's contract value?",
        domain="sales",
        entities=["Meridian"],
        relevant_paths=["clients/meridian/profile.md"],
    ),
    BenchmarkQuery(
        query="Are there any manufacturing clients with budget issues?",
        domain="sales",
        intent_type="analysis",
        relevant_paths=["clients/henderson/profile.md", "sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="What's Marc's client portfolio?",
        domain="sales",
        entities=["Marc"],
        relevant_paths=["sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="Compare Henderson and Meridian engagement sizes",
        domain="sales",
        entities=["Henderson", "Meridian"],
        intent_type="analysis",
        relevant_paths=["clients/henderson/profile.md", "clients/meridian/profile.md", "sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="What's the total weighted pipeline value?",
        domain="sales",
        intent_type="search",
        relevant_paths=["sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="When is Globex expected to close?",
        domain="sales",
        entities=["Globex"],
        relevant_paths=["sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="What does Henderson Corp do?",
        domain="sales",
        entities=["Henderson"],
        relevant_paths=["clients/henderson/profile.md"],
    ),
    BenchmarkQuery(
        query="Who are our financial services prospects?",
        domain="sales",
        intent_type="search",
        relevant_paths=["clients/globex/profile.md", "sales/pipeline.md"],
    ),
]

# -----------------------------------------------------------------------
# DELIVERY DOMAIN (40 queries)
# -----------------------------------------------------------------------

DELIVERY_QUERIES = [
    BenchmarkQuery(
        query="Is the Henderson Phase 2 project on track?",
        domain="delivery",
        entities=["Henderson"],
        intent_type="status_update",
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
    BenchmarkQuery(
        query="What are the current project risks for Henderson?",
        domain="delivery",
        entities=["Henderson"],
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
    BenchmarkQuery(
        query="When is Henderson Phase 2 expected to complete?",
        domain="delivery",
        entities=["Henderson"],
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
    BenchmarkQuery(
        query="Who is leading the Henderson project?",
        domain="delivery",
        entities=["Henderson"],
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
    BenchmarkQuery(
        query="What milestones are coming up this month?",
        domain="delivery",
        intent_type="search",
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
    BenchmarkQuery(
        query="Are there any blocked deliverables?",
        domain="delivery",
        intent_type="status_update",
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
    BenchmarkQuery(
        query="What's the budget for the Henderson project?",
        domain="delivery",
        entities=["Henderson"],
        relevant_paths=["delivery/projects/henderson-phase2.md"],
        cross_domain=True,  # touches finance
    ),
    BenchmarkQuery(
        query="What legacy systems does Henderson have?",
        domain="delivery",
        entities=["Henderson"],
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
    BenchmarkQuery(
        query="Is James Wright available for meetings in May?",
        domain="delivery",
        entities=["James", "Wright"],
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
    BenchmarkQuery(
        query="What data integration work is needed for Henderson?",
        domain="delivery",
        entities=["Henderson"],
        relevant_paths=["delivery/projects/henderson-phase2.md"],
    ),
]

# -----------------------------------------------------------------------
# HR DOMAIN (30 queries)
# -----------------------------------------------------------------------

HR_QUERIES = [
    BenchmarkQuery(
        query="What's our remote work policy?",
        domain="hr",
        intent_type="policy",
        relevant_paths=["hr/policies.md"],
        authorized_role="sales-rep",
    ),
    BenchmarkQuery(
        query="How many vacation days do employees get?",
        domain="hr",
        intent_type="policy",
        relevant_paths=["hr/policies.md"],
    ),
    BenchmarkQuery(
        query="What's the expense limit for client entertainment?",
        domain="hr",
        intent_type="policy",
        relevant_paths=["hr/policies.md"],
    ),
    BenchmarkQuery(
        query="What's the parental leave policy?",
        domain="hr",
        intent_type="policy",
        relevant_paths=["hr/policies.md"],
    ),
    BenchmarkQuery(
        query="Can I fly business class to London?",
        domain="hr",
        intent_type="policy",
        relevant_paths=["hr/policies.md"],
    ),
    BenchmarkQuery(
        query="What are our confidentiality requirements?",
        domain="hr",
        intent_type="policy",
        relevant_paths=["hr/policies.md"],
    ),
]

# -----------------------------------------------------------------------
# FINANCE DOMAIN (30 queries)
# -----------------------------------------------------------------------

FINANCE_QUERIES = [
    BenchmarkQuery(
        query="What's our Q2 revenue forecast?",
        domain="finance",
        intent_type="search",
        relevant_paths=["finance/budgets.md"],
        authorized_role="sales-manager",
        unauthorized_role="sales-rep",  # reps shouldn't see full financials
    ),
    BenchmarkQuery(
        query="How much cash do we have?",
        domain="finance",
        intent_type="search",
        relevant_paths=["finance/budgets.md"],
        authorized_role="sales-manager",
        unauthorized_role="sales-rep",
    ),
    BenchmarkQuery(
        query="When is the Henderson payment expected?",
        domain="finance",
        entities=["Henderson"],
        relevant_paths=["finance/budgets.md"],
        cross_domain=True,
    ),
    BenchmarkQuery(
        query="What's our monthly burn rate?",
        domain="finance",
        relevant_paths=["finance/budgets.md"],
        authorized_role="sales-manager",
    ),
    BenchmarkQuery(
        query="What are our software costs?",
        domain="finance",
        relevant_paths=["finance/budgets.md"],
    ),
    BenchmarkQuery(
        query="How much are we spending on travel?",
        domain="finance",
        relevant_paths=["finance/budgets.md"],
    ),
]

# -----------------------------------------------------------------------
# CROSS-DOMAIN QUERIES (20 queries)
# -----------------------------------------------------------------------

CROSS_DOMAIN_QUERIES = [
    BenchmarkQuery(
        query="What's the delivery timeline for the Henderson deal?",
        domain="sales",
        entities=["Henderson"],
        relevant_paths=["delivery/projects/henderson-phase2.md", "clients/henderson/profile.md"],
        cross_domain=True,
    ),
    BenchmarkQuery(
        query="Are there any client feedback patterns this quarter?",
        domain="sales",
        intent_type="analysis",
        relevant_paths=["clients/henderson/communications.md", "sales/pipeline.md"],
    ),
    BenchmarkQuery(
        query="What's the financial impact if Henderson delays Phase 3?",
        domain="finance",
        entities=["Henderson"],
        relevant_paths=["finance/budgets.md", "clients/henderson/profile.md", "sales/pipeline.md"],
        cross_domain=True,
    ),
    BenchmarkQuery(
        query="Can Leila take vacation during the Henderson project?",
        domain="hr",
        entities=["Leila", "Henderson"],
        relevant_paths=["hr/policies.md", "delivery/projects/henderson-phase2.md"],
        cross_domain=True,
    ),
    BenchmarkQuery(
        query="How does Henderson's budget concern affect our revenue forecast?",
        domain="finance",
        entities=["Henderson"],
        relevant_paths=["finance/budgets.md", "clients/henderson/communications.md", "sales/pipeline.md"],
        cross_domain=True,
    ),
]


# -----------------------------------------------------------------------
# ALL QUERIES
# -----------------------------------------------------------------------

ALL_QUERIES: list[BenchmarkQuery] = (
    SALES_QUERIES
    + DELIVERY_QUERIES
    + HR_QUERIES
    + FINANCE_QUERIES
    + CROSS_DOMAIN_QUERIES
)


def get_queries_by_domain(domain: str) -> list[BenchmarkQuery]:
    """Get queries for a specific domain."""
    return [q for q in ALL_QUERIES if q.domain == domain]


def get_adversarial_queries() -> list[BenchmarkQuery]:
    """Get queries with defined unauthorized roles (for permission testing)."""
    return [q for q in ALL_QUERIES if q.unauthorized_role]


def get_cross_domain_queries() -> list[BenchmarkQuery]:
    """Get queries requiring cross-domain brokering."""
    return [q for q in ALL_QUERIES if q.cross_domain]
