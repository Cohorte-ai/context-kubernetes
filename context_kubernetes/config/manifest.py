"""Context Architecture Manifest — the declarative spec from Section 4.2.

A YAML-based manifest that allows organizations to define their
knowledge architecture as code: sources, permissions, freshness
policies, routing rules, trust policies, and operator configurations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from context_kubernetes.models import ApprovalTier


# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------


class IngestionConfig(BaseModel):
    chunking: str = "semantic"  # semantic | per-thread | per-document
    chunk_size: int = 500
    embedding: str = "text-embedding-3-small"
    ttl_days: int | None = None
    extract_entities: bool = True


class SourceSpec(BaseModel):
    name: str
    type: str  # git-repo | connector | file-system
    config: dict[str, Any] = Field(default_factory=dict)
    refresh: str = "1h"  # realtime | 15m | 1h | daily
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


class RoleAccess(BaseModel):
    role: str
    read: list[str] = Field(default_factory=lambda: ["*"])
    write: list[str] = Field(default_factory=list)


class AgentPermissionSpec(BaseModel):
    read: str = "autonomous"  # always autonomous for reads within user scope
    write_default: ApprovalTier = ApprovalTier.SOFT_APPROVAL
    write_overrides: dict[str, ApprovalTier] = Field(default_factory=dict)
    execute: dict[str, ApprovalTier] = Field(default_factory=dict)


class CrossDomainRule(BaseModel):
    domain: str
    mode: str = "brokered"  # brokered | denied


class AccessSpec(BaseModel):
    roles: list[RoleAccess] = Field(default_factory=list)
    agent_permissions: AgentPermissionSpec = Field(default_factory=AgentPermissionSpec)
    cross_domain: list[CrossDomainRule] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


class FreshnessOverride(BaseModel):
    path: str
    max_age: str = "24h"
    stale_action: str = "flag"  # flag | re-sync | archive


class FreshnessSpec(BaseModel):
    max_age: str = "24h"
    stale_action: str = "flag"
    expired_action: str = "archive"
    overrides: list[FreshnessOverride] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class RankingSignal(BaseModel):
    signal: str  # semantic_relevance | recency | authority | user_relevance
    weight: float = 0.25


class RoutingSpec(BaseModel):
    intent_parsing: str = "llm-assisted"  # llm-assisted | rule-based
    token_budget: int = 8000
    priority: list[RankingSignal] = Field(default_factory=list)
    conversation_aware: bool = True


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------


class PatternEngineConfig(BaseModel):
    min_signals: int = 3
    window_days: int = 30


class OperatorSpec(BaseModel):
    type: str = "master-agent"
    template: str = ""
    model: str = ""
    pattern_engine: PatternEngineConfig = Field(default_factory=PatternEngineConfig)
    guardrails: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Trust
# ---------------------------------------------------------------------------


class GuardrailPolicy(BaseModel):
    name: str
    trigger: str
    condition: str = ""
    action: str = ""


class AnomalyDetectionConfig(BaseModel):
    baseline: str = "per-user-per-role"
    threshold: str = "3x"
    response: str = "alert-admin"


class TrustSpec(BaseModel):
    policies: list[GuardrailPolicy] = Field(default_factory=list)
    anomaly_detection: AnomalyDetectionConfig = Field(default_factory=AnomalyDetectionConfig)
    audit_level: str = "full"
    audit_retention: str = "7y"


# ---------------------------------------------------------------------------
# Reliability
# ---------------------------------------------------------------------------


class ReliabilitySpec(BaseModel):
    min_level: float = 0.90
    method: str = "trustgate"
    schedule_deploy: bool = True
    schedule_model_change: bool = True
    schedule_monthly: bool = True


# ---------------------------------------------------------------------------
# The full manifest (Section 4.2, Listing 1)
# ---------------------------------------------------------------------------


class DomainManifest(BaseModel):
    """
    A complete Context Domain Manifest.

    apiVersion: context/v1
    kind: ContextDomain
    """

    api_version: str = "context/v1"
    kind: str = "ContextDomain"
    name: str
    namespace: str = "default"
    labels: dict[str, str] = Field(default_factory=dict)

    sources: list[SourceSpec] = Field(default_factory=list)
    access: AccessSpec = Field(default_factory=AccessSpec)
    freshness: FreshnessSpec = Field(default_factory=FreshnessSpec)
    routing: RoutingSpec = Field(default_factory=RoutingSpec)
    operator: OperatorSpec = Field(default_factory=OperatorSpec)
    trust: TrustSpec = Field(default_factory=TrustSpec)
    reliability: ReliabilitySpec = Field(default_factory=ReliabilitySpec)

    @classmethod
    def from_yaml(cls, path: str | Path) -> DomainManifest:
        """Load a manifest from a YAML file."""
        with open(path) as f:
            raw = yaml.safe_load(f)

        metadata = raw.get("metadata", {})
        spec = raw.get("spec", {})

        # Flatten nested YAML structure into Pydantic model
        access_raw = spec.get("access", {})
        agent_perms_raw = access_raw.get("agentPermissions", {})

        write_raw = agent_perms_raw.get("write", {})
        if isinstance(write_raw, str):
            write_default = ApprovalTier(write_raw)
            write_overrides = {}
        else:
            write_default = ApprovalTier(write_raw.get("default", "soft-approval"))
            write_overrides = {
                k: ApprovalTier(v) for k, v in write_raw.get("paths", {}).items()
            }

        execute_raw = agent_perms_raw.get("execute", {})
        execute = {k: ApprovalTier(v) for k, v in execute_raw.items()}

        agent_permissions = AgentPermissionSpec(
            read=agent_perms_raw.get("read", "autonomous"),
            write_default=write_default,
            write_overrides=write_overrides,
            execute=execute,
        )

        cross_domain = [
            CrossDomainRule(**cd) for cd in access_raw.get("crossDomain", [])
        ]

        freshness_raw = spec.get("freshness", {})
        defaults = freshness_raw.get("defaults", {})
        overrides = [
            FreshnessOverride(
                path=o.get("path", ""),
                max_age=o.get("maxAge", "24h"),
                stale_action=o.get("staleAction", "flag"),
            )
            for o in freshness_raw.get("overrides", [])
        ]

        routing_raw = spec.get("routing", {})
        priority = [
            RankingSignal(**s) for s in routing_raw.get("priority", [])
        ]

        trust_raw = spec.get("trust", {})
        policies = [
            GuardrailPolicy(**p) for p in trust_raw.get("policies", [])
        ]

        return cls(
            api_version=raw.get("apiVersion", "context/v1"),
            kind=raw.get("kind", "ContextDomain"),
            name=metadata.get("name", ""),
            namespace=metadata.get("namespace", "default"),
            labels=metadata.get("labels", {}),
            sources=[SourceSpec(**s) for s in spec.get("sources", [])],
            access=AccessSpec(
                roles=[RoleAccess(**r) for r in access_raw.get("roles", [])],
                agent_permissions=agent_permissions,
                cross_domain=cross_domain,
            ),
            freshness=FreshnessSpec(
                max_age=defaults.get("maxAge", "24h"),
                stale_action=defaults.get("staleAction", "flag"),
                expired_action=defaults.get("expiredAction", "archive"),
                overrides=overrides,
            ),
            routing=RoutingSpec(
                intent_parsing=routing_raw.get("intentParsing", "llm-assisted"),
                token_budget=routing_raw.get("tokenBudget", 8000),
                priority=priority,
                conversation_aware=routing_raw.get("conversationAware", True),
            ),
            operator=OperatorSpec(
                type=spec.get("operator", {}).get("type", "master-agent"),
                template=spec.get("operator", {}).get("template", ""),
                guardrails=spec.get("operator", {}).get("guardrails", []),
            ),
            trust=TrustSpec(
                policies=policies,
                anomaly_detection=AnomalyDetectionConfig(
                    **trust_raw.get("anomalyDetection", {})
                ),
                audit_level=trust_raw.get("audit", {}).get("level", "full"),
                audit_retention=trust_raw.get("audit", {}).get("retention", "7y"),
            ),
        )
