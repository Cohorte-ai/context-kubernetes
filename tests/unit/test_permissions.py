"""Tests for the Permission Engine — including invariant verification.

These tests verify Design Invariants 3.7 and 3.8 from the paper:
  3.7: Agent permissions are a strict subset of user permissions
  3.8: Strong approval is architecturally isolated from the agent
"""

import pytest

from context_kubernetes.models import (
    ActionRequest,
    ApprovalTier,
    OperationPermission,
)
from context_kubernetes.permissions.engine import PermissionEngine


@pytest.fixture
def engine():
    """Create an engine with a configured sales role."""
    e = PermissionEngine(otp_ttl_seconds=60)

    # Register role: what the USER can do
    e.register_role("sales-manager", [
        OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="send_email", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="commit_pricing", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        OperationPermission(operation="sign_contract", resources=["*"], tier=ApprovalTier.SOFT_APPROVAL),
    ])

    # Register agent profile: strict subset of user permissions
    e.register_agent_profile(
        user_id="user-sarah",
        role="sales-manager",
        agent_permissions=[
            OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.SOFT_APPROVAL),
            OperationPermission(operation="send_email", resources=["*"], tier=ApprovalTier.STRONG_APPROVAL),
        ],
        excluded_operations=["commit_pricing", "sign_contract"],
    )

    return e


class TestInvariant37_StrictSubset:
    """Design Invariant 3.7: P_{a_u} ⊂ P_u"""

    def test_agent_has_fewer_operations(self, engine):
        """Agent must have strictly fewer operations than user."""
        profile = engine._agent_profiles["user-sarah"]
        agent_ops = {p.operation for p in profile.permissions}
        user_ops = {p.operation for p in engine._role_permissions["sales-manager"]}
        assert agent_ops < user_ops  # strict subset

    def test_excluded_operations_exist(self, engine):
        """At least one user operation must be excluded from agent."""
        profile = engine._agent_profiles["user-sarah"]
        assert len(profile.excluded_operations) >= 1
        assert "commit_pricing" in profile.excluded_operations

    def test_agent_tier_not_less_restrictive(self, engine):
        """For shared operations, agent tier >= user tier."""
        profile = engine._agent_profiles["user-sarah"]
        # User can write autonomously, agent requires soft approval
        tier = profile.get_tier("write", "clients/henderson/notes.md")
        assert tier == ApprovalTier.SOFT_APPROVAL  # more restrictive than user's AUTONOMOUS

    def test_reject_superset_registration(self, engine):
        """Registering agent with operations not in user role must fail."""
        with pytest.raises(ValueError, match="Invariant 3.7"):
            engine.register_agent_profile(
                user_id="user-bad",
                role="sales-manager",
                agent_permissions=[
                    OperationPermission(operation="delete_database", tier=ApprovalTier.AUTONOMOUS),
                ],
            )

    def test_reject_equal_set_registration(self, engine):
        """Registering agent with ALL user operations (not strict subset) must fail."""
        all_user_ops = engine._role_permissions["sales-manager"]
        with pytest.raises(ValueError, match="STRICT subset"):
            engine.register_agent_profile(
                user_id="user-greedy",
                role="sales-manager",
                agent_permissions=all_user_ops,
                excluded_operations=[],
            )

    def test_reject_less_restrictive_tier(self, engine):
        """Agent with less restrictive tier than user must fail."""
        with pytest.raises(ValueError, match="less restrictive"):
            engine.register_agent_profile(
                user_id="user-lax",
                role="sales-manager",
                agent_permissions=[
                    # User has sign_contract at SOFT_APPROVAL
                    # Agent tries AUTONOMOUS — less restrictive → must fail
                    OperationPermission(
                        operation="sign_contract",
                        resources=["*"],
                        tier=ApprovalTier.AUTONOMOUS,
                    ),
                ],
                excluded_operations=["read", "write", "send_email", "commit_pricing"],
            )

    def test_default_deny(self, engine):
        """Operations not in the profile are EXCLUDED."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        tier, _ = engine.authorize(session.session_id, "drop_table", "production_db")
        assert tier == ApprovalTier.EXCLUDED


class TestInvariant38_StrongApprovalIsolation:
    """Design Invariant 3.8: Strong approval channel is architecturally isolated."""

    def test_t3_otp_not_returned_to_agent(self, engine):
        """The OTP must NOT be returned in the approval request."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        action = ActionRequest(
            session_id=session.session_id,
            action_type="send_email",
            resource="client@external.com",
        )

        approval = engine.request_approval(
            session.session_id, action, ApprovalTier.STRONG_APPROVAL
        )

        # The approval request contains the approval_id but NOT the OTP
        assert approval.approval_id.startswith("apr-")
        # The approval object has no OTP field accessible to the agent
        assert not hasattr(approval, "otp")
        assert not hasattr(approval, "verification_code")

    def test_t3_correct_otp_approves(self, engine):
        """Correct OTP from out-of-band channel approves the action."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        action = ActionRequest(
            session_id=session.session_id,
            action_type="send_email",
            resource="client@external.com",
        )

        approval = engine.request_approval(
            session.session_id, action, ApprovalTier.STRONG_APPROVAL
        )

        # Simulate user reading OTP from their phone (out-of-band)
        otp = engine.get_otp_from_channel("user-sarah", approval.approval_id)
        assert otp is not None

        # Verify through the separate endpoint
        result = engine.resolve_approval_t3(approval.approval_id, otp)
        assert result is True

    def test_t3_wrong_otp_denied(self, engine):
        """Wrong OTP must be denied."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        action = ActionRequest(
            session_id=session.session_id,
            action_type="send_email",
            resource="client@external.com",
        )

        approval = engine.request_approval(
            session.session_id, action, ApprovalTier.STRONG_APPROVAL
        )

        # Agent tries to guess the OTP
        result = engine.resolve_approval_t3(approval.approval_id, "WRONG!")
        assert result is False

    def test_t3_cannot_resolve_as_t2(self, engine):
        """A T3 approval cannot be resolved through the T2 path."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        action = ActionRequest(
            session_id=session.session_id,
            action_type="send_email",
            resource="client@external.com",
        )

        approval = engine.request_approval(
            session.session_id, action, ApprovalTier.STRONG_APPROVAL
        )

        # Try to resolve via T2 (bypass the OTP)
        result = engine.resolve_approval_t2(approval.approval_id, True)
        assert result is False  # Must fail — wrong tier

    def test_t3_replay_attack_fails(self, engine):
        """Using the same OTP twice must fail."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        action = ActionRequest(
            session_id=session.session_id,
            action_type="send_email",
            resource="client@external.com",
        )

        approval = engine.request_approval(
            session.session_id, action, ApprovalTier.STRONG_APPROVAL
        )

        otp = engine.get_otp_from_channel("user-sarah", approval.approval_id)
        assert otp is not None

        # First use: succeeds
        result1 = engine.resolve_approval_t3(approval.approval_id, otp)
        assert result1 is True

        # Second use (replay): fails because already resolved
        result2 = engine.resolve_approval_t3(approval.approval_id, otp)
        assert result2 is False


class TestApprovalWorkflow:
    def test_t1_no_approval_needed(self, engine):
        """Autonomous operations need no approval."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        tier, _ = engine.authorize(session.session_id, "read", "clients/henderson/profile.md")
        assert tier == ApprovalTier.AUTONOMOUS

    def test_t2_soft_approval_flow(self, engine):
        """Tier 2: agent proposes, user confirms."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        action = ActionRequest(
            session_id=session.session_id,
            action_type="write",
            resource="clients/henderson/notes.md",
        )

        approval = engine.request_approval(
            session.session_id, action, ApprovalTier.SOFT_APPROVAL
        )

        result = engine.resolve_approval_t2(approval.approval_id, approved=True)
        assert result is True

    def test_t2_rejection(self, engine):
        """User can reject a Tier 2 action."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        action = ActionRequest(
            session_id=session.session_id,
            action_type="write",
            resource="clients/henderson/notes.md",
        )

        approval = engine.request_approval(
            session.session_id, action, ApprovalTier.SOFT_APPROVAL
        )

        result = engine.resolve_approval_t2(approval.approval_id, approved=False)
        assert result is False


class TestKillSwitch:
    def test_kill_single_session(self, engine):
        """Kill switch: terminate a single session."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        assert session.active is True

        engine.kill_session(session.session_id)
        assert engine.get_session(session.session_id) is None

        # Authorization must fail after kill
        tier, _ = engine.authorize(session.session_id, "read", "anything")
        assert tier == ApprovalTier.EXCLUDED

    def test_kill_all_user_sessions(self, engine):
        """Kill switch: terminate all sessions for a user."""
        s1 = engine.create_session("user-sarah", "agent-1", "sales-manager")
        s2 = engine.create_session("user-sarah", "agent-2", "sales-manager")

        killed = engine.kill_all_sessions(user_id="user-sarah")
        assert killed == 2
        assert engine.get_session(s1.session_id) is None
        assert engine.get_session(s2.session_id) is None


class TestAuditLog:
    def test_permission_checks_are_logged(self, engine):
        """Every permission check must be logged."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        engine.authorize(session.session_id, "read", "clients/henderson/profile.md")
        engine.authorize(session.session_id, "write", "clients/henderson/notes.md")

        log = engine.get_audit_log()
        perm_checks = [e for e in log if e.event_type == "permission_check"]
        assert len(perm_checks) == 2
        assert perm_checks[0].operation == "read"
        assert perm_checks[1].operation == "write"

    def test_approval_requests_are_logged(self, engine):
        """Every approval request must be logged."""
        session = engine.create_session("user-sarah", "agent-1", "sales-manager")
        action = ActionRequest(
            session_id=session.session_id,
            action_type="send_email",
            resource="client@external.com",
        )
        engine.request_approval(session.session_id, action, ApprovalTier.STRONG_APPROVAL)

        log = engine.get_audit_log()
        approval_events = [e for e in log if e.event_type == "approval_requested"]
        assert len(approval_events) == 1
        assert approval_events[0].details["tier"] == "strong-approval"
