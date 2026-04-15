"""Expanded benchmark: 200 queries across 5 domains.

Extends the original 47 queries to 200 for statistical significance.
Ground truth paths match the 8 seed data files:
  - clients/henderson/profile.md
  - clients/henderson/communications.md
  - clients/globex/profile.md
  - clients/meridian/profile.md
  - delivery/projects/henderson-phase2.md
  - finance/budgets.md
  - hr/policies.md
  - sales/pipeline.md
"""

from benchmarks.test_queries import BenchmarkQuery, SALES_QUERIES, DELIVERY_QUERIES, HR_QUERIES, FINANCE_QUERIES, CROSS_DOMAIN_QUERIES


# -----------------------------------------------------------------------
# ADDITIONAL SALES QUERIES (+30 → total 50)
# -----------------------------------------------------------------------

EXTRA_SALES = [
    BenchmarkQuery(query="What industry is Henderson in?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/profile.md"]),
    BenchmarkQuery(query="How long have we worked with Henderson?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/profile.md"]),
    BenchmarkQuery(query="What's Henderson's annual contract value?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/profile.md"]),
    BenchmarkQuery(query="Who manages the Henderson account?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/profile.md", "sales/pipeline.md"]),
    BenchmarkQuery(query="What are Henderson's key interests?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/profile.md"]),
    BenchmarkQuery(query="Tell me about Globex International", domain="sales", entities=["Globex"], relevant_paths=["clients/globex/profile.md"]),
    BenchmarkQuery(query="Who is the contact at Globex?", domain="sales", entities=["Globex"], relevant_paths=["clients/globex/profile.md"]),
    BenchmarkQuery(query="What's Globex's industry?", domain="sales", entities=["Globex"], relevant_paths=["clients/globex/profile.md"]),
    BenchmarkQuery(query="Is Globex an active client or a prospect?", domain="sales", entities=["Globex"], relevant_paths=["clients/globex/profile.md"]),
    BenchmarkQuery(query="What concerns does Globex have about data residency?", domain="sales", entities=["Globex"], relevant_paths=["clients/globex/profile.md"]),
    BenchmarkQuery(query="Tell me about Meridian Consulting", domain="sales", entities=["Meridian"], relevant_paths=["clients/meridian/profile.md"]),
    BenchmarkQuery(query="What's Meridian's contract value?", domain="sales", entities=["Meridian"], relevant_paths=["clients/meridian/profile.md"]),
    BenchmarkQuery(query="Who is Claire Moreau?", domain="sales", entities=["Claire", "Moreau"], relevant_paths=["clients/meridian/profile.md"]),
    BenchmarkQuery(query="What does Meridian need from us?", domain="sales", entities=["Meridian"], relevant_paths=["clients/meridian/profile.md"]),
    BenchmarkQuery(query="Is Meridian our pilot site?", domain="sales", entities=["Meridian"], relevant_paths=["clients/meridian/profile.md"]),
    BenchmarkQuery(query="List all clients and their stages", domain="sales", intent_type="search", relevant_paths=["sales/pipeline.md"]),
    BenchmarkQuery(query="What's our total active revenue?", domain="sales", relevant_paths=["sales/pipeline.md"]),
    BenchmarkQuery(query="Which deals are most likely to close?", domain="sales", intent_type="analysis", relevant_paths=["sales/pipeline.md"]),
    BenchmarkQuery(query="Who owns the Archon Group deal?", domain="sales", entities=["Archon"], relevant_paths=["sales/pipeline.md"]),
    BenchmarkQuery(query="What's the Nexus Technologies opportunity?", domain="sales", entities=["Nexus"], relevant_paths=["sales/pipeline.md"]),
    BenchmarkQuery(query="Are there any clients in financial services?", domain="sales", intent_type="search", relevant_paths=["clients/globex/profile.md"]),
    BenchmarkQuery(query="Summarize the March meeting with Henderson", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/communications.md"]),
    BenchmarkQuery(query="What was discussed about the delivery timeline with Henderson?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/communications.md"]),
    BenchmarkQuery(query="When did we kick off with Henderson?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/communications.md"]),
    BenchmarkQuery(query="What did James Wright say at the kickoff?", domain="sales", entities=["James", "Wright"], relevant_paths=["clients/henderson/communications.md"]),
    BenchmarkQuery(query="Has Sarah Henderson mentioned the CFO?", domain="sales", entities=["Sarah", "Henderson"], relevant_paths=["clients/henderson/communications.md"]),
    BenchmarkQuery(query="What proposals have we sent to Henderson?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/communications.md", "sales/pipeline.md"]),
    BenchmarkQuery(query="Show me all prospects in the discovery stage", domain="sales", intent_type="search", relevant_paths=["sales/pipeline.md"]),
    BenchmarkQuery(query="Which clients have the highest contract value?", domain="sales", intent_type="analysis", relevant_paths=["sales/pipeline.md", "clients/henderson/profile.md"]),
    BenchmarkQuery(query="When is Sophie's follow-up with Globex?", domain="sales", entities=["Sophie", "Globex"], relevant_paths=["sales/pipeline.md"]),
]

# -----------------------------------------------------------------------
# ADDITIONAL DELIVERY QUERIES (+30 → total 40)
# -----------------------------------------------------------------------

EXTRA_DELIVERY = [
    BenchmarkQuery(query="What phase is the Henderson project in?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Who is the project lead for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What's the budget for Henderson Phase 2?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Are there any risks on the Henderson project?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What week is the Henderson project in?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What's the data integration status for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="When does Henderson Phase 2 end?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What are the next milestones for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Is Leila Amrani available for the Henderson project?", domain="delivery", entities=["Leila", "Amrani", "Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What connectors are being built for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Has the AI model training started for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What deliverables are complete for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Is the Henderson project within budget?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What's the Henderson project start date?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Show me all active projects", domain="delivery", intent_type="search", relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Are any projects at risk?", domain="delivery", intent_type="status_update", relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What legacy systems does Henderson use?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="When will the knowledge transfer happen for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What's the deployment plan for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Is James Wright traveling in May?", domain="delivery", entities=["James", "Wright"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What was completed in weeks 1-2 of Henderson?", domain="delivery", entities=["Henderson"], intent_type="status_update", relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What are the Henderson project blockers?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="How complex is the data integration for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What's the scope of Henderson Phase 2?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Show me the Henderson milestone table", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What risk mitigation is in place for Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What's the Henderson target completion date?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="How many weeks is Henderson Phase 2?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="What engineering resources are allocated to Henderson?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
    BenchmarkQuery(query="Has Henderson's internal IT team been responsive?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"]),
]

# -----------------------------------------------------------------------
# ADDITIONAL HR QUERIES (+24 → total 30)
# -----------------------------------------------------------------------

EXTRA_HR = [
    BenchmarkQuery(query="How many days of annual leave do we get?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What's the notice period for planned leave?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="Do I need a medical certificate for sick leave?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What's the maximum hotel cost per night?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="Can I work remotely full time?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="How many remote days per week are allowed?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What are the travel class rules?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What's the expense pre-approval threshold?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="How long is parental leave for the birth parent?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="How long is parental leave for the other parent?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="Are client-facing days required in-office?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="Where can I find the NDA template?", domain="hr", intent_type="search", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What are the rules about sharing client information?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="Can I share client data between engagement teams?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What happens if I'm sick for more than 3 days?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="Do expenses need receipts?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What class should I fly for a 5-hour flight?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What's the sick leave policy?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="Who approves full-time remote work?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What's our confidentiality policy?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="How much can I spend on a client dinner?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What are the expense rules for hotels outside major cities?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="Is unlimited sick leave really unlimited?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
    BenchmarkQuery(query="What's the policy on working from client sites?", domain="hr", intent_type="policy", relevant_paths=["hr/policies.md"]),
]

# -----------------------------------------------------------------------
# ADDITIONAL FINANCE QUERIES (+24 → total 30)
# -----------------------------------------------------------------------

EXTRA_FINANCE = [
    BenchmarkQuery(query="What's our Q1 actual revenue?", domain="finance", relevant_paths=["finance/budgets.md"], authorized_role="sales-manager", unauthorized_role="sales-rep"),
    BenchmarkQuery(query="How much did we spend on salaries in Q1?", domain="finance", relevant_paths=["finance/budgets.md"], authorized_role="sales-manager", unauthorized_role="sales-rep"),
    BenchmarkQuery(query="What's the Q2 salary budget?", domain="finance", relevant_paths=["finance/budgets.md"], authorized_role="sales-manager"),
    BenchmarkQuery(query="How much runway do we have?", domain="finance", relevant_paths=["finance/budgets.md"], authorized_role="sales-manager"),
    BenchmarkQuery(query="What's our current cash position?", domain="finance", relevant_paths=["finance/budgets.md"], authorized_role="sales-manager"),
    BenchmarkQuery(query="What are our office costs?", domain="finance", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="How much do we spend on marketing?", domain="finance", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="What's the total Q2 expense budget?", domain="finance", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="Are we profitable in Q1?", domain="finance", intent_type="analysis", relevant_paths=["finance/budgets.md"], authorized_role="sales-manager"),
    BenchmarkQuery(query="What's the revenue gap between Q1 and Q2?", domain="finance", intent_type="analysis", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="When do we expect the Globex payment?", domain="finance", entities=["Globex"], relevant_paths=["finance/budgets.md"], cross_domain=True),
    BenchmarkQuery(query="What percentage of revenue comes from Henderson?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md"], authorized_role="sales-manager"),
    BenchmarkQuery(query="What's our infrastructure spend?", domain="finance", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="How much are we spending on tools and software?", domain="finance", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="What's the Q2 travel budget?", domain="finance", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="Compare Q1 expenses to Q2 budget", domain="finance", intent_type="analysis", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="What's total revenue if Globex closes?", domain="finance", entities=["Globex"], relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="What's the Q2 revenue forecast without Globex?", domain="finance", entities=["Globex"], relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="How many months of runway at current burn?", domain="finance", relevant_paths=["finance/budgets.md"], authorized_role="sales-manager"),
    BenchmarkQuery(query="When is the Henderson Phase 2 payment due?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md"], cross_domain=True),
    BenchmarkQuery(query="What's our biggest expense category?", domain="finance", intent_type="analysis", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="Are we on track for Q2 budget?", domain="finance", intent_type="status_update", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="What's the marketing budget for Q2?", domain="finance", relevant_paths=["finance/budgets.md"]),
    BenchmarkQuery(query="Show me the full expense breakdown", domain="finance", intent_type="search", relevant_paths=["finance/budgets.md"]),
]

# -----------------------------------------------------------------------
# ADDITIONAL CROSS-DOMAIN QUERIES (+45 → total 50)
# -----------------------------------------------------------------------

EXTRA_CROSS_DOMAIN = [
    BenchmarkQuery(query="What's the delivery status for the Henderson deal?", domain="sales", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md", "clients/henderson/profile.md"], cross_domain=True),
    BenchmarkQuery(query="How does Henderson's project timeline affect our revenue forecast?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="Can Leila take vacation during Henderson Phase 2?", domain="hr", entities=["Leila", "Henderson"], relevant_paths=["hr/policies.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="What's the financial exposure if Henderson delays?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md", "delivery/projects/henderson-phase2.md", "clients/henderson/profile.md"], cross_domain=True),
    BenchmarkQuery(query="Which active clients have projects running?", domain="sales", relevant_paths=["sales/pipeline.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="Is the Henderson delivery on track for the client review?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md", "clients/henderson/communications.md"], cross_domain=True),
    BenchmarkQuery(query="What budget concerns did Henderson raise and how does that affect our forecast?", domain="finance", entities=["Henderson"], relevant_paths=["clients/henderson/communications.md", "finance/budgets.md"], cross_domain=True),
    BenchmarkQuery(query="Can I expense the Henderson team dinner?", domain="hr", entities=["Henderson"], relevant_paths=["hr/policies.md"], cross_domain=True),
    BenchmarkQuery(query="What's Marc's total portfolio value?", domain="sales", entities=["Marc"], relevant_paths=["sales/pipeline.md", "clients/henderson/profile.md", "clients/meridian/profile.md"], cross_domain=True),
    BenchmarkQuery(query="How does the manufacturing sector slowdown affect our pipeline?", domain="sales", relevant_paths=["sales/pipeline.md", "clients/henderson/communications.md", "clients/henderson/profile.md"], cross_domain=True),
    BenchmarkQuery(query="What's the travel budget for the Henderson project team?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md", "hr/policies.md"], cross_domain=True),
    BenchmarkQuery(query="If Globex closes, what's our new revenue position?", domain="finance", entities=["Globex"], relevant_paths=["finance/budgets.md", "sales/pipeline.md", "clients/globex/profile.md"], cross_domain=True),
    BenchmarkQuery(query="Does Henderson's Phase 2 scope include AI quality control?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md", "clients/henderson/profile.md"], cross_domain=True),
    BenchmarkQuery(query="What's Sarah Henderson's latest feedback on the project?", domain="sales", entities=["Sarah", "Henderson"], relevant_paths=["clients/henderson/communications.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="How many SaaS tools does Meridian currently use?", domain="sales", entities=["Meridian"], relevant_paths=["clients/meridian/profile.md"], cross_domain=True),
    BenchmarkQuery(query="What's the total contract value across all active clients?", domain="sales", relevant_paths=["sales/pipeline.md", "clients/henderson/profile.md", "clients/meridian/profile.md"], cross_domain=True),
    BenchmarkQuery(query="Is the Henderson data integration risk affecting the timeline?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="How does Henderson's 8-week preference compare to the project plan?", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md", "clients/henderson/communications.md"], cross_domain=True),
    BenchmarkQuery(query="What did Henderson say about the ROI breakdown the CFO wants?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/communications.md"], cross_domain=True),
    BenchmarkQuery(query="Show me everything about Henderson — client profile, project status, and financials", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/profile.md", "clients/henderson/communications.md", "delivery/projects/henderson-phase2.md", "finance/budgets.md"], cross_domain=True),
    BenchmarkQuery(query="What's Globex worried about regarding compliance?", domain="sales", entities=["Globex"], relevant_paths=["clients/globex/profile.md"], cross_domain=True),
    BenchmarkQuery(query="Which clients are in the proposal stage and what's the total value?", domain="sales", relevant_paths=["sales/pipeline.md", "clients/globex/profile.md"], cross_domain=True),
    BenchmarkQuery(query="What remote work arrangements exist for the Henderson project team?", domain="hr", entities=["Henderson"], relevant_paths=["hr/policies.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="What's the expense policy for the Globex pitch trip?", domain="hr", entities=["Globex"], relevant_paths=["hr/policies.md"], cross_domain=True),
    BenchmarkQuery(query="How does Henderson Phase 2 revenue compare to expenses?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="What's our cash position after Henderson pays?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md"], cross_domain=True),
    BenchmarkQuery(query="Prepare a brief for the Henderson quarterly review", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/profile.md", "clients/henderson/communications.md", "delivery/projects/henderson-phase2.md", "sales/pipeline.md"], cross_domain=True),
    BenchmarkQuery(query="What confidentiality rules apply to sharing Henderson data with Meridian?", domain="hr", entities=["Henderson", "Meridian"], relevant_paths=["hr/policies.md"], cross_domain=True),
    BenchmarkQuery(query="Can we fly business class to the Globex meeting in Paris?",domain="hr", entities=["Globex"], relevant_paths=["hr/policies.md"], cross_domain=True),
    BenchmarkQuery(query="What's the pipeline outlook if manufacturing clients cut budgets?", domain="sales", relevant_paths=["sales/pipeline.md", "clients/henderson/communications.md"], cross_domain=True),
    BenchmarkQuery(query="How does Meridian's knowledge management project relate to our Context Kubernetes work?", domain="sales", entities=["Meridian"], relevant_paths=["clients/meridian/profile.md"], cross_domain=True),
    BenchmarkQuery(query="What SOC 2 concerns might Globex raise?", domain="sales", entities=["Globex"], relevant_paths=["clients/globex/profile.md"], cross_domain=True),
    BenchmarkQuery(query="Is there budget to hire a contractor for the Henderson project?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="What's the total value of Marc Dubois' client relationships?", domain="sales", entities=["Marc", "Dubois"], relevant_paths=["sales/pipeline.md", "clients/henderson/profile.md", "clients/meridian/profile.md"], cross_domain=True),
    BenchmarkQuery(query="Should we expand Henderson Phase 2 scope given the budget concerns?", domain="sales", entities=["Henderson"], intent_type="analysis", relevant_paths=["clients/henderson/communications.md", "delivery/projects/henderson-phase2.md", "finance/budgets.md"], cross_domain=True),
    BenchmarkQuery(query="What are all the touchpoints we've had with Henderson this quarter?", domain="sales", entities=["Henderson"], relevant_paths=["clients/henderson/communications.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="What's Sophie Laurent working on and what's the pipeline impact?", domain="sales", entities=["Sophie", "Laurent"], relevant_paths=["sales/pipeline.md", "clients/globex/profile.md"], cross_domain=True),
    BenchmarkQuery(query="What's our revenue if both Henderson Phase 3 and Globex close?", domain="finance", entities=["Henderson", "Globex"], relevant_paths=["finance/budgets.md", "sales/pipeline.md"], cross_domain=True),
    BenchmarkQuery(query="Compare Henderson and Meridian — size, value, and status", domain="sales", entities=["Henderson", "Meridian"], intent_type="analysis", relevant_paths=["clients/henderson/profile.md", "clients/meridian/profile.md", "sales/pipeline.md"], cross_domain=True),
    BenchmarkQuery(query="What's the leave policy and how does it affect project staffing?", domain="hr", relevant_paths=["hr/policies.md", "delivery/projects/henderson-phase2.md"], cross_domain=True),
    BenchmarkQuery(query="Are there any sector trends affecting multiple clients?", domain="sales", intent_type="analysis", relevant_paths=["sales/pipeline.md", "clients/henderson/communications.md", "clients/henderson/profile.md"], cross_domain=True),
    BenchmarkQuery(query="What's the biggest risk to Q2 revenue?", domain="finance", intent_type="analysis", relevant_paths=["finance/budgets.md", "sales/pipeline.md", "clients/henderson/communications.md"], cross_domain=True),
    BenchmarkQuery(query="Draft a status update covering Henderson delivery and financials", domain="delivery", entities=["Henderson"], relevant_paths=["delivery/projects/henderson-phase2.md", "finance/budgets.md", "clients/henderson/profile.md"], cross_domain=True),
    BenchmarkQuery(query="What do we know about Thomas Renard from Globex?", domain="sales", entities=["Thomas", "Renard", "Globex"], relevant_paths=["clients/globex/profile.md"]),
    BenchmarkQuery(query="What's the relationship between Henderson's budget concern and our forecast?", domain="finance", entities=["Henderson"], relevant_paths=["finance/budgets.md", "clients/henderson/communications.md"], cross_domain=True),
]


# -----------------------------------------------------------------------
# COMBINED: 200 queries
# -----------------------------------------------------------------------

ALL_QUERIES_200 = (
    SALES_QUERIES + EXTRA_SALES
    + DELIVERY_QUERIES + EXTRA_DELIVERY
    + HR_QUERIES + EXTRA_HR
    + FINANCE_QUERIES + EXTRA_FINANCE
    + CROSS_DOMAIN_QUERIES + EXTRA_CROSS_DOMAIN
)
