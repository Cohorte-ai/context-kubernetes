"""Integration tests for the Context API — full end-to-end workflows.

Tests the complete pipeline: session → context request → action → approval → audit.
These are the workflow traces from the paper's Section 6.2.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import Repo

from context_kubernetes.api.app import app
from context_kubernetes.api.state import get_state, reset_state, AppState
from context_kubernetes.cxri.connectors.git_connector import GitConnector
from context_kubernetes.cxri.interface import ConnectionConfig
from context_kubernetes.models import ApprovalTier, OperationPermission


@pytest.fixture(autouse=True)
def clean_state():
    """Reset application state between tests."""
    reset_state()
    yield
    reset_state()


@pytest.fixture
def client_with_repo():
    """Set up a test client with a git repo connected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test repo
        repo = Repo.init(tmpdir)
        clients = Path(tmpdir) / "clients" / "henderson"
        clients.mkdir(parents=True)
        (clients / "profile.md").write_text(
            "# Henderson Corp\nIndustry: Manufacturing\nContact: Sarah Henderson\n"
            "Status: Active client\nBudget: €180K for Q2\n"
        )
        (clients / "communications.md").write_text(
            "## March 15 Meeting Notes\n\n"
            "Sarah mentioned budget concerns for Q2.\n"
            "Delivery timeline: 8 weeks preferred.\n"
        )
        (Path(tmpdir) / "pipeline.md").write_text(
            "# Pipeline\n| Client | Stage | Value |\n| Henderson | Proposal | €180K |\n"
        )
        repo.index.add([
            "clients/henderson/profile.md",
            "clients/henderson/communications.md",
            "pipeline.md",
        ])
        repo.index.commit("Initial context")

        # Configure the app state
        state = get_state()
        state._setup_demo()

        # Connect git repo
        import asyncio
        connector = GitConnector()
        asyncio.get_event_loop().run_until_complete(
            connector.connect(ConnectionConfig(
                connector_type="git-repo",
                endpoint=tmpdir,
                extra={"domain": "sales"},
            ))
        )
        state.router.register_connector("sales", connector)
        state.router.register_connector("delivery", connector)
        state.reconciliation.register_source(
            "git-sales", "sales", connector, max_age="24h"
        )
        state._connectors.append(connector)

        client = TestClient(app)
        yield client, state


class TestWorkflow1_SimpleContextRequest:
    """W1: Consultant asks 'Henderson project status'."""

    def test_create_session_and_request_context(self, client_with_repo):
        client, state = client_with_repo

        # Create session
        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
            "workspace_scope": "clients/henderson",
        })
        assert resp.status_code == 200
        session = resp.json()
        assert session["active"] is True

        # Request context
        resp = client.post("/context/request", json={
            "session_id": session["session_id"],
            "intent": "What's the Henderson client status?",
            "token_budget": 8000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["units"]) > 0
        assert data["total_tokens"] > 0
        assert data["latency_ms"] > 0

        # Verify Henderson content was found
        all_content = " ".join(u["content"] for u in data["units"])
        assert "henderson" in all_content.lower()


class TestWorkflow3_ThreeTierApproval:
    """W3: Agent drafts a proposal and requests email delivery."""

    def test_t1_autonomous_action(self, client_with_repo):
        """T1: read is autonomous — no approval needed."""
        client, state = client_with_repo

        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
        })
        session_id = resp.json()["session_id"]

        resp = client.post("/actions/submit", json={
            "session_id": session_id,
            "action_type": "read",
            "resource": "clients/henderson/profile.md",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "autonomous"
        assert data["status"] == "autonomous"

    def test_t2_soft_approval_flow(self, client_with_repo):
        """T2: write requires soft approval."""
        client, state = client_with_repo

        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
        })
        session_id = resp.json()["session_id"]

        # Submit write action
        resp = client.post("/actions/submit", json={
            "session_id": session_id,
            "action_type": "write",
            "resource": "clients/henderson/notes.md",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "soft-approval"
        assert data["status"] == "pending_approval"
        approval_id = data["approval_id"]

        # User approves
        resp = client.post(f"/approvals/{approval_id}/resolve", json={
            "approved": True,
        })
        assert resp.status_code == 200
        assert resp.json()["approved"] is True

    def test_t3_strong_approval_flow(self, client_with_repo):
        """T3: send_email requires strong approval with OTP."""
        client, state = client_with_repo

        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
        })
        session_id = resp.json()["session_id"]

        # Submit email action
        resp = client.post("/actions/submit", json={
            "session_id": session_id,
            "action_type": "send_email",
            "resource": "client@external.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "strong-approval"
        approval_id = data["approval_id"]

        # Get OTP from out-of-band channel (simulated)
        otp = state.permission_engine.get_otp_from_channel("demo-user", approval_id)
        assert otp is not None

        # Verify with correct OTP
        resp = client.post(f"/approvals/{approval_id}/resolve", json={
            "approved": True,
            "verification_code": otp,
        })
        assert resp.status_code == 200
        assert resp.json()["approved"] is True

    def test_t3_wrong_code_denied(self, client_with_repo):
        """T3: wrong OTP is denied."""
        client, state = client_with_repo

        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
        })
        session_id = resp.json()["session_id"]

        resp = client.post("/actions/submit", json={
            "session_id": session_id,
            "action_type": "send_email",
            "resource": "client@external.com",
        })
        approval_id = resp.json()["approval_id"]

        # Try wrong code
        resp = client.post(f"/approvals/{approval_id}/resolve", json={
            "approved": True,
            "verification_code": "WRONG",
        })
        assert resp.status_code == 200
        assert resp.json()["approved"] is False

    def test_excluded_action_denied(self, client_with_repo):
        """Excluded: commit_pricing not in agent profile."""
        client, state = client_with_repo

        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
        })
        session_id = resp.json()["session_id"]

        resp = client.post("/actions/submit", json={
            "session_id": session_id,
            "action_type": "commit_pricing",
            "resource": "henderson-proposal",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "excluded"
        assert data["status"] == "excluded"
        assert "manual" in data["message"].lower()


class TestKillSwitch:
    """Kill switches — instant session termination."""

    def test_kill_session_blocks_requests(self, client_with_repo):
        client, state = client_with_repo

        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
        })
        session_id = resp.json()["session_id"]

        # Kill the session
        resp = client.delete(f"/sessions/{session_id}")
        assert resp.status_code == 200

        # Context request should now return empty
        resp = client.post("/context/request", json={
            "session_id": session_id,
            "intent": "Henderson status",
        })
        data = resp.json()
        assert len(data["units"]) == 0

    def test_kill_all_sessions(self, client_with_repo):
        client, state = client_with_repo

        # Create two sessions
        client.post("/sessions", json={
            "user_id": "demo-user", "agent_id": "a1", "role": "sales-rep"
        })
        client.post("/sessions", json={
            "user_id": "demo-user", "agent_id": "a2", "role": "sales-rep"
        })

        # Kill all
        resp = client.delete("/sessions", params={"user_id": "demo-user"})
        assert resp.status_code == 200
        assert resp.json()["killed"] == 2


class TestAudit:
    """Audit log — every interaction is recorded."""

    def test_context_requests_logged(self, client_with_repo):
        client, state = client_with_repo

        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
        })
        session_id = resp.json()["session_id"]

        client.post("/context/request", json={
            "session_id": session_id,
            "intent": "Henderson client status",
        })

        # Query audit
        resp = client.post("/audit/events", json={
            "event_type": "context_request",
        })
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1

    def test_action_submissions_logged(self, client_with_repo):
        client, state = client_with_repo

        resp = client.post("/sessions", json={
            "user_id": "demo-user",
            "agent_id": "agent-1",
            "role": "sales-rep",
        })
        session_id = resp.json()["session_id"]

        client.post("/actions/submit", json={
            "session_id": session_id,
            "action_type": "read",
            "resource": "clients/henderson/profile.md",
        })

        resp = client.get("/audit/count", params={"event_type": "action_executed"})
        assert resp.json()["count"] >= 1


class TestHealth:
    """Health endpoints."""

    def test_health_check(self, client_with_repo):
        client, _ = client_with_repo
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "0.1.0"
        assert data["uptime_seconds"] > 0

    def test_source_health(self, client_with_repo):
        client, _ = client_with_repo
        resp = client.get("/health/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert "git-sales" in data
        assert data["git-sales"]["health"] == "healthy"
