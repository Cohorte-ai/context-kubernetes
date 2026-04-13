"""Application state — wires all components together.

This is where the Context Registry, Router, Permission Engine,
Reconciliation Loop, and Audit Log are initialized and connected.
"""

from __future__ import annotations

import os
from pathlib import Path

from context_kubernetes.audit.log import InMemoryAuditLog, FileAuditLog
from context_kubernetes.config.manifest import DomainManifest
from context_kubernetes.cxri.connectors.git_connector import GitConnector
from context_kubernetes.cxri.interface import ConnectionConfig
from context_kubernetes.models import ApprovalTier, OperationPermission
from context_kubernetes.permissions.engine import PermissionEngine
from context_kubernetes.reconciliation.loop import ReconciliationLoop
from context_kubernetes.router.intent import IntentClassifier
from context_kubernetes.router.ranking import RankingEngine, RankingSignalWeights
from context_kubernetes.router.router import ContextRouter


class AppState:
    """
    Central application state.

    Owns all components and manages their lifecycle.
    Initialized once at startup, torn down on shutdown.
    """

    def __init__(self) -> None:
        self.permission_engine = PermissionEngine()
        self.audit_log = InMemoryAuditLog()
        self.reconciliation = ReconciliationLoop(interval_seconds=30)
        self.router = ContextRouter(
            permission_engine=self.permission_engine,
        )
        self._connectors: list[GitConnector] = []

    async def initialize(self) -> None:
        """
        Initialize the system.

        In production: load manifests, connect to sources, start reconciliation.
        For the prototype: set up a demo configuration.
        """
        # Load manifests from environment or default path
        manifest_dir = os.environ.get("CK8S_MANIFESTS", "")
        if manifest_dir and Path(manifest_dir).is_dir():
            await self._load_manifests(Path(manifest_dir))
        else:
            self._setup_demo()

    async def shutdown(self) -> None:
        """Clean shutdown."""
        self.reconciliation.stop()
        for conn in self._connectors:
            await conn.disconnect()

    async def _load_manifests(self, manifest_dir: Path) -> None:
        """Load all YAML manifests from a directory."""
        for yaml_file in sorted(manifest_dir.glob("*.yaml")):
            manifest = DomainManifest.from_yaml(yaml_file)
            await self._apply_manifest(manifest)

    async def _apply_manifest(self, manifest: DomainManifest) -> None:
        """Apply a domain manifest — connect sources, configure permissions."""
        domain = manifest.name

        # Set up routing weights from manifest
        if manifest.routing.priority:
            weights = RankingSignalWeights(
                **{s.signal: s.weight for s in manifest.routing.priority}
            )
            self.router._ranker = RankingEngine(weights=weights)

        # Configure intent classifier
        self.router._classifier = IntentClassifier(
            available_domains=[manifest.name],
        )

        # Connect sources
        for source_spec in manifest.sources:
            if source_spec.type == "git-repo":
                endpoint = source_spec.config.get("repo", "")
                if endpoint and Path(endpoint).is_dir():
                    connector = GitConnector()
                    config = ConnectionConfig(
                        connector_type="git-repo",
                        endpoint=endpoint,
                        scope=source_spec.config.get("scope", ""),
                        extra={"domain": domain},
                    )
                    await connector.connect(config)
                    self.router.register_connector(domain, connector)
                    self.reconciliation.register_source(
                        name=source_spec.name,
                        domain=domain,
                        connector=connector,
                        max_age=manifest.freshness.max_age,
                        stale_action=manifest.freshness.stale_action,
                    )
                    self._connectors.append(connector)

        # Configure cross-domain rules
        allowed = set()
        for rule in manifest.access.cross_domain:
            if rule.mode == "brokered":
                allowed.add(rule.domain)
        self.router.set_cross_domain_rules(domain, allowed)

    def _setup_demo(self) -> None:
        """Set up a minimal demo configuration for testing."""
        # Register roles
        self.permission_engine.register_role("sales-rep", [
            OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="send_email", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="commit_pricing", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
        ])

        self.permission_engine.register_role("sales-manager", [
            OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="write", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="send_email", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="commit_pricing", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
            OperationPermission(operation="sign_contract", resources=["*"], tier=ApprovalTier.SOFT_APPROVAL),
        ])

        # Register agent profiles (strict subset of user permissions)
        self.permission_engine.register_agent_profile(
            user_id="demo-user",
            role="sales-rep",
            agent_permissions=[
                OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
                OperationPermission(operation="write", resources=["clients/*"], tier=ApprovalTier.SOFT_APPROVAL),
                OperationPermission(operation="send_email", resources=["*"], tier=ApprovalTier.STRONG_APPROVAL),
            ],
            excluded_operations=["commit_pricing"],
        )

        self.permission_engine.register_agent_profile(
            user_id="demo-manager",
            role="sales-manager",
            agent_permissions=[
                OperationPermission(operation="read", resources=["*"], tier=ApprovalTier.AUTONOMOUS),
                OperationPermission(operation="write", resources=["*"], tier=ApprovalTier.SOFT_APPROVAL),
                OperationPermission(operation="send_email", resources=["*"], tier=ApprovalTier.STRONG_APPROVAL),
            ],
            excluded_operations=["commit_pricing", "sign_contract"],
        )

        # Set up router with available domains
        self.router._classifier = IntentClassifier(
            available_domains=["sales", "delivery", "hr", "finance", "operations"],
        )


# -----------------------------------------------------------------------
# Singleton
# -----------------------------------------------------------------------

_state: AppState | None = None


def get_state() -> AppState:
    """Get or create the application state singleton."""
    global _state
    if _state is None:
        _state = AppState()
    return _state


def reset_state() -> None:
    """Reset state (for testing)."""
    global _state
    _state = None
