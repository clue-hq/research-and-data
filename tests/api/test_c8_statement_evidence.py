"""PC-C8 task 1.1 — the artifact-backed ``StatementEvidenceReader`` and its DRY seam.

``volunteered_statement`` stores a quote as offsets plus a sha256 into a captured onboarding
artifact and *no text*, so every reader of interview evidence must slice the artifact and verify
the span. There is now exactly one implementation of that
(``clue_api.statement_evidence.resolve_statement_quotes``), and both readers go through it: ICP
synthesis (``Stage0Trial._project_statements``) and the Stage-0 project card (via
``ArtifactStatementEvidenceReader``). This suite pins:

* **verbatim quotes** (spec AC-4) — a compiled card's ``quoted_text`` is byte-identical to the
  artifact slice, not a paraphrase and not a hash;
* **the two failure species stay different** — erased/tombstoned evidence is an exclusion (erasing
  one turn must not disable synthesis or blank the card); a span that no longer hashes to its
  recorded quote, or an artifact owned by another workspace, raises;
* **the seam is genuinely shared** — synthesis and the card resolve the *same words* for the same
  statement, asserted by running both against one fixture. Two implementations of "slice and check
  the hash" is exactly how the model's context and the synthesis prompt start disagreeing;
* **determinism across fresh objects** (AC-8's process-restart half, approximated) — a card
  recompiled through independently constructed store/reader/policy objects has the same sha256, so
  the digest depends on durable state alone and not on in-process identity.

DB-backed; rollback-only transactions; skips without a reachable ``CLUE_DATABASE_URL``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.stage0_trial import (
    Stage0Trial,
    Stage0TrialPaths,
    Stage0TrialState,
)
from clue_api.statement_evidence import (
    ArtifactStatementEvidenceReader,
    StatementEvidenceCorrupt,
    resolve_statement_quotes,
)
from clue_core import AccountStatus, EntityId, OnboardingInputKind
from clue_db import db_lifespan
from clue_projections.stage0 import (
    STAGE0_CARD_POLICY_V1,
    ExcludedEvidence,
    ResolvedQuote,
    Stage0CardPolicy,
    compile_stage0_project_card,
)
from clue_research.identity import insert_account_entity
from clue_research.stage0 import (
    StatementRoute,
    read_statements,
    record_statement,
    submit_onboarding_input,
)
from clue_spine import create_brand, create_product, create_project, create_workspace
from clue_storage import FsStorage, mark_erased
from tests.db.conftest import _db_available, run_async

_ANSWER = (
    "We target neurosurgery practices in the US that run their own imaging, and the campaign "
    "should open with the practice administrators."
)
# The exact span the fixture records: a real substring of the captured body.
_QUOTE_START = 11
_QUOTE_END = 33
_QUOTE = _ANSWER[_QUOTE_START:_QUOTE_END]


@pytest.fixture
def stage0_db_available() -> bool:
    return _db_available()


def _state(slug: str) -> Stage0TrialState:
    session_id = uuid4()
    return Stage0TrialState(
        session_id=session_id,
        session_slug=slug,
        workspace_id=f"c8-ev-{session_id.hex[:8]}",
        brand_id=f"brand_{session_id.hex[:8]}",
        product_id=f"product_{session_id.hex[:8]}",
        project_id=f"project_{session_id.hex[:8]}",
        client_entity_id=uuid4(),
        client_kb_version=1,
        company_name="Aura AI",
        website="https://aura.invalid",
        product_name="Aura ABM",
        project_name="Aura Stage 0",
        thread_id=f"c8-ev-{session_id.hex}",
        created_at=datetime.now(UTC),
    )


async def _seed(
    conn: AsyncConnection,
    artifacts: DurableAgentArtifactStore,
    *,
    state: Stage0TrialState,
    recorded_quote: str = _QUOTE,
    quote_start: int = _QUOTE_START,
    quote_end: int = _QUOTE_END,
) -> Stage0TrialState:
    """One captured turn with one routed ``project_state`` statement, as a live turn writes it."""

    await create_workspace(conn, workspace_id=state.workspace_id, name="C8 evidence")
    brand = await create_brand(
        conn, workspace_id=state.workspace_id, name="Aura", brand_id=state.brand_id
    )
    product = await create_product(
        conn,
        workspace_id=state.workspace_id,
        brand_id=brand.brand_id,
        name="Aura ABM",
        product_id=state.product_id,
    )
    await create_project(
        conn,
        workspace_id=state.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        name="Aura Stage 0",
        project_id=state.project_id,
    )
    client = await insert_account_entity(
        conn,
        canonical_name="Aura AI",
        primary_domain="aura.invalid",
        workspace_id=state.workspace_id,
        status=AccountStatus.ACTIVE,
    )
    ref = await artifacts.persist_body(
        workspace_id=state.workspace_id,
        data=_ANSWER.encode(),
        media_type="text/plain",
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=state.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=state.project_id,
        client_entity_id=client,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=ref.artifact_key,
        content_sha256=ref.sha256,
        actor="human",
    )
    await record_statement(
        conn,
        onboarding_input_id=captured.onboarding_input_id,
        workspace_id=state.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=state.project_id,
        client_entity_id=client,
        entity_id=client,
        route_kind=StatementRoute.PROJECT_STATE,
        route_key="target_segment",
        quote=recorded_quote,
        quote_start=quote_start,
        quote_end=quote_end,
        created_by_actor="human",
    )
    return state.model_copy(update={"client_entity_id": client})


def _trial(
    conn_factory: Any,
    tmp_path: Path,
    artifacts: DurableAgentArtifactStore,
    state: Stage0TrialState,
) -> Stage0Trial:
    trial = object.__new__(Stage0Trial)
    trial.state = state
    trial.paths = Stage0TrialPaths.for_session(tmp_path, state.session_slug)
    trial._components = SimpleNamespace(artifacts=artifacts)  # type: ignore[assignment]
    trial._conn_factory = conn_factory
    return trial


def _scenario(
    tmp_path: Path,
    stage0_db_available: bool,
    *,
    body: Any,
    recorded_quote: str = _QUOTE,
    quote_start: int = _QUOTE_START,
    quote_end: int = _QUOTE_END,
) -> None:
    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def _run() -> None:
        state = _state(f"ev-{uuid4().hex[:8]}")
        async with db_lifespan() as engine:
            conn = await engine.connect()
            outer = await conn.begin()

            @asynccontextmanager
            async def connection_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            try:
                artifacts = DurableAgentArtifactStore(
                    storage=FsStorage(tmp_path / "artifacts"),
                    conn_factory=connection_factory,
                )
                seeded = await _seed(
                    conn,
                    artifacts,
                    state=state,
                    recorded_quote=recorded_quote,
                    quote_start=quote_start,
                    quote_end=quote_end,
                )
                await body(conn, connection_factory, artifacts, seeded, tmp_path)
            finally:
                await outer.rollback()
                await conn.close()

    run_async(_run())


def test_the_reader_returns_the_verbatim_captured_span(
    tmp_path: Path, stage0_db_available: bool
) -> None:
    """The words, not a hash — byte-compared against the artifact body the turn captured."""

    async def body(
        conn: AsyncConnection,
        conn_factory: Any,
        artifacts: DurableAgentArtifactStore,
        state: Stage0TrialState,
        _tmp: Path,
    ) -> None:
        rows = await read_statements(
            conn, workspace_id=state.workspace_id, project_id=state.project_id
        )
        reader = ArtifactStatementEvidenceReader(artifacts=artifacts, conn_factory=conn_factory)
        (resolved,) = await reader.resolve_quotes(workspace_id=state.workspace_id, statements=rows)

        assert isinstance(resolved, ResolvedQuote)
        assert resolved.quote == _QUOTE
        assert resolved.quote.encode() == _ANSWER.encode()[_QUOTE_START:_QUOTE_END]
        # the single-statement form of the port agrees with the batch form
        single = await reader.resolve_quote(workspace_id=state.workspace_id, statement=rows[0])
        assert single == resolved

    _scenario(tmp_path, stage0_db_available, body=body)


def test_erased_evidence_is_an_exclusion_not_a_failure(
    tmp_path: Path, stage0_db_available: bool
) -> None:
    """A DSAR erasure removes words from every reader, and disables neither of them."""

    async def body(
        conn: AsyncConnection,
        conn_factory: Any,
        artifacts: DurableAgentArtifactStore,
        state: Stage0TrialState,
        _tmp: Path,
    ) -> None:
        key = (
            await conn.execute(
                text("SELECT artifact_key FROM onboarding_input WHERE workspace_id = :w"),
                {"w": state.workspace_id},
            )
        ).scalar_one()
        await mark_erased(conn, key)
        rows = await read_statements(
            conn, workspace_id=state.workspace_id, project_id=state.project_id
        )
        reader = ArtifactStatementEvidenceReader(artifacts=artifacts, conn_factory=conn_factory)

        (resolved,) = await reader.resolve_quotes(workspace_id=state.workspace_id, statements=rows)
        assert isinstance(resolved, ExcludedEvidence)
        assert resolved.statement_id == rows[0].id
        # stable, not a one-shot failure
        assert (await reader.resolve_quotes(workspace_id=state.workspace_id, statements=rows)) == (
            resolved,
        )

    _scenario(tmp_path, stage0_db_available, body=body)


def test_a_span_that_no_longer_hashes_to_its_quote_raises(
    tmp_path: Path, stage0_db_available: bool
) -> None:
    """Corruption/tampering is loud: laundering it into an omission would let a mutated artifact
    quietly rewrite what the client is recorded as having said."""

    async def body(
        conn: AsyncConnection,
        conn_factory: Any,
        artifacts: DurableAgentArtifactStore,
        state: Stage0TrialState,
        _tmp: Path,
    ) -> None:
        rows = await read_statements(
            conn, workspace_id=state.workspace_id, project_id=state.project_id
        )
        reader = ArtifactStatementEvidenceReader(artifacts=artifacts, conn_factory=conn_factory)
        with pytest.raises(
            StatementEvidenceCorrupt, match="does not match its captured evidence quote"
        ):
            await reader.resolve_quotes(workspace_id=state.workspace_id, statements=rows)

    _scenario(
        tmp_path,
        stage0_db_available,
        body=body,
        # the offsets select one span, the row hashed a different one
        quote_start=0,
        quote_end=10,
        recorded_quote=_QUOTE,
    )


def test_a_cross_workspace_artifact_reference_raises(
    tmp_path: Path, stage0_db_available: bool
) -> None:
    """A scoping violation is not an erasure. Fail closed rather than serve foreign bytes."""

    async def body(
        conn: AsyncConnection,
        conn_factory: Any,
        artifacts: DurableAgentArtifactStore,
        state: Stage0TrialState,
        _tmp: Path,
    ) -> None:
        rows = await read_statements(
            conn, workspace_id=state.workspace_id, project_id=state.project_id
        )
        reader = ArtifactStatementEvidenceReader(artifacts=artifacts, conn_factory=conn_factory)
        with pytest.raises(StatementEvidenceCorrupt, match="owned by another workspace"):
            await reader.resolve_quotes(workspace_id="some-other-workspace", statements=rows)

    _scenario(tmp_path, stage0_db_available, body=body)


def test_synthesis_and_the_card_read_the_same_words_through_one_seam(
    tmp_path: Path, stage0_db_available: bool
) -> None:
    """The DRY guarantee, executable: ``_project_statements`` and the card's reader agree.

    Both now call ``resolve_statement_quotes``; this asserts the two callers therefore produce the
    same quote for the same statement, which is the property that stops the model's context and the
    synthesis prompt from drifting apart.
    """

    async def body(
        conn: AsyncConnection,
        conn_factory: Any,
        artifacts: DurableAgentArtifactStore,
        state: Stage0TrialState,
        tmp: Path,
    ) -> None:
        rows = await read_statements(
            conn, workspace_id=state.workspace_id, project_id=state.project_id
        )
        synthesis = await _trial(conn_factory, tmp, artifacts, state)._project_statements(conn)
        shared = await resolve_statement_quotes(
            conn, artifacts, workspace_id=state.workspace_id, statements=rows
        )

        assert [item.quote for item in synthesis.statements] == [
            item.quote for item in shared if isinstance(item, ResolvedQuote)
        ]
        assert synthesis.excluded_statement_ids == tuple(
            item.statement_id for item in shared if isinstance(item, ExcludedEvidence)
        )

    _scenario(tmp_path, stage0_db_available, body=body)


def test_the_card_carries_the_verbatim_quote_through_the_production_reader(
    tmp_path: Path, stage0_db_available: bool
) -> None:
    """AC-4 end to end: the compiled card shows the exact artifact slice.

    Also AC-8's process-restart half, approximated: recompiling through independently constructed
    storage / reader / policy objects yields the same sha256, so the digest is a function of
    durable state and the policy version alone.
    """

    async def body(
        conn: AsyncConnection,
        conn_factory: Any,
        artifacts: DurableAgentArtifactStore,
        state: Stage0TrialState,
        tmp: Path,
    ) -> None:
        card = await compile_stage0_project_card(
            project_id=state.project_id,
            workspace_id=state.workspace_id,
            client_entity_id=EntityId(state.client_entity_id),
            client_kb_version=state.client_kb_version,
            product_id=state.product_id,
            evidence=ArtifactStatementEvidenceReader(
                artifacts=artifacts, conn_factory=conn_factory
            ),
            conn_factory=conn_factory,
        )

        (entry,) = card.interview.current_effective_statements
        assert entry.quoted_text == _QUOTE
        assert entry.quote_truncated is False
        assert entry.quoted_text.encode() == _ANSWER.encode()[_QUOTE_START:_QUOTE_END]
        assert card.omissions == ()

        fresh = await compile_stage0_project_card(
            project_id=state.project_id,
            workspace_id=state.workspace_id,
            client_entity_id=EntityId(state.client_entity_id),
            client_kb_version=state.client_kb_version,
            product_id=state.product_id,
            evidence=ArtifactStatementEvidenceReader(
                artifacts=DurableAgentArtifactStore(
                    storage=FsStorage(tmp / "artifacts"), conn_factory=conn_factory
                ),
                conn_factory=conn_factory,
            ),
            policy=Stage0CardPolicy(version=STAGE0_CARD_POLICY_V1.version),
            conn_factory=conn_factory,
        )
        assert fresh.content_sha256() == card.content_sha256()

    _scenario(tmp_path, stage0_db_available, body=body)
