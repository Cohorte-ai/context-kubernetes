"""CxRI Connector: Git Repository.

The most fundamental context source. Organizational knowledge stored as
files in git repositories — versioned, branched, diffable, attributable.

Implements the six CxRI operations:
  connect(φ)        → clone or open the repo
  query(conn, q)    → search files by content/path matching
  read(conn, path)  → read a file, return as ContextUnit
  write(conn, path) → write a file, commit with attribution
  subscribe(conn)   → watch for changes via polling (webhook in production)
  health(conn)      → check repo accessibility
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from git import Repo, InvalidGitRepositoryError, GitCommandError

from context_kubernetes.cxri.interface import (
    ChangeEvent,
    ConnectionConfig,
    CxRIConnector,
    HealthStatus,
    WriteResult,
)
from context_kubernetes.models import ContextUnit, ContextUnitMetadata, ContentType


# File extensions we treat as context (readable text)
CONTEXT_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".json", ".csv", ".rst", ".org"}


class GitConnector(CxRIConnector):
    """
    CxRI connector for git repositories.

    Reads files from a git repo, converts them to ContextUnits with
    full metadata (author, timestamp, version=commit hash). Writes
    create new commits with attribution.

    Config:
        endpoint: path to local repo OR remote URL to clone
        scope: subdirectory within the repo to scope queries (optional)
        extra:
            branch: branch name (default: main)
            clone_to: local path to clone into (for remote repos)
            domain: context domain name for metadata
    """

    connector_type = "git-repo"

    def __init__(self) -> None:
        self._repo: Repo | None = None
        self._repo_path: Path | None = None
        self._scope: str = ""
        self._branch: str = "main"
        self._domain: str = "default"
        self._last_commit: str = ""

    async def connect(self, config: ConnectionConfig) -> None:
        """Open a local repo or clone a remote one."""
        self._scope = config.scope
        self._branch = config.extra.get("branch", "main")
        self._domain = config.extra.get("domain", "default")

        endpoint = config.endpoint

        # Determine if local or remote
        if os.path.isdir(endpoint):
            try:
                self._repo = Repo(endpoint)
                self._repo_path = Path(endpoint)
            except InvalidGitRepositoryError:
                raise ConnectionError(f"Not a git repository: {endpoint}")
        else:
            # Remote — clone to specified or temp path
            clone_to = config.extra.get("clone_to", f"/tmp/cxri-git-{hash(endpoint) % 100000}")
            if os.path.isdir(clone_to):
                try:
                    self._repo = Repo(clone_to)
                    # Pull latest
                    self._repo.remotes.origin.pull(self._branch)
                except Exception:
                    # Re-clone if corrupted
                    import shutil
                    shutil.rmtree(clone_to, ignore_errors=True)
                    self._repo = Repo.clone_from(endpoint, clone_to, branch=self._branch)
            else:
                self._repo = Repo.clone_from(endpoint, clone_to, branch=self._branch)
            self._repo_path = Path(clone_to)

        # Checkout the right branch
        try:
            self._repo.git.checkout(self._branch)
        except GitCommandError:
            pass  # Already on the branch

        # Record current HEAD for change detection
        self._last_commit = self._repo.head.commit.hexsha

    async def query(self, intent: str, **filters: Any) -> list[ContextUnit]:
        """
        Search repository files by content and path matching.

        For now uses simple substring matching. The Context Router handles
        semantic ranking — this connector returns candidate matches.
        """
        self._ensure_connected()
        assert self._repo is not None and self._repo_path is not None

        results: list[ContextUnit] = []
        search_terms = intent.lower().split()
        scope_path = self._repo_path / self._scope if self._scope else self._repo_path

        for file_path in self._iter_context_files(scope_path):
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            # Score: how many search terms appear in the file content or path
            text_lower = content.lower()
            path_lower = str(file_path).lower()
            hits = sum(1 for term in search_terms if term in text_lower or term in path_lower)

            if hits > 0:
                rel_path = str(file_path.relative_to(self._repo_path))
                unit = self._file_to_context_unit(file_path, rel_path, content)
                results.append(unit)

        # Sort by relevance (number of term hits) — basic ranking
        # The Context Router will re-rank with multi-signal scoring
        results.sort(key=lambda u: sum(
            1 for term in search_terms
            if term in u.content.lower()
        ), reverse=True)

        max_results = filters.get("max_results", 50)
        return results[:max_results]

    async def read(self, path: str) -> ContextUnit | None:
        """Read a specific file by path within the repo."""
        self._ensure_connected()
        assert self._repo_path is not None

        file_path = self._repo_path / path
        if not file_path.is_file():
            return None

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return None

        return self._file_to_context_unit(file_path, path, content)

    async def write(self, path: str, content: str, message: str = "") -> WriteResult:
        """Write a file and commit with attribution."""
        self._ensure_connected()
        assert self._repo is not None and self._repo_path is not None

        file_path = self._repo_path / path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            file_path.write_text(content, encoding="utf-8")
            self._repo.index.add([path])

            if not message:
                message = f"Update {path}"

            commit = self._repo.index.commit(message)
            return WriteResult(
                success=True,
                version=commit.hexsha,
                message=f"Committed: {message}",
            )
        except Exception as e:
            return WriteResult(success=False, message=str(e))

    async def subscribe(self, path_pattern: str) -> AsyncIterator[ChangeEvent]:
        """
        Watch for changes by polling for new commits.

        In production, this would be driven by git webhooks.
        For the prototype, we poll every 5 seconds.
        """
        self._ensure_connected()
        assert self._repo is not None

        while True:
            await asyncio.sleep(5)

            try:
                # Pull latest (for remote repos)
                if self._repo.remotes:
                    self._repo.remotes.origin.pull(self._branch)
            except Exception:
                pass

            current_head = self._repo.head.commit.hexsha
            if current_head != self._last_commit:
                # Find changed files between last known commit and current HEAD
                try:
                    diff = self._repo.commit(self._last_commit).diff(current_head)
                    for change in diff:
                        change_type = "modified"
                        file_path = change.b_path or change.a_path
                        if change.new_file:
                            change_type = "created"
                        elif change.deleted_file:
                            change_type = "deleted"

                        if not path_pattern or self._matches_pattern(file_path, path_pattern):
                            yield ChangeEvent(
                                path=file_path,
                                change_type=change_type,
                                timestamp=time.time(),
                                new_version=current_head,
                            )
                except Exception:
                    # If diff fails, yield a generic change event
                    yield ChangeEvent(
                        path=path_pattern or "*",
                        change_type="modified",
                        timestamp=time.time(),
                        new_version=current_head,
                    )

                self._last_commit = current_head

    async def health(self) -> HealthStatus:
        """Check repository accessibility."""
        if self._repo is None:
            return HealthStatus.DISCONNECTED

        try:
            # Can we read HEAD?
            _ = self._repo.head.commit.hexsha
            return HealthStatus.HEALTHY
        except Exception:
            return HealthStatus.DEGRADED

    async def disconnect(self) -> None:
        """Clean up."""
        self._repo = None
        self._repo_path = None

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._repo is None:
            raise ConnectionError("Not connected. Call connect() first.")

    def _iter_context_files(self, root: Path) -> list[Path]:
        """List all readable context files under root."""
        files = []
        if not root.is_dir():
            return files

        for file_path in root.rglob("*"):
            if file_path.is_file() and file_path.suffix in CONTEXT_EXTENSIONS:
                # Skip hidden files and .git
                parts = file_path.relative_to(root).parts
                if not any(p.startswith(".") for p in parts):
                    files.append(file_path)
        return files

    def _file_to_context_unit(
        self, file_path: Path, rel_path: str, content: str
    ) -> ContextUnit:
        """Convert a git-tracked file into a ContextUnit."""
        assert self._repo is not None

        # Get git metadata for this file
        author = "unknown"
        timestamp = datetime.now(timezone.utc)
        version = ""

        try:
            commits = list(self._repo.iter_commits(paths=rel_path, max_count=1))
            if commits:
                last_commit = commits[0]
                author = str(last_commit.author)
                timestamp = datetime.fromtimestamp(
                    last_commit.committed_date, tz=timezone.utc
                )
                version = last_commit.hexsha[:12]
        except Exception:
            version = self._last_commit[:12] if self._last_commit else "unknown"

        return ContextUnit(
            content=content,
            content_type=ContentType.UNSTRUCTURED,
            metadata=ContextUnitMetadata(
                author=author,
                timestamp=timestamp,
                domain=self._domain,
                source=f"git:{rel_path}",
                entities=self._extract_entities_from_path(rel_path),
            ),
            version=version,
            authorized_roles=set(),  # populated by Permission Engine at query time
        )

    @staticmethod
    def _extract_entities_from_path(path: str) -> list[str]:
        """Extract entity hints from file path structure."""
        parts = Path(path).parts
        entities = []
        for part in parts:
            # Skip generic directory names
            if part not in ("clients", "projects", "docs", "context", "team", "sales",
                           "hr", "legal", "finance", "operations", "knowledge"):
                clean = part.replace(".md", "").replace(".yaml", "").replace(".txt", "")
                clean = clean.replace("-", " ").replace("_", " ")
                if clean and len(clean) > 1:
                    entities.append(clean)
        return entities

    @staticmethod
    def _matches_pattern(path: str, pattern: str) -> bool:
        """Simple glob-like pattern matching."""
        import fnmatch
        return fnmatch.fnmatch(path, pattern)
