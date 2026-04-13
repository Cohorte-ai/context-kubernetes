"""Core domain models — the six abstractions from the paper."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ContentType(StrEnum):
    UNSTRUCTURED = "unstructured"
    STRUCTURED = "structured"
    HYBRID = "hybrid"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    CONFLICTED = "conflicted"


class ApprovalTier(StrEnum):
    AUTONOMOUS = "autonomous"  # T1: agent acts freely
    SOFT_APPROVAL = "soft-approval"  # T2: user confirms in UI
    STRONG_APPROVAL = "strong-approval"  # T3: out-of-band 2FA
    EXCLUDED = "excluded"  # not in agent profile


class ActionOutcome(StrEnum):
    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"
    EXPIRED = "expired"


class DriftType(StrEnum):
    SOURCE_DISCONNECTED = "source_disconnected"
    CONTEXT_STALE = "context_stale"
    OPERATOR_UNHEALTHY = "operator_unhealthy"
    ANOMALY = "anomaly"
    RELIABILITY_DRIFT = "reliability_drift"
    PERMISSION_CHANGE = "permission_change"


# ---------------------------------------------------------------------------
# Definition 3.1: Context Unit
# ---------------------------------------------------------------------------


class ContextUnitMetadata(BaseModel):
    """Metadata set m for a context unit."""

    author: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    domain: str
    sensitivity: str = "internal"  # public | internal | confidential | restricted
    entities: list[str] = Field(default_factory=list)
    source: str  # identifier of the CxRI connector that produced this unit


class ContextUnit(BaseModel):
    """
    Definition 3.1: The smallest addressable element of organizational knowledge.

    u = (c, τ, m, v, e, π)
    """

    id: str = ""
    content: str  # c
    content_type: ContentType  # τ
    metadata: ContextUnitMetadata  # m
    version: str  # v — git commit hash, DB change ID, or timestamp
    embedding: list[float] = Field(default_factory=list)  # e ∈ ℝ^d
    authorized_roles: set[str] = Field(default_factory=set)  # π ⊆ R
    freshness: FreshnessState = FreshnessState.FRESH
    token_count: int = 0

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            h = hashlib.sha256(
                f"{self.metadata.source}:{self.metadata.domain}:{self.version}:{self.content[:100]}".encode()
            ).hexdigest()[:16]
            self.id = f"cu-{h}"
        if not self.token_count:
            self.token_count = len(self.content.split())  # rough estimate


# ---------------------------------------------------------------------------
# Definition 3.7 / 3.8: Permission Model
# ---------------------------------------------------------------------------


class OperationPermission(BaseModel):
    """A single permitted operation with its required approval tier."""

    operation: str  # e.g., "read", "write", "send_email", "update_crm"
    resources: list[str] = Field(default_factory=lambda: ["*"])  # glob patterns
    tier: ApprovalTier = ApprovalTier.AUTONOMOUS


class AgentPermissionProfile(BaseModel):
    """
    Design Invariant 3.7: Agent permissions are a strict subset of user permissions.

    P_{a_u} ⊂ P_u, and T(o, a_u) >= T(o, u) for all shared operations.
    """

    user_id: str
    role: str
    permissions: list[OperationPermission] = Field(default_factory=list)
    excluded_operations: list[str] = Field(default_factory=list)

    def get_tier(self, operation: str, resource: str) -> ApprovalTier:
        """Determine the approval tier for a given operation on a resource."""
        if operation in self.excluded_operations:
            return ApprovalTier.EXCLUDED

        import fnmatch

        for perm in self.permissions:
            if perm.operation == operation:
                if any(fnmatch.fnmatch(resource, pat) for pat in perm.resources):
                    return perm.tier
        return ApprovalTier.EXCLUDED  # default-deny


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class Session(BaseModel):
    """An authenticated, scoped agent session."""

    session_id: str
    user_id: str
    agent_id: str
    role: str
    workspace_scope: str  # e.g., "clients/henderson"
    permission_profile: AgentPermissionProfile
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    active: bool = True


# ---------------------------------------------------------------------------
# Context Request / Response (the Context Endpoint contract)
# ---------------------------------------------------------------------------


class ContextRequest(BaseModel):
    """A request from an agent to the Context Endpoint."""

    session_id: str
    intent: str  # natural language query
    workspace_scope: str = ""
    token_budget: int = 8000


class ContextResponse(BaseModel):
    """Filtered, ranked context delivered to the agent."""

    request_id: str
    units: list[ContextUnit] = Field(default_factory=list)
    total_tokens: int = 0
    freshness_warnings: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Action Request / Approval
# ---------------------------------------------------------------------------


class ActionRequest(BaseModel):
    """An agent's request to perform an action."""

    session_id: str
    action_type: str  # e.g., "send_email", "update_record"
    resource: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    """Sent to the user when T2/T3 approval is required."""

    approval_id: str
    action: ActionRequest
    tier: ApprovalTier
    description: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None


class ApprovalResponse(BaseModel):
    """User's response to an approval request."""

    approval_id: str
    approved: bool
    verification_code: str | None = None  # for T3: OTP from out-of-band channel


# ---------------------------------------------------------------------------
# Audit Event
# ---------------------------------------------------------------------------


class AuditEvent(BaseModel):
    """Immutable record of every interaction with the system."""

    event_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str
    user_id: str
    agent_id: str = ""
    event_type: str  # context_request | action_submit | approval | permission_check | ...
    operation: str = ""
    resource: str = ""
    outcome: str = ""  # allowed | denied | pending | error
    latency_ms: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class DriftEvent(BaseModel):
    """A detected divergence between desired and actual state."""

    drift_type: DriftType
    domain: str
    source: str = ""
    details: str = ""
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved: bool = False
    resolution: str = ""
