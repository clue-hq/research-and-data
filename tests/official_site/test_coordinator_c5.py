"""Provider-free C5 coordinator dependency and identity guards."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from clue_research.official_site import ConcurrentCrawlCoordinator, CrawlLease, CrawlPhase

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_coordinator_does_not_import_or_branch_on_provider_packages() -> None:
    source = (
        _REPO_ROOT / "subsystems/research/clue_research/official_site/coordinator.py"
    ).read_text()
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(
        provider in imported for imported in imports for provider in ("firecrawl", "scrapling")
    )
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "firecrawl" not in literals
    assert "scrapling" not in literals


def test_operation_key_is_stable_within_generation_and_fenced_across_generations() -> None:
    page_id = uuid4()
    run_id = uuid4()
    lease = CrawlLease(
        workspace_id="workspace",
        crawl_run_id=run_id,
        page_id=page_id,
        worker_id="worker-a",
        lease_generation=3,
        phase=CrawlPhase.FAST,
        fetch_key="https://example.com/",
        requested_url="https://example.com/",
        host="example.com",
        graph_depth=0,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    replay = lease.model_copy(update={"worker_id": "worker-a"})
    replacement = lease.model_copy(update={"worker_id": "worker-b", "lease_generation": 4})

    assert ConcurrentCrawlCoordinator.operation_key(lease) == (
        ConcurrentCrawlCoordinator.operation_key(replay)
    )
    assert ConcurrentCrawlCoordinator.operation_key(lease) != (
        ConcurrentCrawlCoordinator.operation_key(replacement)
    )
