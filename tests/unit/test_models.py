"""Tests for core domain models — the six abstractions."""

from context_kubernetes.models import (
    ActionRequest,
    AgentPermissionProfile,
    ApprovalTier,
    ContextUnit,
    ContextUnitMetadata,
    ContentType,
    FreshnessState,
    OperationPermission,
    Session,
)


class TestContextUnit:
    def test_create_minimal(self):
        unit = ContextUnit(
            content="Henderson project is on track for Q2 delivery.",
            content_type=ContentType.UNSTRUCTURED,
            metadata=ContextUnitMetadata(domain="delivery", source="git"),
            version="abc123",
        )
        assert unit.id.startswith("cu-")
        assert unit.freshness == FreshnessState.FRESH
        assert unit.token_count > 0

    def test_auto_generates_id(self):
        unit = ContextUnit(
            content="Test content",
            content_type=ContentType.UNSTRUCTURED,
            metadata=ContextUnitMetadata(domain="test", source="test"),
            version="v1",
        )
        assert len(unit.id) == 19  # "cu-" + 16 hex chars

    def test_authorized_roles(self):
        unit = ContextUnit(
            content="Confidential pricing info",
            content_type=ContentType.UNSTRUCTURED,
            metadata=ContextUnitMetadata(
                domain="sales", source="git", sensitivity="confidential"
            ),
            version="v1",
            authorized_roles={"sales-manager", "c-level"},
        )
        assert "sales-manager" in unit.authorized_roles
        assert "sales-rep" not in unit.authorized_roles


class TestAgentPermissionProfile:
    def test_autonomous_operation(self):
        profile = AgentPermissionProfile(
            user_id="user-1",
            role="sales-rep",
            permissions=[
                OperationPermission(
                    operation="read", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS
                ),
            ],
        )
        tier = profile.get_tier("read", "clients/henderson/profile.md")
        assert tier == ApprovalTier.AUTONOMOUS

    def test_soft_approval_operation(self):
        profile = AgentPermissionProfile(
            user_id="user-1",
            role="sales-rep",
            permissions=[
                OperationPermission(
                    operation="write",
                    resources=["clients/*"],
                    tier=ApprovalTier.SOFT_APPROVAL,
                ),
            ],
        )
        tier = profile.get_tier("write", "clients/henderson/notes.md")
        assert tier == ApprovalTier.SOFT_APPROVAL

    def test_strong_approval_operation(self):
        profile = AgentPermissionProfile(
            user_id="user-1",
            role="sales-rep",
            permissions=[
                OperationPermission(
                    operation="write",
                    resources=["clients/*/contracts/*"],
                    tier=ApprovalTier.STRONG_APPROVAL,
                ),
            ],
        )
        tier = profile.get_tier("write", "clients/henderson/contracts/proposal.pdf")
        assert tier == ApprovalTier.STRONG_APPROVAL

    def test_excluded_operation(self):
        profile = AgentPermissionProfile(
            user_id="user-1",
            role="sales-rep",
            excluded_operations=["commit-to-pricing", "terminate-employee"],
        )
        tier = profile.get_tier("commit-to-pricing", "any-resource")
        assert tier == ApprovalTier.EXCLUDED

    def test_default_deny(self):
        """Operations not in the profile are EXCLUDED (default-deny)."""
        profile = AgentPermissionProfile(
            user_id="user-1",
            role="sales-rep",
            permissions=[
                OperationPermission(
                    operation="read", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS
                ),
            ],
        )
        tier = profile.get_tier("delete", "clients/henderson")
        assert tier == ApprovalTier.EXCLUDED

    def test_strict_subset_invariant(self):
        """
        Design Invariant 3.7: P_{a_u} ⊂ P_u

        The agent permission set must be a strict subset of the user's.
        For every user, there exists at least one operation the user can
        perform but the agent cannot.
        """
        user_operations = {"read", "write", "send_email", "commit_pricing", "sign_contract"}

        profile = AgentPermissionProfile(
            user_id="user-1",
            role="sales-manager",
            permissions=[
                OperationPermission(operation="read", tier=ApprovalTier.AUTONOMOUS),
                OperationPermission(operation="write", tier=ApprovalTier.SOFT_APPROVAL),
                OperationPermission(operation="send_email", tier=ApprovalTier.STRONG_APPROVAL),
            ],
            excluded_operations=["commit_pricing", "sign_contract"],
        )

        agent_operations = {
            p.operation for p in profile.permissions
        }

        # Agent permissions are a strict subset
        assert agent_operations < user_operations
        # There exist operations the user can do but the agent cannot
        assert len(user_operations - agent_operations) >= 1


class TestManifestParsing:
    def test_load_sales_manifest(self):
        from pathlib import Path

        from context_kubernetes.config.manifest import DomainManifest

        manifest_path = Path(__file__).parent.parent.parent / "manifests" / "sales-domain.yaml"
        manifest = DomainManifest.from_yaml(manifest_path)

        assert manifest.name == "sales"
        assert manifest.namespace == "acme-corp"
        assert len(manifest.sources) == 3
        assert manifest.sources[0].name == "client-context"
        assert manifest.sources[0].type == "git-repo"
        assert manifest.routing.token_budget == 8000
        assert len(manifest.routing.priority) == 4
        assert manifest.access.agent_permissions.execute.get("commit-to-pricing") == ApprovalTier.EXCLUDED
        assert manifest.access.agent_permissions.execute.get("send-external-email") == ApprovalTier.STRONG_APPROVAL
        assert len(manifest.trust.policies) == 1
        assert manifest.trust.policies[0].name == "no-unreviewed-external-email"
