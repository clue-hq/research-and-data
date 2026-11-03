"""Research trial (recipe 32+): the researcher's markdown dossier, saved as committed versions.

The agent edits /outputs/dossier.md and /outputs/dossier-index.json freely; a version exists only
when it calls commit_dossier. Each commit is a stored file plus an ``artifact_reference`` row keyed
``<job>:<version>``, the same way the JSON dossier stores its snapshots, so no migration is needed.
The last commit of a run is published. Code checks the dossier's shape only (headings, finding
numbers, cited sources exist in this job's evidence, index anchors exist); it never judges the
research and never checks quoted words (founder ruling 2026-11-03).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_evidence import list_sources
from clue_api.quality_research_artifacts import ResearchArtifacts
from clue_obs import get_logger
from clue_storage import StorageBackend, read_verified_artifact, retain_artifact

log = get_logger("arv2.markdown_dossier")

DOSSIER_PATH = "outputs/dossier.md"
INDEX_PATH = "outputs/dossier-index.json"
COMMIT_KIND = "research_md_dossier"
PUBLISHED_KIND = "research_md_dossier_published"
HEADINGS = (
    "Verdict",
    "What they do",
    "What changed recently",
    "How the work is done today",
    "What they use now and its problems",
    "How the seller could prove itself here",
    "Who decides and who to approach first",
    "What could stop a deal",
    "Open questions",
)
VERDICTS = {"pursue", "pursue_with_conditions", "deprioritise"}
_FINDING = re.compile(r"^### (F\d{3,}) · \S", re.MULTILINE)
_SOURCE = re.compile(r"\[(/evidence/[^\]\s]+)\]")


def uses_markdown_dossier(scope: JobScope) -> bool:
    return (
        scope.catalog_version == "v4"
        and not scope.person_subject_id
        and int((scope.input_refs or {}).get("quality_recipe_version", 5)) >= 32
    )


def check(dossier: str, index_raw: str | None, source_paths: set[str]) -> list[str]:
    """Contract problems only, each phrased so the agent can fix it."""
    problems: list[str] = []
    headings = [h.strip() for h in re.findall(r"^## (.+)$", dossier, re.MULTILINE)]
    missing = [h for h in HEADINGS if h not in headings]
    if missing:
        problems.append(
            "Missing headings (use them word for word as '## <heading>'): " + ", ".join(missing)
        )
    elif [h for h in headings if h in HEADINGS] != list(HEADINGS):
        problems.append("Put the nine headings in the order the skill gives.")
    ids = _FINDING.findall(dossier)
    if not ids:
        problems.append("No findings. Each finding starts '### F001 · <title>'.")
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        problems.append("Finding numbers used more than once: " + ", ".join(repeated))
    blocks = re.split(r"^(?=### F\d{3,} · )", dossier, flags=re.MULTILINE)
    for block in blocks:
        match = _FINDING.match(block)
        if not match:
            continue
        body = re.split(r"^## ", block, maxsplit=1, flags=re.MULTILINE)[0]
        cited = _SOURCE.findall(body)
        if not cited:
            problems.append(f"{match.group(1)} cites no source; add its [/evidence/...] path.")
        unknown = sorted(set(cited) - source_paths)
        if unknown:
            problems.append(
                f"{match.group(1)} cites paths not in this job's evidence index: "
                + ", ".join(unknown)
            )
    if index_raw is None:
        problems.append(f"/{INDEX_PATH} is missing.")
        return problems
    try:
        index = json.loads(index_raw)
    except ValueError as exc:
        problems.append(f"/{INDEX_PATH} is not valid JSON: {exc}")
        return problems
    if not isinstance(index, dict):
        problems.append(f"/{INDEX_PATH} must be a JSON object.")
        return problems
    if index.get("verdict") not in VERDICTS:
        problems.append("Index verdict must be one of: " + ", ".join(sorted(VERDICTS)))
    if not str(index.get("verdict_reason") or "").strip():
        problems.append("Index verdict_reason is empty.")
    known = set(ids)
    referenced: list[str] = []
    for row in index.get("icp") or []:
        if isinstance(row, dict):
            if row.get("status") not in {"met", "unmet", "unknown"}:
                problems.append(f"ICP status must be met, unmet or unknown: {row.get('criterion')}")
            referenced += list(row.get("findings") or [])
    for key in ("incumbent", "size", "region"):
        if isinstance(index.get(key), dict):
            referenced += list(index[key].get("findings") or [])
    for row in index.get("key_facts") or []:
        if isinstance(row, dict):
            referenced.append(row.get("finding"))
    if len(index.get("key_facts") or []) > 10:
        problems.append("List at most ten key facts.")
    dangling = sorted({str(r) for r in referenced if r not in known})
    if dangling:
        problems.append("Index points at findings not in the dossier: " + ", ".join(dangling))
    return problems


@asynccontextmanager
async def _sink(
    conn: AsyncConnection, storage: StorageBackend, scope: JobScope, context_id: UUID
) -> AsyncIterator[ResearchArtifacts]:
    @asynccontextmanager
    async def connections() -> AsyncIterator[AsyncConnection]:
        yield conn

    sink = ResearchArtifacts(storage=storage, conn_factory=connections)
    sink.scope, sink.context_id = scope, context_id
    yield sink


async def latest_commit(
    conn: AsyncConnection, storage: StorageBackend, scope: JobScope
) -> dict[str, Any] | None:
    key = (
        await conn.execute(
            text("""SELECT storage_key FROM artifact_reference
              WHERE workspace_id=:ws AND reference_kind=:kind AND reference_id LIKE :prefix
              ORDER BY reference_id DESC LIMIT 1"""),
            {"ws": scope.workspace_id, "kind": COMMIT_KIND, "prefix": f"{scope.job_id}:%"},
        )
    ).scalar_one_or_none()
    if key is None:
        return None
    _, raw = await read_verified_artifact(
        conn, storage, workspace_id=scope.workspace_id, storage_key=key
    )
    return {**json.loads(raw), "artifact_key": key}


async def commit(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    execution_id: UUID,
    *,
    message: str,
    dossier: str,
    index_raw: str | None,
) -> dict[str, Any]:
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"research-md-dossier:{scope.workspace_id}:{scope.job_id}"},
    )
    authority = await resolve_authority(conn, scope, execution_id)
    inventory = await list_sources(conn, authority.grant, limit=0)
    paths = {r["path"] for r in inventory["sources"] if r.get("available") and r.get("path")}
    problems = check(dossier, index_raw, paths)
    if not message.strip():
        problems.append("Give the commit a one-line message saying what changed and why.")
    if problems:
        return {"committed": False, "problems": problems}
    parent = await latest_commit(conn, storage, scope)
    if parent and parent["dossier"] == dossier and parent["index_raw"] == index_raw:
        return {
            "committed": False,
            "problems": [f"Nothing changed since version {parent['version']}."],
        }
    version = (parent["version"] + 1) if parent else 1
    body = {
        "job_id": str(scope.job_id),
        "context_id": str(authority.context_id),
        "subject_id": str(scope.account_id),
        "version": version,
        "parent_artifact_key": parent["artifact_key"] if parent else None,
        "message": message.strip(),
        "committed_at": datetime.now(UTC).isoformat(),
        "dossier": dossier,
        "index_raw": index_raw,
        "findings": _FINDING.findall(dossier),
        "cited_sources": sorted(set(_SOURCE.findall(dossier))),
    }
    async with _sink(conn, storage, scope, authority.context_id) as sink:
        ref = await sink.persist_body(
            workspace_id=scope.workspace_id,
            data=json.dumps(body, ensure_ascii=False, sort_keys=True).encode(),
            media_type="application/json",
        )
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=ref.artifact_key,
        reference_kind=COMMIT_KIND,
        reference_id=f"{scope.job_id}:{version:010d}",
    )
    log.info(
        "arv2.markdown_dossier.committed",
        job_id=str(scope.job_id),
        version=version,
        findings=len(body["findings"]),
        artifact_key=ref.artifact_key,
    )
    return {"committed": True, "version": version, "findings": len(body["findings"])}


async def publish(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    *,
    dossier: str | None,
    index_raw: str | None,
) -> dict[str, Any]:
    """Finish: the last commit must match the files as they are now, and becomes published."""
    latest = await latest_commit(conn, storage, scope)
    if latest is None:
        raise ValueError("No committed dossier. Commit /outputs/dossier.md, then finalize_turn.")
    if latest["dossier"] != dossier or latest["index_raw"] != index_raw:
        raise ValueError(
            "The dossier or its index changed after your last commit. Call commit_dossier with "
            "your final edits, then finalize_turn."
        )
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=latest["artifact_key"],
        reference_kind=PUBLISHED_KIND,
        reference_id=f"{scope.job_id}:{latest['version']:010d}",
    )
    return {
        "dossier": "markdown",
        "dossier_version": latest["version"],
        "dossier_artifact_key": latest["artifact_key"],
        "findings": len(latest["findings"]),
    }
