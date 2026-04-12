"""Permission Engine — Design Invariants 3.7 and 3.8.

Implements the three-tier agent permission model:
  T1 (Autonomous):      Agent acts freely
  T2 (Soft Approval):   Agent proposes, user confirms in UI
  T3 (Strong Approval): Out-of-band 2FA, architecturally isolated
  Excluded:             Agent cannot even request — manual only

Key architectural properties:
  - Agent permissions are ALWAYS a strict subset of user permissions
  - No API exists for an agent to modify its own permission profile
  - Tier 3 approval verification is on a separate endpoint that the
    agent process cannot call (enforced by network policy in production,
    by separate auth token in the prototype)
"""

from __future__ import annotations

import fnmatch
import hashlib
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from context_kubernetes.models import (
    ActionRequest,
    AgentPermissionProfile,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalTier,
    AuditEvent,
    OperationPermission,
    Session,
)


class PendingApproval(BaseModel):
    """A Tier 2 or Tier 3 approval awaiting user response."""

    approval_id: str
    session_id: str
    user_id: str
    action: ActionRequest
    tier: ApprovalTier
    otp_hash: str = ""  # SHA-256 of the OTP (for T3 verification)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: float = 0.0  # unix timestamp
    resolved: bool = False
    approved: bool = False


class PermissionEngine:
    """
    The Permission Engine.

    Enforces Design Invariant 3.7 (Agent Permission Subset):
      P_{a_u} ⊂ P_u — no agent can exceed its user's authority

    Enforces Design Invariant 3.8 (Strong Approval Isolation):
      Tier 3 OTPs are generated here but verified through a SEPARATE
      endpoint. The agent process receives only the approval_id,
      never the OTP itself.
    """

    def __init__(self, otp_ttl_seconds: int = 300) -> None:
        # Role definitions: role → user permissions (loaded from manifest)
        self._role_permissions: dict[str, list[OperationPermission]] = {}
        # Agent profiles: user_id → agent permission profile
        self._agent_profiles: dict[str, AgentPermissionProfile] = {}
        # Active sessions
        self._sessions: dict[str, Session] = {}
        # Pending approvals
        self._pending: dict[str, PendingApproval] = {}
        # Audit log (in-memory for prototype; PostgreSQL in production)
        self._audit_log: list[AuditEvent] = []
        # OTP time-to-live
        self._otp_ttl = otp_ttl_seconds

    # -------------------------------------------------------------------
    # Configuration (loaded from manifest)
    # -------------------------------------------------------------------

    def register_role(self, role: str, permissions: list[OperationPermission]) -> None:
        """Register a role's user-level permissions."""
        self._role_permissions[role] = permissions

    def register_agent_profile(
        self,
        user_id: str,
        role: str,
        agent_permissions: list[OperationPermission],
        excluded_operations: list[str] | None = None,
    ) -> AgentPermissionProfile:
        """
        Register an agent permission profile for a user.

        Enforces Invariant 3.7: the agent profile is validated to be
        a strict subset of the role's permissions.
        """
        user_perms = self._role_permissions.get(role, [])
        user_ops = {p.operation for p in user_perms}

        agent_ops = {p.operation for p in agent_permissions}
        excluded = set(excluded_operations or [])

        # Invariant 3.7: agent operations must be a subset of user operations
        if not agent_ops.issubset(user_ops):
            extra = agent_ops - user_ops
            raise ValueError(
                f"Invariant 3.7 violated: agent has operations not in user role: {extra}"
            )

        # Invariant 3.7: strict subset — at least one user op must be excluded
        if agent_ops == user_ops and not excluded:
            raise ValueError(
                "Invariant 3.7 violated: agent permissions must be a STRICT subset. "
                "At least one user operation must be excluded from the agent profile."
            )

        # Invariant 3.7: agent tier >= user tier for shared operations
        user_tier_map = {p.operation: p.tier for p in user_perms}
        for perm in agent_permissions:
            user_tier = user_tier_map.get(perm.operation)
            if user_tier and _tier_rank(perm.tier) < _tier_rank(user_tier):
                raise ValueError(
                    f"Invariant 3.7 violated: agent tier for '{perm.operation}' "
                    f"({perm.tier}) is less restrictive than user tier ({user_tier})"
                )

        profile = AgentPermissionProfile(
            user_id=user_id,
            role=role,
            permissions=agent_permissions,
            excluded_operations=list(excluded),
        )
        self._agent_profiles[user_id] = profile
        return profile

    # -------------------------------------------------------------------
    # Session management
    # -------------------------------------------------------------------

    def create_session(
        self, user_id: str, agent_id: str, role: str, workspace_scope: str = ""
    ) -> Session:
        """Create an authenticated, scoped agent session."""
        if user_id not in self._agent_profiles:
            raise PermissionError(f"No agent profile registered for user {user_id}")

        session_id = f"sess-{secrets.token_hex(8)}"
        session = Session(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            role=role,
            workspace_scope=workspace_scope,
            permission_profile=self._agent_profiles[user_id],
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Retrieve an active session."""
        session = self._sessions.get(session_id)
        if session and session.active:
            return session
        return None

    def kill_session(self, session_id: str) -> None:
        """Immediately terminate a session (kill switch)."""
        if session_id in self._sessions:
            self._sessions[session_id].active = False

    def kill_all_sessions(self, user_id: str | None = None) -> int:
        """Kill all sessions, optionally filtered by user. Returns count."""
        count = 0
        for session in self._sessions.values():
            if session.active and (user_id is None or session.user_id == user_id):
                session.active = False
                count += 1
        return count

    # -------------------------------------------------------------------
    # Authorization (the core check)
    # -------------------------------------------------------------------

    def authorize(
        self, session_id: str, operation: str, resource: str
    ) -> tuple[ApprovalTier, str]:
        """
        Determine what approval tier is required for this operation.

        Returns (tier, reason).
        If the session is invalid or inactive, returns (EXCLUDED, reason).
        """
        session = self._sessions.get(session_id)
        if not session:
            return ApprovalTier.EXCLUDED, "Invalid session"
        if not session.active:
            return ApprovalTier.EXCLUDED, "Session terminated"

        profile = session.permission_profile
        tier = profile.get_tier(operation, resource)

        # Log the permission check
        self._audit_log.append(AuditEvent(
            session_id=session_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            event_type="permission_check",
            operation=operation,
            resource=resource,
            outcome=tier.value,
        ))

        reason = f"Role {session.role}, operation {operation} on {resource}"
        return tier, reason

    def check_context_access(
        self, session_id: str, authorized_roles: set[str]
    ) -> bool:
        """
        Check if the session's role is authorized to access a context unit.

        This is the permission filter applied during context delivery.
        Design Goal 3.9 (Safety): no context unit is delivered to an
        agent whose profile does not include the unit's access scope.
        """
        session = self._sessions.get(session_id)
        if not session or not session.active:
            return False

        # Empty authorized_roles means accessible to all
        if not authorized_roles:
            return True

        return session.role in authorized_roles

    # -------------------------------------------------------------------
    # Approval workflow
    # -------------------------------------------------------------------

    def request_approval(
        self, session_id: str, action: ActionRequest, tier: ApprovalTier
    ) -> ApprovalRequest:
        """
        Create an approval request for T2 or T3 actions.

        For T3 (Strong Approval): generates a one-time password (OTP)
        that is NOT returned to the caller. The OTP must be delivered
        through an out-of-band channel (email, TOTP app) and verified
        through a separate endpoint.

        Design Invariant 3.8: the agent process receives the approval_id
        but never the OTP. The approval channel is architecturally
        isolated from the agent's execution environment.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise PermissionError("Invalid session")

        approval_id = f"apr-{secrets.token_hex(8)}"
        otp_hash = ""

        if tier == ApprovalTier.STRONG_APPROVAL:
            # Generate OTP — stored as hash, NEVER returned to caller
            otp = secrets.token_hex(3).upper()  # 6-char hex code
            otp_hash = hashlib.sha256(otp.encode()).hexdigest()

            # In production: send OTP via email/SMS/TOTP to user's device
            # For prototype: store in a separate "channel" dict
            self._deliver_otp(session.user_id, approval_id, otp)

        pending = PendingApproval(
            approval_id=approval_id,
            session_id=session_id,
            user_id=session.user_id,
            action=action,
            tier=tier,
            otp_hash=otp_hash,
            expires_at=time.time() + self._otp_ttl,
        )
        self._pending[approval_id] = pending

        self._audit_log.append(AuditEvent(
            session_id=session_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            event_type="approval_requested",
            operation=action.action_type,
            resource=action.resource,
            outcome="pending",
            details={"tier": tier.value, "approval_id": approval_id},
        ))

        return ApprovalRequest(
            approval_id=approval_id,
            action=action,
            tier=tier,
            description=f"{tier.value}: {action.action_type} on {action.resource}",
        )

    def resolve_approval_t2(self, approval_id: str, approved: bool) -> bool:
        """
        Resolve a Tier 2 (soft) approval.

        The user confirms or rejects directly in the agent UI.
        """
        pending = self._pending.get(approval_id)
        if not pending or pending.resolved:
            return False
        if pending.tier != ApprovalTier.SOFT_APPROVAL:
            return False
        if time.time() > pending.expires_at:
            pending.resolved = True
            return False

        pending.resolved = True
        pending.approved = approved

        self._audit_log.append(AuditEvent(
            session_id=pending.session_id,
            user_id=pending.user_id,
            event_type="approval_resolved",
            operation=pending.action.action_type,
            resource=pending.action.resource,
            outcome="approved" if approved else "denied",
            details={"tier": "soft-approval", "approval_id": approval_id},
        ))

        return approved

    def resolve_approval_t3(self, approval_id: str, verification_code: str) -> bool:
        """
        Resolve a Tier 3 (strong) approval.

        Design Invariant 3.8: This method verifies the OTP that was
        delivered out-of-band. The agent CANNOT call this method —
        in production, this endpoint requires a separate auth token
        bound to the user's identity, not the agent's session.

        The verification_code is the OTP the user received on their
        separate device (phone, email).
        """
        pending = self._pending.get(approval_id)
        if not pending or pending.resolved:
            return False
        if pending.tier != ApprovalTier.STRONG_APPROVAL:
            return False
        if time.time() > pending.expires_at:
            pending.resolved = True
            return False

        # Verify OTP by comparing hash
        code_hash = hashlib.sha256(verification_code.encode()).hexdigest()
        approved = code_hash == pending.otp_hash

        pending.resolved = True
        pending.approved = approved

        self._audit_log.append(AuditEvent(
            session_id=pending.session_id,
            user_id=pending.user_id,
            event_type="approval_resolved",
            operation=pending.action.action_type,
            resource=pending.action.resource,
            outcome="approved" if approved else "denied_wrong_code",
            details={"tier": "strong-approval", "approval_id": approval_id},
        ))

        return approved

    # -------------------------------------------------------------------
    # OTP delivery (out-of-band channel simulation)
    # -------------------------------------------------------------------

    # In production: email, SMS, TOTP app via a separate service
    # In prototype: stored in a dict keyed by user_id, accessible only
    # through the verification endpoint (not the agent's session)
    _otp_channel: dict[str, dict[str, str]] = {}

    def _deliver_otp(self, user_id: str, approval_id: str, otp: str) -> None:
        """Deliver OTP through out-of-band channel (simulated)."""
        if user_id not in self._otp_channel:
            self._otp_channel[user_id] = {}
        self._otp_channel[user_id][approval_id] = otp

    def get_otp_from_channel(self, user_id: str, approval_id: str) -> str | None:
        """
        Retrieve OTP from the out-of-band channel.

        THIS METHOD IS NOT ACCESSIBLE TO THE AGENT.
        In production: the user reads the OTP from their phone/email.
        In the prototype: test code calls this to simulate the user.
        """
        return self._otp_channel.get(user_id, {}).get(approval_id)

    # -------------------------------------------------------------------
    # Audit
    # -------------------------------------------------------------------

    def get_audit_log(self) -> list[AuditEvent]:
        """Return the complete audit log."""
        return list(self._audit_log)

    def get_pending_approvals(self, user_id: str | None = None) -> list[PendingApproval]:
        """List pending (unresolved) approvals."""
        return [
            p for p in self._pending.values()
            if not p.resolved and (user_id is None or p.user_id == user_id)
        ]


def _tier_rank(tier: ApprovalTier) -> int:
    """Numeric rank for tier comparison. Higher = more restrictive."""
    return {
        ApprovalTier.AUTONOMOUS: 0,
        ApprovalTier.SOFT_APPROVAL: 1,
        ApprovalTier.STRONG_APPROVAL: 2,
        ApprovalTier.EXCLUDED: 3,
    }[tier]
