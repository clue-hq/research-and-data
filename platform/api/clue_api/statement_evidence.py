"""The artifact-backed implementation of the projection's ``StatementEvidenceReader`` port.

``volunteered_statement`` stores a quote as *offsets plus a sha256* into a captured onboarding
artifact and never the text, so "what did the client actually say?" is answered by slicing the
artifact body and verifying the span against that hash. The projection layer may not import
storage, so it declares the port (``clue_projections.stage0.StatementEvidenceReader``) and this
composition-root module owns the I/O.

**This is the DRY seam.** Both readers of interview evidence go through :func:`resolve_statement_
quotes`: the PC-C8 Stage-0 project card (via :class:`ArtifactStatementEvidenceReader`) and ICP
synthesis (``Stage0Trial._project_statements``). Two independent implementations of "slice the span
and check the hash" is exactly how the model's context and the synthesis prompt would start
disagreeing about what a statement says.

The two ways resolution can fail are deliberately **not** the same failure:

* the evidence artifact is **gone** — erased or tombstoned by DSAR, or its row purged — so the
  statement is excluded and reported as :class:`~clue_projections.stage0.ExcludedEvidence`. Erasing
  one conversation turn must never permanently disable synthesis or blank the whole card;
* the artifact is present but the span **does not hash to** the recorded quote, or its durable
  metadata disagrees with the row — that is corruption or tampering, and it raises. A
  cross-workspace artifact reference is a scoping violation, not an erasure: it raises too.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentArtifactReader, ArtifactRef
from clue_db import ConnFactory, transaction
from clue_projections.stage0 import (
    ExcludedEvidence,
    ExcludedEvidenceReason,
    ResolvedQuote,
)
from clue_research.stage0 import VolunteeredStatementRow
from clue_storage import ArtifactNotFound, get_artifact


class StatementEvidenceCorrupt(RuntimeError):
    """A statement's captured evidence exists but does not say what the row claims it says.

    Never raised for missing/erased evidence (that is an exclusion). This is the tamper/corruption
    signal, and it is loud on purpose: silently degrading it to an omission would let a mutated
    artifact quietly rewrite what the client is recorded as having said.
    """


class ArtifactStatementEvidenceReader:
    """The one production ``StatementEvidenceReader``.

    Holds no per-compile state: each call opens one connection and caches artifact bodies for the
    duration of that call only, so a card compiled after an erasure never serves bytes a previous
    compile happened to have read.
    """

    def __init__(
        self,
        *,
        artifacts: AgentArtifactReader,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._artifacts = artifacts
        self._conn_factory = conn_factory

    async def resolve_quote(
        self, *, workspace_id: str, statement: VolunteeredStatementRow
    ) -> ResolvedQuote | ExcludedEvidence:
        resolved = await self.resolve_quotes(workspace_id=workspace_id, statements=(statement,))
        return resolved[0]

    async def resolve_quotes(
        self, *, workspace_id: str, statements: Sequence[VolunteeredStatementRow]
    ) -> tuple[ResolvedQuote | ExcludedEvidence, ...]:
        if not statements:
            return ()
        async with self._conn_factory() as conn:
            return await resolve_statement_quotes(
                conn,
                self._artifacts,
                workspace_id=workspace_id,
                statements=statements,
            )


async def resolve_statement_quotes(
    conn: AsyncConnection,
    artifacts: AgentArtifactReader,
    *,
    workspace_id: str,
    statements: Sequence[VolunteeredStatementRow],
) -> tuple[ResolvedQuote | ExcludedEvidence, ...]:
    """Resolve every statement's quote from its captured artifact, in input order.

    One body read per distinct artifact (a captured turn usually backs several statements), and a
    missing artifact is remembered so a purged turn is not re-fetched once per statement.
    """

    bodies: dict[str, str] = {}
    missing: set[str] = set()
    resolved: list[ResolvedQuote | ExcludedEvidence] = []
    for row in statements:
        if row.artifact_key in missing:
            resolved.append(_excluded(row))
            continue
        body = bodies.get(row.artifact_key)
        if body is None:
            record = await get_artifact(conn, row.artifact_key)
            if record is not None and record.workspace_id != workspace_id:
                raise StatementEvidenceCorrupt(
                    f"interview statement {row.id} cites an artifact owned by another workspace"
                )
            if record is None:
                missing.add(row.artifact_key)
                resolved.append(_excluded(row))
                continue
            try:
                body = (
                    await artifacts.read(
                        ArtifactRef(
                            workspace_id=workspace_id,
                            artifact_key=row.artifact_key,
                            sha256=record.content_sha256,
                            media_type=record.media_type,
                            byte_count=record.size_bytes,
                        )
                    )
                ).decode()
            except ArtifactNotFound:
                # Erased or tombstoned evidence: honest-empty, never fatal.
                missing.add(row.artifact_key)
                resolved.append(_excluded(row))
                continue
            bodies[row.artifact_key] = body
        # Offsets are character offsets into the decoded body, matching how ``record_statement``
        # hashed the quote it was given; the sha check below is what proves that agreement.
        quote = body[row.quote_start : row.quote_end]
        if hashlib.sha256(quote.encode()).hexdigest() != row.quote_sha256:
            raise StatementEvidenceCorrupt(
                f"interview statement {row.id} does not match its captured evidence quote"
            )
        resolved.append(ResolvedQuote(statement_id=row.id, quote=quote))
    return tuple(resolved)


def _excluded(row: VolunteeredStatementRow) -> ExcludedEvidence:
    return ExcludedEvidence(
        statement_id=row.id,
        reason=ExcludedEvidenceReason.ARTIFACT_MISSING,
    )


__all__ = [
    "ArtifactStatementEvidenceReader",
    "StatementEvidenceCorrupt",
    "resolve_statement_quotes",
]
