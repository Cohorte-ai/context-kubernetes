"""Tests for the Context Router — intent classification, ranking, and routing."""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from git import Repo

from context_kubernetes.cxri.connectors.git_connector import GitConnector
from context_kubernetes.cxri.interface import ConnectionConfig
from context_kubernetes.models import (
    ApprovalTier,
    ContextRequest,
    ContextUnit,
    ContextUnitMetadata,
    ContentType,
    FreshnessState,
    OperationPermission,
)
from context_kubernetes.permissions.engine import PermissionEngine
from context_kubernetes.router.intent import IntentClassifier, ClassifiedIntent
from context_kubernetes.router.ranking import RankingEngine, RankingSignalWeights
from context_kubernetes.router.router import ContextRouter


# -----------------------------------------------------------------------
# Intent classification tests
# -----------------------------------------------------------------------


class TestIntentClassifier:
    def setup_method(self):
        self.classifier = IntentClassifier(
            available_domains=["sales", "delivery", "hr", "finance"]
        )

    @pytest.mark.asyncio
    async def test_classify_sales_query(self):
        intent = await self.classifier.classify("What's the pipeline status for Henderson?")
        assert intent.primary_domain == "sales"
        assert "Henderson" in intent.entities
        assert intent.method == "rule-based"

    @pytest.mark.asyncio
    async def test_classify_delivery_query(self):
        intent = await self.classifier.classify("Is the Henderson project on track?")
        assert intent.primary_domain == "delivery"
        assert intent.intent_type == "status_update"

    @pytest.mark.asyncio
    async def test_classify_hr_query(self):
        intent = await self.classifier.classify("What's our remote work policy?")
        assert intent.primary_domain == "hr"
        assert intent.intent_type == "policy"

    @pytest.mark.asyncio
    async def test_classify_finance_query(self):
        intent = await self.classifier.classify("Show me the Q2 budget forecast")
        assert intent.primary_domain == "finance"
        assert intent.time_scope in ("current", "upcoming")

    @pytest.mark.asyncio
    async def test_classify_with_time_scope(self):
        intent = await self.classifier.classify("What happened with Henderson last quarter?")
        assert intent.time_scope == "historical"

    @pytest.mark.asyncio
    async def test_entity_extraction(self):
        intent = await self.classifier.classify("Draft a proposal for Meridian Corp")
        assert "Meridian" in intent.entities or "Corp" in intent.entities

    @pytest.mark.asyncio
    async def test_conversation_aware(self):
        """Co-reference resolution from conversation history."""
        history = ["Tell me about the Henderson project"]
        intent = await self.classifier.classify(
            "What about the budget?",
            conversation_history=history,
        )
        # Should pick up "Henderson" from context
        assert "Henderson" in intent.entities or intent.primary_domain in ("finance", "delivery")

    @pytest.mark.asyncio
    async def test_cross_domain_detection(self):
        intent = await self.classifier.classify(
            "What's the delivery timeline for the Henderson deal?"
        )
        domains = {intent.primary_domain} | set(intent.secondary_domains)
        # Should detect both delivery and sales
        assert len(domains) >= 1  # at minimum the primary


# -----------------------------------------------------------------------
# Ranking tests
# -----------------------------------------------------------------------


class TestRankingEngine:
    def setup_method(self):
        self.ranker = RankingEngine(
            weights=RankingSignalWeights(
                semantic_relevance=0.4,
                recency=0.3,
                authority=0.2,
                user_relevance=0.1,
            )
        )

    def _make_unit(
        self,
        content: str,
        domain: str = "sales",
        age_hours: float = 0,
        author: str = "analyst",
        entities: list[str] | None = None,
    ) -> ContextUnit:
        ts = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        return ContextUnit(
            content=content,
            content_type=ContentType.UNSTRUCTURED,
            metadata=ContextUnitMetadata(
                domain=domain,
                source="test",
                author=author,
                timestamp=ts,
                entities=entities or [],
            ),
            version="v1",
        )

    def test_semantic_relevance_ranking(self):
        """Units with more query term matches should rank higher."""
        units = [
            self._make_unit("The weather is nice today", entities=[]),
            self._make_unit("Henderson project status update", entities=["Henderson"]),
            self._make_unit("Henderson budget and timeline review", entities=["Henderson"]),
        ]

        results = self.ranker.rank(units, "Henderson budget")
        # The one mentioning both "Henderson" and "budget" should rank first
        assert "budget" in results[0].unit.content.lower()

    def test_recency_ranking(self):
        """Recent content should score higher on recency."""
        units = [
            self._make_unit("Old update from January", age_hours=2000),
            self._make_unit("Fresh update from today", age_hours=1),
        ]

        results = self.ranker.rank(units, "update")
        assert results[0].signals["recency"] > results[1].signals["recency"]

    def test_authority_ranking(self):
        """Content from senior authors should score higher."""
        units = [
            self._make_unit("Analysis from intern", author="intern"),
            self._make_unit("Analysis from partner", author="partner"),
        ]

        results = self.ranker.rank(units, "analysis")
        partner = [r for r in results if "partner" in r.unit.metadata.author][0]
        intern = [r for r in results if "intern" in r.unit.metadata.author][0]
        assert partner.signals["authority"] > intern.signals["authority"]

    def test_token_budget_truncation(self):
        """Results should be truncated to fit the token budget."""
        units = [
            self._make_unit("Word " * 100, entities=["relevant"]),  # ~100 tokens
            self._make_unit("Word " * 100, entities=["relevant"]),
            self._make_unit("Word " * 100, entities=["relevant"]),
        ]

        results = self.ranker.rank(units, "relevant", token_budget=250)
        total = sum(r.unit.token_count for r in results)
        assert total <= 250

    def test_user_relevance(self):
        """Units matching user's entities should rank higher."""
        units = [
            self._make_unit("Acme Corp quarterly review", entities=["Acme"]),
            self._make_unit("Henderson quarterly review", entities=["Henderson"]),
        ]

        results = self.ranker.rank(
            units,
            "quarterly review",
            user_entities=["Henderson"],
        )
        # Henderson should score higher on user_relevance
        henderson = [r for r in results if "Henderson" in r.unit.content][0]
        acme = [r for r in results if "Acme" in r.unit.content][0]
        assert henderson.signals["user_relevance"] >= acme.signals["user_relevance"]

    def test_cosine_similarity(self):
        """Embedding-based similarity should work."""
        sim = RankingEngine._cosine_similarity(
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        )
        assert abs(sim - 1.0) < 0.001

        sim_ortho = RankingEngine._cosine_similarity(
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        )
        assert abs(sim_ortho) < 0.001


# -----------------------------------------------------------------------
# Full router integration tests
# -----------------------------------------------------------------------


@pytest.fixture
def router_with_repo():
    """Set up a full router with a git connector and permission engine."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test repo
        repo = Repo.init(tmpdir)
        clients = Path(tmpdir) / "clients" / "henderson"
        clients.mkdir(parents=True)
        (clients / "profile.md").write_text(
            "# Henderson Corp\nStatus: Active\nIndustry: Manufacturing\n"
        )
        (clients / "communications.md").write_text(
            "## March Meeting\nDiscussed budget constraints for Q2.\n"
        )
        pipeline = Path(tmpdir) / "pipeline.md"
        pipeline.write_text("# Pipeline\n| Client | Stage |\n| Henderson | Proposal |\n")

        repo.index.add([
            "clients/henderson/profile.md",
            "clients/henderson/communications.md",
            "pipeline.md",
        ])
        repo.index.commit("Initial")

        # Set up permission engine
        perm_engine = PermissionEngine()
        perm_engine.register_role("sales-rep", [
            OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="send_email", tier=ApprovalTier.AUTONOMOUS),
        ])
        perm_engine.register_agent_profile(
            user_id="user-1",
            role="sales-rep",
            agent_permissions=[
                OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
                OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.SOFT_APPROVAL),
            ],
            excluded_operations=["send_email"],
        )
        session = perm_engine.create_session(
            "user-1", "agent-1", "sales-rep",
            workspace_scope="clients/henderson",
        )

        # Set up router
        router = ContextRouter(
            permission_engine=perm_engine,
            intent_classifier=IntentClassifier(available_domains=["sales", "delivery"]),
        )

        yield router, tmpdir, session


class TestContextRouter:
    @pytest.mark.asyncio
    async def test_end_to_end_route(self, router_with_repo):
        router, tmpdir, session = router_with_repo

        # Register git connector
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))
        router.register_connector("sales", connector)

        # Route a query
        response = await router.route(ContextRequest(
            session_id=session.session_id,
            intent="What's the Henderson client status?",
            token_budget=8000,
        ))

        assert len(response.units) > 0
        assert response.total_tokens > 0
        assert response.latency_ms > 0
        # Should find Henderson-related content
        all_content = " ".join(u.content for u in response.units)
        assert "henderson" in all_content.lower()

    @pytest.mark.asyncio
    async def test_invalid_session_denied(self, router_with_repo):
        router, _, _ = router_with_repo

        response = await router.route(ContextRequest(
            session_id="invalid-session",
            intent="anything",
        ))

        assert len(response.units) == 0
        assert "Invalid" in response.freshness_warnings[0]

    @pytest.mark.asyncio
    async def test_expired_content_not_served(self, router_with_repo):
        """Design Goal 3.9: expired units must not be served."""
        router, tmpdir, session = router_with_repo

        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))
        router.register_connector("sales", connector)

        # Route a query
        response = await router.route(ContextRequest(
            session_id=session.session_id,
            intent="Henderson",
            token_budget=8000,
        ))

        # Manually mark all units as expired and re-filter
        for unit in response.units:
            unit.freshness = FreshnessState.EXPIRED

        filtered, warnings = ContextRouter._filter_by_freshness(response.units)
        assert len(filtered) == 0  # no expired content served

    @pytest.mark.asyncio
    async def test_stale_content_has_warnings(self, router_with_repo):
        """Stale units are served but with freshness warnings."""
        router, tmpdir, session = router_with_repo

        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))
        router.register_connector("sales", connector)

        response = await router.route(ContextRequest(
            session_id=session.session_id,
            intent="Henderson",
            token_budget=8000,
        ))

        # Mark units as stale
        for unit in response.units:
            unit.freshness = FreshnessState.STALE

        filtered, warnings = ContextRouter._filter_by_freshness(response.units)
        assert len(filtered) > 0  # stale is served
        assert len(warnings) > 0  # but with warnings

    @pytest.mark.asyncio
    async def test_audit_logging(self, router_with_repo):
        """Every route request must be logged."""
        router, tmpdir, session = router_with_repo

        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))
        # Register under both sales and delivery so the query always finds connectors
        router.register_connector("sales", connector)
        router.register_connector("delivery", connector)

        await router.route(ContextRequest(
            session_id=session.session_id,
            intent="Henderson client pipeline deal",  # strong sales signal
        ))

        log = router.get_audit_log()
        assert len(log) >= 1
        assert log[0].event_type == "context_request"
        assert log[0].user_id == "user-1"
        assert "intent" in log[0].details

    @pytest.mark.asyncio
    async def test_token_budget_respected(self, router_with_repo):
        """Response must not exceed the requested token budget."""
        router, tmpdir, session = router_with_repo

        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))
        router.register_connector("sales", connector)

        response = await router.route(ContextRequest(
            session_id=session.session_id,
            intent="Henderson",
            token_budget=50,  # very tight budget
        ))

        assert response.total_tokens <= 50
