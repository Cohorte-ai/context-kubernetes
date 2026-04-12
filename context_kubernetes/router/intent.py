"""Intent Classification — parses agent queries into structured intents.

Two modes (from the paper's Design Principle 5):
  1. LLM-assisted: semantic understanding via a small, fast model
  2. Rule-based fallback: keyword + pattern matching when LLM
     confidence is below threshold or LLM is unavailable

The router always has a deterministic fallback path — this addresses
the LLM-in-the-loop tension identified in Section 8.2 of the paper.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClassifiedIntent:
    """Structured output of intent classification."""

    primary_domain: str  # e.g., "delivery", "sales", "hr"
    entities: list[str] = field(default_factory=list)  # e.g., ["Henderson", "project"]
    intent_type: str = "general_query"  # e.g., "status_update", "search", "action"
    time_scope: str = "current"  # current | historical | upcoming
    secondary_domains: list[str] = field(default_factory=list)
    confidence: float = 1.0
    method: str = "rule-based"  # "llm-assisted" | "rule-based"
    raw_query: str = ""


# -----------------------------------------------------------------------
# Domain keyword maps for rule-based classification
# -----------------------------------------------------------------------

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "sales": [
        "client", "prospect", "pipeline", "deal", "proposal", "pricing",
        "revenue", "lead", "opportunity", "quote", "contract", "account",
        "customer", "sales", "crm", "follow-up", "meeting",
    ],
    "delivery": [
        "project", "delivery", "milestone", "deadline", "timeline",
        "sprint", "task", "blocker", "status", "progress", "resource",
        "allocation", "workstream", "deliverable", "phase",
    ],
    "hr": [
        "employee", "policy", "onboarding", "leave", "vacation", "salary",
        "benefits", "hiring", "performance", "review", "hr", "handbook",
        "org chart", "team", "people", "headcount",
    ],
    "legal": [
        "contract", "compliance", "regulation", "legal", "nda",
        "agreement", "liability", "terms", "intellectual property",
        "dispute", "lawsuit", "counsel",
    ],
    "finance": [
        "budget", "invoice", "expense", "revenue", "cost", "financial",
        "profit", "loss", "forecast", "accounting", "billing", "payment",
        "tax", "audit",
    ],
    "operations": [
        "process", "workflow", "operations", "logistics", "inventory",
        "supply chain", "vendor", "procurement", "infrastructure",
        "capacity", "scheduling",
    ],
    "knowledge": [
        "template", "playbook", "framework", "methodology", "best practice",
        "learning", "training", "documentation", "guide", "reference",
    ],
}

INTENT_TYPE_PATTERNS: dict[str, list[str]] = {
    "status_update": ["status", "progress", "update", "how is", "where are we", "on track"],
    "search": ["find", "search", "look for", "where is", "show me", "get me", "what is"],
    "action": ["send", "create", "update", "delete", "draft", "schedule", "assign"],
    "analysis": ["pattern", "trend", "compare", "analyze", "insight", "summary"],
    "policy": ["policy", "rule", "guideline", "allowed", "can i", "should i"],
}

TIME_SCOPE_PATTERNS: dict[str, list[str]] = {
    "current": ["current", "now", "today", "latest", "active"],
    "historical": ["last", "previous", "history", "past", "ago", "was"],
    "upcoming": ["next", "upcoming", "future", "planned", "scheduled", "will"],
}


class IntentClassifier:
    """
    Classifies natural language queries into structured intents.

    Supports two modes:
    - rule-based (always available, deterministic)
    - llm-assisted (higher quality, requires API key)

    The router falls back to rule-based when:
    - No LLM is configured
    - LLM call fails
    - LLM confidence is below threshold
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        llm_model: str = "gpt-4o-mini",
        confidence_threshold: float = 0.7,
        available_domains: list[str] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._llm_model = llm_model
        self._confidence_threshold = confidence_threshold
        self._available_domains = available_domains or list(DOMAIN_KEYWORDS.keys())

    async def classify(self, query: str, conversation_history: list[str] | None = None) -> ClassifiedIntent:
        """
        Classify a query into a structured intent.

        Tries LLM-assisted classification first, falls back to rule-based
        if LLM is unavailable or returns low confidence.
        """
        # Try LLM-assisted first
        if self._llm_client is not None:
            try:
                intent = await self._classify_llm(query, conversation_history)
                if intent.confidence >= self._confidence_threshold:
                    return intent
                # Low confidence — fall through to rule-based
            except Exception:
                pass  # LLM failed — fall through to rule-based

        # Rule-based fallback (always available)
        return self._classify_rules(query, conversation_history)

    # -------------------------------------------------------------------
    # Rule-based classification
    # -------------------------------------------------------------------

    def _classify_rules(
        self, query: str, conversation_history: list[str] | None = None
    ) -> ClassifiedIntent:
        """Deterministic classification using keyword matching."""
        query_lower = query.lower()

        # Resolve co-references from conversation history
        if conversation_history:
            query_lower = self._resolve_coreferences(query_lower, conversation_history)

        # Score each domain by keyword hits
        domain_scores: dict[str, int] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if domain not in self._available_domains:
                continue
            score = sum(1 for kw in keywords if kw in query_lower)
            if score > 0:
                domain_scores[domain] = score

        # Primary domain = highest scoring
        if domain_scores:
            sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
            primary = sorted_domains[0][0]
            secondary = [d for d, _ in sorted_domains[1:] if _ > 0]
        else:
            primary = self._available_domains[0] if self._available_domains else "general"
            secondary = []

        # Extract entities (capitalized words that aren't common English)
        entities = self._extract_entities(query)

        # Classify intent type
        intent_type = "general_query"
        for itype, patterns in INTENT_TYPE_PATTERNS.items():
            if any(p in query_lower for p in patterns):
                intent_type = itype
                break

        # Time scope
        time_scope = "current"
        for scope, patterns in TIME_SCOPE_PATTERNS.items():
            if any(p in query_lower for p in patterns):
                time_scope = scope
                break

        # Confidence: based on how many domain keywords matched
        max_score = max(domain_scores.values()) if domain_scores else 0
        confidence = min(0.5 + max_score * 0.1, 0.95)

        return ClassifiedIntent(
            primary_domain=primary,
            entities=entities,
            intent_type=intent_type,
            time_scope=time_scope,
            secondary_domains=secondary[:2],
            confidence=confidence,
            method="rule-based",
            raw_query=query,
        )

    # -------------------------------------------------------------------
    # LLM-assisted classification
    # -------------------------------------------------------------------

    async def _classify_llm(
        self, query: str, conversation_history: list[str] | None = None
    ) -> ClassifiedIntent:
        """Semantic classification using an LLM."""
        context_str = ""
        if conversation_history:
            context_str = "\n".join(f"- {h}" for h in conversation_history[-5:])
            context_str = f"\nRecent conversation:\n{context_str}\n"

        domains_str = ", ".join(self._available_domains)

        prompt = f"""Classify this query for a context orchestration system.

Available domains: {domains_str}
{context_str}
Query: "{query}"

Return JSON only:
{{"primary_domain": "...", "entities": ["..."], "intent_type": "status_update|search|action|analysis|policy|general_query", "time_scope": "current|historical|upcoming", "secondary_domains": ["..."], "confidence": 0.0-1.0}}"""

        response = await self._llm_client.chat.completions.create(
            model=self._llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        data = json.loads(content)

        return ClassifiedIntent(
            primary_domain=data.get("primary_domain", self._available_domains[0]),
            entities=data.get("entities", []),
            intent_type=data.get("intent_type", "general_query"),
            time_scope=data.get("time_scope", "current"),
            secondary_domains=data.get("secondary_domains", []),
            confidence=data.get("confidence", 0.8),
            method="llm-assisted",
            raw_query=query,
        )

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_entities(query: str) -> list[str]:
        """Extract likely entity names from the query."""
        # Capitalized words that aren't at sentence start and aren't common
        common_words = {
            "the", "a", "an", "is", "are", "was", "were", "what", "how",
            "when", "where", "who", "which", "do", "does", "did", "can",
            "could", "would", "should", "any", "all", "our", "my", "your",
            "this", "that", "these", "those", "i", "we", "they", "it",
            "has", "have", "had", "get", "got", "tell", "show", "give",
        }
        words = query.split()
        entities = []
        for i, word in enumerate(words):
            clean = re.sub(r'[^\w]', '', word)
            if clean and clean[0].isupper() and clean.lower() not in common_words:
                # Skip if it's the first word (sentence capitalization)
                if i > 0 or len(words) == 1:
                    entities.append(clean)
        return entities

    @staticmethod
    def _resolve_coreferences(query: str, history: list[str]) -> str:
        """
        Basic co-reference resolution using conversation history.

        If the query contains pronouns like "it", "that", "the project",
        try to resolve them from the most recent history entry.
        """
        pronouns = {"it", "that", "this", "the project", "the client", "their", "them"}
        if not any(p in query for p in pronouns):
            return query

        # Extract entities from the most recent history entry
        if history:
            last = history[-1].lower()
            # Find capitalized words in history as context
            context_entities = IntentClassifier._extract_entities(history[-1])
            if context_entities:
                # Append context entities to the query for better matching
                query = f"{query} {' '.join(context_entities)}"

        return query
