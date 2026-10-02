"""PC-C8 §9 — the Stage-0 project card's own DSAR surface.

The card embeds ``quoted_text``: a **derived copy** of interview personal data that this slice
creates. The B2 precedent is that a new personal-data surface lands with its purge path, so the
card gets three things here and nothing is deferred:

1. **Reverse dependency bindings at persist.** :func:`stage0_card_subject_bindings` enumerates
   *every statement id whose quote the card body embeds* as an ``agent_artifact_subject`` row
   (``binding_kind='derived'``), beside the existing client-level ``context`` binding. Per-source,
   not per-client: "which card artifacts quote statement X" becomes one indexed query
   (:func:`card_artifacts_quoting_statement`) instead of a body scan.
2. **Erasure.** :class:`Stage0StatementEraser` composes the reverse bindings with the *existing* B2
   machinery — it resolves the affected artifact keys and hands them to
   :meth:`~clue_api.agent_turn_wiring.AgentPrivacyService.erase_artifacts`, which is the same
   tombstone → ``mark_erased`` → ``purge_erased_artifacts`` → turn-event → workspace-purge path
   ``erase_subject`` has always run. No new erasure semantics are invented here.
3. **No resurrection, and honest recompilation.** The artifact *row* survives as audit; the body is
   gone, and the tombstone makes a content-addressed re-persist of the identical bytes a loud
   refusal. A later compile excludes the statement by construction — the shared evidence reader
   returns ``ExcludedEvidence`` for a purged artifact — and the card surfaces
   ``excluded_statement_evidence_missing`` rather than silently shrinking.

**What erasing one statement takes with it.** A statement's evidence is not private to it: the
captured artifact is the whole client turn, and its siblings quote spans of the same body. Erasing
the bytes therefore erases every sibling's words too, so the eraser deliberately widens to the
sibling set before collecting dependent cards. Erasing less would leave a card on disk quoting an
erased turn.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import PrivacyEraseResult
from clue_api.agent_turn_wiring import AgentPrivacyService
from clue_db import ConnFactory, transaction
from clue_projections.production_context import Stage0ProjectStateCard
from clue_projections.stage0 import Stage0ProjectCard

if TYPE_CHECKING:  # the refresher's module imports this one's neighbours; only the type is needed
    from clue_api.project_library_refresh import ProjectLibraryRefresher

#: The ``agent_artifact_subject.binding_kind`` a card carries for each statement it quotes. It is
#: ``derived`` (one of the six values the table's CHECK admits) because the card holds a *derived
#: copy* of the statement's words — the ``conversation`` capture and the client-level ``context``
#: binding already mean something else on the same table.
STAGE0_CARD_QUOTE_BINDING_KIND = "derived"

#: The reason stamped on the tombstone + privacy event when a statement's evidence is erased.
STAGE0_STATEMENT_ERASURE_REASON = "dsar_stage0_statement_erasure"


class Stage0StatementNotFound(LookupError):
    """No such statement **in this workspace**.

    Fail-closed and indistinguishable from a truly absent id: a cross-workspace statement id gets
    exactly this, so erasure cannot be used to probe another tenant's interview.
    """


class Stage0StatementErasure(BaseModel):
    """What one statement erasure actually reached.

    ``card_artifact_keys`` is the reverse-binding answer (the dependent card bodies);
    ``evidence_artifact_key`` is the captured turn the quote was sliced from. Both are inside
    ``erase.tombstoned_artifact_keys`` — they are reported separately so an auditor can see the
    dependency edge the bindings made queryable, not just the union that was purged.

    ``affected_statement_ids`` is every statement that **lost its words**, the requested one
    included. It is deliberately not "siblings": the target is affected too, and a DSAR record that
    named only the collateral would understate what the erasure did.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    statement_id: UUID
    affected_statement_ids: tuple[UUID, ...]
    evidence_artifact_key: str
    card_artifact_keys: tuple[str, ...]
    erase: PrivacyEraseResult


def stage0_card_subject_bindings(
    *,
    card: Stage0ProjectCard | Stage0ProjectStateCard,
    base: Sequence[tuple[UUID, str]] = (),
) -> tuple[tuple[UUID, str], ...]:
    """The subject bindings a persisted card body must carry (spec §9, "reverse bindings").

    ``base`` is whatever the persisting surface already binds — the client-level ``context``
    binding, which stays: the card is *also* personal data about the client. Appended to it is one
    ``derived`` binding per statement whose quote the body embeds, read straight off the compiled
    card rather than off the caller's idea of what went in, so the bindings can never describe a
    different card than the one being persisted.

    Only ``current_effective_statements`` are bound because only their words are in the body;
    a statement the size policy dropped is named nowhere in the bytes and binding it would claim a
    dependency that does not exist. ``persist_body`` sorts and de-duplicates, so the order here is
    not load-bearing.
    """

    bindings = list(base)
    bindings.extend(
        (UUID(entry.statement_id), STAGE0_CARD_QUOTE_BINDING_KIND)
        for entry in card.interview.current_effective_statements
    )
    return tuple(bindings)


async def card_artifacts_quoting_statement(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    statement_id: UUID,
) -> tuple[str, ...]:
    """Which card artifacts quote statement X — the direct query the bindings exist for.

    Served by ``agent_artifact_subject_lookup`` (``workspace_id, subject_entity_id, artifact_key``),
    so this stays an index read no matter how many cards a long conversation persisted.
    """

    rows = await conn.execute(
        text(
            "SELECT artifact_key FROM agent_artifact_subject "
            "WHERE workspace_id = :workspace AND subject_entity_id = :subject "
            "AND binding_kind = :kind ORDER BY artifact_key"
        ),
        {
            "workspace": workspace_id,
            "subject": statement_id,
            "kind": STAGE0_CARD_QUOTE_BINDING_KIND,
        },
    )
    return tuple(rows.scalars())


class Stage0StatementEraser:
    """Erase one interview statement's words everywhere this slice copied them.

    A thin composition, not a second erasure engine: it resolves *which* artifact keys an erasure
    reaches (the captured evidence + every dependent card, found through the reverse bindings) and
    delegates the act itself to :class:`AgentPrivacyService`.
    """

    def __init__(
        self,
        *,
        privacy: AgentPrivacyService,
        conn_factory: ConnFactory = transaction,
        library: ProjectLibraryRefresher | None = None,
    ) -> None:
        self._privacy = privacy
        self._conn_factory = conn_factory
        self._library = library

    async def erase_statement(
        self,
        *,
        workspace_id: str,
        statement_id: UUID,
        reason_code: str = STAGE0_STATEMENT_ERASURE_REASON,
    ) -> Stage0StatementErasure:
        async with self._conn_factory() as conn:
            evidence_key, project_id = await self._evidence_key(
                conn, workspace_id=workspace_id, statement_id=statement_id
            )
            affected = await self._statements_citing(
                conn, workspace_id=workspace_id, artifact_key=evidence_key
            )
            card_keys: set[str] = set()
            for affected_id in affected:
                card_keys.update(
                    await card_artifacts_quoting_statement(
                        conn, workspace_id=workspace_id, statement_id=affected_id
                    )
                )

        erase = await self._privacy.erase_artifacts(
            workspace_id=workspace_id,
            subject_entity_id=statement_id,
            artifact_keys=(evidence_key, *sorted(card_keys)),
            reason_code=reason_code,
        )
        # The project library quotes these words in ``decisions.md``, and it is a *rendering*, not
        # an artifact — nothing tombstones it, so it has to be rewritten. Forced, because erasure
        # moves no row the library's digest hashes: the ``volunteered_statement`` row survives as
        # audit and only its evidence is gone, so an unforced refresh would find nothing to do.
        if self._library is not None and project_id is not None:
            await self._library.refresh(
                workspace_id=workspace_id, project_id=project_id, force=True
            )
        return Stage0StatementErasure(
            workspace_id=workspace_id,
            statement_id=statement_id,
            affected_statement_ids=affected,
            evidence_artifact_key=evidence_key,
            card_artifact_keys=tuple(sorted(card_keys)),
            erase=erase,
        )

    @staticmethod
    async def _evidence_key(
        conn: AsyncConnection, *, workspace_id: str, statement_id: UUID
    ) -> tuple[str, str | None]:
        """The captured turn this statement's quote was sliced from, and its project.

        The project comes along because the erasure has one more rendering to correct than the
        artifact set describes: this project's library quotes the statement in ``decisions.md``.
        It is nullable on the row (a client-level statement belongs to no project) and then there
        is no project library to refresh.
        """

        row = (
            await conn.execute(
                text(
                    "SELECT i.artifact_key, s.project_id FROM volunteered_statement s "
                    "JOIN onboarding_input i ON i.id = s.onboarding_input_id "
                    "WHERE s.id = :statement AND s.workspace_id = :workspace"
                ),
                {"statement": statement_id, "workspace": workspace_id},
            )
        ).first()
        if row is None:
            raise Stage0StatementNotFound(
                "no interview statement with that id exists in this workspace"
            )
        return str(row[0]), None if row[1] is None else str(row[1])

    @staticmethod
    async def _statements_citing(
        conn: AsyncConnection, *, workspace_id: str, artifact_key: str
    ) -> tuple[UUID, ...]:
        """Every statement whose words live in the same captured body — the erasure blast radius.

        Includes the requested statement itself (it cites that body too), which is why the result
        is named ``affected``, not "siblings".
        """

        rows = await conn.execute(
            text(
                "SELECT s.id FROM volunteered_statement s "
                "JOIN onboarding_input i ON i.id = s.onboarding_input_id "
                "WHERE s.workspace_id = :workspace AND i.artifact_key = :key ORDER BY s.id"
            ),
            {"workspace": workspace_id, "key": artifact_key},
        )
        return tuple(rows.scalars())


__all__ = [
    "STAGE0_CARD_QUOTE_BINDING_KIND",
    "STAGE0_STATEMENT_ERASURE_REASON",
    "Stage0StatementEraser",
    "Stage0StatementErasure",
    "Stage0StatementNotFound",
    "card_artifacts_quoting_statement",
    "stage0_card_subject_bindings",
]
