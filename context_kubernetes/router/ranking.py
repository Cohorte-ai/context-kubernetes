"""Multi-Signal Ranking Engine.

Ranks context units by configurable weighted signals:
  - semantic_relevance: cosine similarity between query and unit embeddings
  - recency: how recently the unit was modified
  - authority: author's seniority / role weight
  - user_relevance: match to requester's projects/clients

Weights are declared in the manifest routing spec.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from context_kubernetes.models import ContextUnit


@dataclass
class RankingSignalWeights:
    """Configurable weights from the manifest routing.priority spec."""

    semantic_relevance: float = 0.40
    recency: float = 0.30
    authority: float = 0.20
    user_relevance: float = 0.10

    def __post_init__(self) -> None:
        total = (
            self.semantic_relevance + self.recency
            + self.authority + self.user_relevance
        )
        if abs(total - 1.0) > 0.01:
            # Normalize
            self.semantic_relevance /= total
            self.recency /= total
            self.authority /= total
            self.user_relevance /= total


@dataclass
class RankedResult:
    """A context unit with its computed ranking score and signal breakdown."""

    unit: ContextUnit
    score: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)


class RankingEngine:
    """
    Multi-signal ranking engine for context units.

    Given a set of candidate context units and a query, computes a
    composite relevance score using configurable weighted signals.
    """

    def __init__(
        self,
        weights: RankingSignalWeights | None = None,
        authority_roles: dict[str, float] | None = None,
    ) -> None:
        self._weights = weights or RankingSignalWeights()
        # Role → authority score (higher = more authoritative)
        self._authority_roles = authority_roles or {
            "c-level": 1.0,
            "partner": 0.9,
            "director": 0.8,
            "manager": 0.7,
            "senior": 0.6,
            "lead": 0.5,
            "analyst": 0.3,
            "junior": 0.2,
            "intern": 0.1,
        }

    def rank(
        self,
        units: list[ContextUnit],
        query: str,
        query_embedding: list[float] | None = None,
        user_entities: list[str] | None = None,
        token_budget: int = 8000,
    ) -> list[RankedResult]:
        """
        Rank context units by composite multi-signal score.

        Returns ranked results truncated to fit the token budget.
        """
        if not units:
            return []

        results: list[RankedResult] = []

        for unit in units:
            signals = self._compute_signals(
                unit, query, query_embedding, user_entities
            )
            score = (
                self._weights.semantic_relevance * signals["semantic_relevance"]
                + self._weights.recency * signals["recency"]
                + self._weights.authority * signals["authority"]
                + self._weights.user_relevance * signals["user_relevance"]
            )
            results.append(RankedResult(unit=unit, score=score, signals=signals))

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)

        # Truncate to token budget
        return self._truncate_to_budget(results, token_budget)

    def _compute_signals(
        self,
        unit: ContextUnit,
        query: str,
        query_embedding: list[float] | None,
        user_entities: list[str] | None,
    ) -> dict[str, float]:
        """Compute all ranking signals for a single context unit."""
        return {
            "semantic_relevance": self._score_semantic(unit, query, query_embedding),
            "recency": self._score_recency(unit),
            "authority": self._score_authority(unit),
            "user_relevance": self._score_user_relevance(unit, user_entities),
        }

    def _score_semantic(
        self,
        unit: ContextUnit,
        query: str,
        query_embedding: list[float] | None,
    ) -> float:
        """
        Semantic relevance score.

        If embeddings are available, use cosine similarity.
        Otherwise, fall back to term overlap (TF-IDF-like).
        """
        # Embedding-based similarity
        if query_embedding and unit.embedding:
            return self._cosine_similarity(query_embedding, unit.embedding)

        # Fallback: term overlap
        query_terms = set(query.lower().split())
        content_terms = set(unit.content.lower().split())

        if not query_terms:
            return 0.0

        overlap = query_terms & content_terms
        # Also check entities
        entity_matches = sum(
            1 for e in unit.metadata.entities
            if e.lower() in query.lower()
        )

        # Weighted term overlap + entity bonus
        term_score = len(overlap) / len(query_terms) if query_terms else 0.0
        entity_score = min(entity_matches * 0.2, 0.4)

        return min(term_score + entity_score, 1.0)

    def _score_recency(self, unit: ContextUnit) -> float:
        """
        Recency score: exponential decay based on age.

        Score = e^(-age_hours / half_life_hours)
        Half-life of 168 hours (1 week) means content from a week ago
        scores ~0.37, content from 2 weeks ago scores ~0.14.
        """
        now = datetime.now(UTC)
        age = now - unit.metadata.timestamp
        age_hours = age.total_seconds() / 3600

        half_life_hours = 168.0  # 1 week
        return math.exp(-age_hours / half_life_hours)

    def _score_authority(self, unit: ContextUnit) -> float:
        """
        Authority score based on author's role/seniority.

        Higher authority means the content is more trustworthy.
        """
        author = (unit.metadata.author or "").lower()

        # Check if any authority role appears in the author string
        for role, score in self._authority_roles.items():
            if role in author:
                return score

        return 0.4  # default: moderate authority

    def _score_user_relevance(
        self, unit: ContextUnit, user_entities: list[str] | None
    ) -> float:
        """
        User relevance: how relevant is this unit to the requester's
        projects, clients, and current work.
        """
        if not user_entities:
            return 0.5  # neutral if no user context

        # Check entity overlap between unit and user's entities
        unit_entities = {e.lower() for e in unit.metadata.entities}
        user_set = {e.lower() for e in user_entities}

        if not user_set:
            return 0.5

        overlap = unit_entities & user_set
        content_lower = unit.content.lower()
        content_matches = sum(1 for e in user_set if e in content_lower)

        entity_score = len(overlap) / len(user_set) if user_set else 0.0
        content_score = min(content_matches / len(user_set), 1.0)

        return min((entity_score + content_score) / 2 + 0.3, 1.0)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return max(0.0, dot / (norm_a * norm_b))

    @staticmethod
    def _truncate_to_budget(
        results: list[RankedResult], token_budget: int
    ) -> list[RankedResult]:
        """Keep top results until token budget is exhausted."""
        truncated: list[RankedResult] = []
        total_tokens = 0

        for result in results:
            tokens = result.unit.token_count
            if total_tokens + tokens > token_budget:
                break
            truncated.append(result)
            total_tokens += tokens

        return truncated
