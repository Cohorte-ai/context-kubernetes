"""Tests for the Git CxRI connector."""

import os
import tempfile
from pathlib import Path

import pytest
from git import Repo

from context_kubernetes.cxri.connectors.git_connector import GitConnector
from context_kubernetes.cxri.interface import ConnectionConfig, HealthStatus


@pytest.fixture
def sample_repo():
    """Create a temporary git repo with sample context files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)

        # Create context files
        clients = Path(tmpdir) / "clients" / "henderson"
        clients.mkdir(parents=True)

        (clients / "profile.md").write_text(
            "# Henderson Corp\n\nIndustry: Manufacturing\nContact: Sarah Henderson\n"
            "Last meeting: March 15, 2026\nStatus: Active client\n"
        )
        (clients / "communications.md").write_text(
            "## March 15 Meeting Notes\n\n"
            "Sarah mentioned budget concerns for Q2.\n"
            "Delivery timeline discussed: 8 weeks preferred.\n"
        )

        proposals = Path(tmpdir) / "proposals"
        proposals.mkdir()
        (proposals / "henderson-q2.md").write_text(
            "# Henderson Q2 Proposal\n\nValue: €180,000\nTimeline: 8 weeks\n"
        )

        pipeline = Path(tmpdir) / "pipeline.md"
        pipeline.write_text("# Sales Pipeline\n\n| Client | Stage | Value |\n| Henderson | Proposal | €180K |\n")

        repo.index.add([
            "clients/henderson/profile.md",
            "clients/henderson/communications.md",
            "proposals/henderson-q2.md",
            "pipeline.md",
        ])
        repo.index.commit("Initial context structure")

        yield tmpdir, repo


class TestGitConnector:
    @pytest.mark.asyncio
    async def test_connect_local(self, sample_repo):
        tmpdir, _ = sample_repo
        connector = GitConnector()
        config = ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        )
        await connector.connect(config)
        status = await connector.health()
        assert status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_read_file(self, sample_repo):
        tmpdir, _ = sample_repo
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))

        unit = await connector.read("clients/henderson/profile.md")
        assert unit is not None
        assert "Henderson Corp" in unit.content
        assert unit.metadata.domain == "sales"
        assert unit.metadata.source == "git:clients/henderson/profile.md"
        assert len(unit.version) > 0  # should have commit hash

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, sample_repo):
        tmpdir, _ = sample_repo
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))

        unit = await connector.read("does/not/exist.md")
        assert unit is None

    @pytest.mark.asyncio
    async def test_query_by_content(self, sample_repo):
        tmpdir, _ = sample_repo
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))

        results = await connector.query("henderson budget")
        assert len(results) > 0
        # The communications file mentions "budget" — should rank high
        content_texts = [u.content for u in results]
        assert any("budget" in c.lower() for c in content_texts)

    @pytest.mark.asyncio
    async def test_query_scoped(self, sample_repo):
        tmpdir, _ = sample_repo
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            scope="clients",
            extra={"domain": "sales"},
        ))

        results = await connector.query("henderson")
        # Should only find files under clients/
        for unit in results:
            assert "clients/" in unit.metadata.source

    @pytest.mark.asyncio
    async def test_write_and_read_back(self, sample_repo):
        tmpdir, _ = sample_repo
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))

        result = await connector.write(
            "clients/henderson/notes.md",
            "# Meeting Notes\n\nFollowed up on Q2 timeline.\n",
            message="Add Henderson meeting notes",
        )
        assert result.success
        assert len(result.version) > 0

        unit = await connector.read("clients/henderson/notes.md")
        assert unit is not None
        assert "Q2 timeline" in unit.content

    @pytest.mark.asyncio
    async def test_entity_extraction_from_path(self, sample_repo):
        tmpdir, _ = sample_repo
        connector = GitConnector()
        await connector.connect(ConnectionConfig(
            connector_type="git-repo",
            endpoint=tmpdir,
            extra={"domain": "sales"},
        ))

        unit = await connector.read("clients/henderson/profile.md")
        assert unit is not None
        assert "henderson" in unit.metadata.entities

    @pytest.mark.asyncio
    async def test_health_disconnected(self):
        connector = GitConnector()
        status = await connector.health()
        assert status == HealthStatus.DISCONNECTED
