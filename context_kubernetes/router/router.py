"""Context Router — the central scheduling intelligence.

Given intent q, scope ω, and profile α:
  (a) classifies intent via IntentClassifier
  (b) resolves relevant sources from the registry
  (c) fetches via CxRI connectors
  (d) filters by permissions (Permission Engine)
  (e) ranks by multi-signal priority (RankingEngine)
  (f) truncates to token budget B

This is the core component that makes "ask by intent, not by location" work.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from context_kubernetes.cxri.interface import CxRIConnector
from context_kubernetes.models import (
    AuditEvent,
    ContextRequest,
    ContextResponse,
    ContextUnit,
    FreshnessState,
)
from context_kubernetes.permissions.engine import PermissionEngine
from context_kubernetes.router.intent import ClassifiedIntent, IntentClassifier
from context_kubernetes.router.ranking import RankingEngine


class ContextRouter:
    """
    The Context Router — analogous to kube-scheduler + Ingress.

    Agents send a ContextRequest with natural language intent.
    The router resolves it to filtered, ranked, budget-constrained
    context units from the appropriate domain connectors.
    """

    def __init__(
        self,
        permission_engine: PermissionEngine,
        intent_classifier: IntentClassifier | None = None,
        ranking_engine: RankingEngine | None = None,
    ) -> None:
        self._permission_engine = permission_engine
        self._classifier = intent_classifier or IntentClassifier()
        self._ranker = ranking_engine or RankingEngine()

        # Domain → list of connectors
        self._domain_connectors: dict[str, list[CxRIConnector]] = {}

        # Cross-domain brokering rules: source_domain → set of allowed target domains
        self._cross_domain_allowed: dict[str, set[str]] = {}

        # Intent cache: query hash → ClassifiedIntent
        self._intent_cache: dict[str, ClassifiedIntent] = {}

        # Audit events
        self._audit_log: list[AuditEvent] = []

        # Conversation history per session (for co-reference resolution)
        self._session_history: dict[str, list[str]] = {}

    # -------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------

    def register_connector(self, domain: str, connector: CxRIConnector) -> None:
        """Register a CxRI connector for a domain."""
        if domain not in self._domain_connectors:
            self._domain_connectors[domain] = []
        self._domain_connectors[domain].append(connector)

    def set_cross_domain_rules(self, domain: str, allowed_targets: set[str]) -> None:
        """Configure which domains can be queried from this domain."""
        self._cross_domain_allowed[domain] = allowed_targets

    # -------------------------------------------------------------------
    # Core routing
    # -------------------------------------------------------------------

    async def route(self, request: ContextRequest) -> ContextResponse:
        """
        Route a context request to the appropriate sources.

        This is the main entry point — the Context Endpoint (Def. 3.4).
        """
        start_time = time.time()
        request_id = f"req-{hashlib.sha256(f'{request.session_id}:{time.time()}'.encode()).hexdigest()[:12]}"

        # Validate session
        session = self._permission_engine.get_session(request.session_id)
        if not session:
            return ContextResponse(
                request_id=request_id,
                freshness_warnings=["Invalid or terminated session"],
            )

        # Get conversation history for co-reference resolution
        history = self._session_history.get(request.session_id, [])

        # Step 1: Classify intent
        intent = await self._classify_with_cache(request.intent, history)

        # Update conversation history
        if request.session_id not in self._session_history:
            self._session_history[request.session_id] = []
        self._session_history[request.session_id].append(request.intent)
        # Keep last 10 turns
        self._session_history[request.session_id] = self._session_history[request.session_id][-10:]

        # Step 2: Resolve sources (which connectors to query)
        connectors = self._resolve_sources(intent, session.role)

        if not connectors:
            return ContextResponse(
                request_id=request_id,
                freshness_warnings=[f"No connectors available for domain '{intent.primary_domain}'"],
                latency_ms=(time.time() - start_time) * 1000,
            )

        # Step 3: Fetch from connectors
        raw_units = await self._fetch_from_connectors(connectors, intent)

        # Step 4: Permission filter
        filtered_units = self._filter_by_permissions(
            raw_units, request.session_id, session.role
        )

        # Step 5: Freshness filter
        filtered_units, freshness_warnings = self._filter_by_freshness(filtered_units)

        # Step 6: Rank and truncate to token budget
        user_entities = self._extract_user_entities(session)
        ranked = self._ranker.rank(
            filtered_units,
            query=request.intent,
            user_entities=user_entities,
            token_budget=request.token_budget,
        )

        # Build response
        result_units = [r.unit for r in ranked]
        total_tokens = sum(u.token_count for u in result_units)
        latency_ms = (time.time() - start_time) * 1000

        # Audit
        self._audit_log.append(AuditEvent(
            session_id=request.session_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            event_type="context_request",
            operation="route",
            resource=intent.primary_domain,
            outcome=f"returned {len(result_units)} units, {total_tokens} tokens",
            latency_ms=latency_ms,
            details={
                "intent": {
                    "domain": intent.primary_domain,
                    "entities": intent.entities,
                    "type": intent.intent_type,
                    "method": intent.method,
                    "confidence": intent.confidence,
                },
                "candidates": len(raw_units),
                "after_permission_filter": len(filtered_units),
                "returned": len(result_units),
            },
        ))

        return ContextResponse(
            request_id=request_id,
            units=result_units,
            total_tokens=total_tokens,
            freshness_warnings=freshness_warnings,
            latency_ms=latency_ms,
        )

    # -------------------------------------------------------------------
    # Step 1: Intent classification (with caching)
    # -------------------------------------------------------------------

    async def _classify_with_cache(
        self, query: str, history: list[str]
    ) -> ClassifiedIntent:
        """Classify intent, using cache for repeated patterns."""
        cache_key = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]

        if cache_key in self._intent_cache:
            cached = self._intent_cache[cache_key]
            return cached

        intent = await self._classifier.classify(query, history)
        self._intent_cache[cache_key] = intent

        # Keep cache bounded
        if len(self._intent_cache) > 1000:
            # Evict oldest half
            keys = list(self._intent_cache.keys())
            for k in keys[:500]:
                del self._intent_cache[k]

        return intent

    # -------------------------------------------------------------------
    # Step 2: Source resolution
    # -------------------------------------------------------------------

    def _resolve_sources(
        self, intent: ClassifiedIntent, role: str
    ) -> list[CxRIConnector]:
        """Determine which connectors to query for this intent."""
        connectors: list[CxRIConnector] = []

        # Primary domain
        primary = self._domain_connectors.get(intent.primary_domain, [])
        connectors.extend(primary)

        # Secondary domains (cross-domain brokering)
        for domain in intent.secondary_domains:
            allowed = self._cross_domain_allowed.get(intent.primary_domain, set())
            if domain in allowed:
                secondary = self._domain_connectors.get(domain, [])
                connectors.extend(secondary)

        return connectors

    # -------------------------------------------------------------------
    # Step 3: Fetch from connectors
    # -------------------------------------------------------------------

    async def _fetch_from_connectors(
        self,
        connectors: list[CxRIConnector],
        intent: ClassifiedIntent,
    ) -> list[ContextUnit]:
        """Query all resolved connectors and merge results."""
        all_units: list[ContextUnit] = []

        for connector in connectors:
            try:
                units = await connector.query(
                    intent.raw_query,
                    max_results=50,
                    entities=intent.entities,
                )
                all_units.extend(units)
            except Exception:
                # Connector failure — log but continue with others
                pass

        return all_units

    # -------------------------------------------------------------------
    # Step 4: Permission filter
    # -------------------------------------------------------------------

    def _filter_by_permissions(
        self,
        units: list[ContextUnit],
        session_id: str,
        role: str,
    ) -> list[ContextUnit]:
        """
        Filter units by the session's permission profile.

        Design Goal 3.9 (Safety): no context unit is delivered to an
        agent whose permission profile does not include the unit's
        access scope.
        """
        filtered: list[ContextUnit] = []
        for unit in units:
            if self._permission_engine.check_context_access(
                session_id, unit.authorized_roles
            ):
                filtered.append(unit)
        return filtered

    # -------------------------------------------------------------------
    # Step 5: Freshness filter
    # -------------------------------------------------------------------

    @staticmethod
    def _filter_by_freshness(
        units: list[ContextUnit],
    ) -> tuple[list[ContextUnit], list[str]]:
        """
        Filter out expired units, flag stale ones.

        Design Goal 3.9 (Freshness Safety): no expired unit is served.
        Stale units are served with warnings.
        """
        filtered: list[ContextUnit] = []
        warnings: list[str] = []

        for unit in units:
            if unit.freshness == FreshnessState.EXPIRED:
                continue  # never serve expired
            if unit.freshness == FreshnessState.CONFLICTED:
                continue  # don't serve conflicted
            if unit.freshness == FreshnessState.STALE:
                warnings.append(
                    f"Stale content: {unit.metadata.source} "
                    f"(last updated: {unit.metadata.timestamp.isoformat()})"
                )
            filtered.append(unit)

        return filtered, warnings

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_user_entities(session: Any) -> list[str]:
        """Extract entities relevant to the current user for user_relevance scoring."""
        entities = []
        if session.workspace_scope:
            # Extract entity hints from workspace scope
            parts = session.workspace_scope.replace("/", " ").replace("-", " ").split()
            entities.extend(p for p in parts if len(p) > 2)
        return entities

    def get_audit_log(self) -> list[AuditEvent]:
        """Return routing audit events."""
        return list(self._audit_log)
