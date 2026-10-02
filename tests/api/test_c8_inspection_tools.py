"""PC-C8 §7 / AC-3 — the two bounded inspection tools.

The card sheds history to stay under its 24,000-byte ceiling, and these tools are the only way the
shed history comes back. So the properties worth testing are not "does it return rows" but the
ones that would let the fix regress:

* **Bounded.** A page is ≤ 20 rows however long the conversation is, and every reduction is
  reported (``total_matching`` / ``has_more`` / ``next_cursor``). Prompt bloat migrating from the
  opening context into a tool result would be the same defect one layer over.
* **Cursors are the card's cursors.** An ``omissions`` entry the compiler emitted is handed to the
  tool verbatim and resumes exactly where the card stopped — that is the whole reason the card can
  drop rows without lying. Round-trip, empty page, and past-the-end are all asserted.
* **Fail-closed scoping.** A project in another workspace refuses ``stage0_project_not_found``,
  identically to an absent one; a sibling project in the *same* workspace never bleeds into the
  answer.
* **Quote-exclusion honesty.** A statement whose evidence is erased comes back *named as excluded*
  with a null quote — never with fabricated words, and never silently dropped.

Invocation goes through :func:`~clue_toolbelt.invoke_tool` against a real registry, so the
descriptor's output model validates every response: a tool that returned an unbounded or
mis-shaped page would fail here rather than in a session.

DB-backed, ``tests/api`` conventions: per-branch ``CLUE_DATABASE_URL``, one rollback-only
transaction per scenario, ``pytest.skip`` without a database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.stage0_inspection_tools import (
    MAX_INSPECTION_PAGE,
    build_stage0_inspection_tools,
)
from clue_api.statement_evidence import ArtifactStatementEvidenceReader
from clue_core import (
    EntityId,
    OnboardingInputKind,
    ReadinessGate,
    VolunteeredStatementId,
    new_operation_id,
)
from clue_projections import Stage0CardOmissionKind, decode_card_cursor, encode_card_cursor
from clue_projections.stage0 import Stage0CardPolicy, compile_stage0_project_card
from clue_research.stage0 import (
    StatementRoute,
    override_readiness,
    record_statement,
    submit_onboarding_input,
)
from clue_spine import create_project
from clue_storage import ArtifactNotFound
from clue_storage.artifacts import mark_erased
from clue_toolbelt import PreconditionFailed, ToolContext, ToolRegistry, invoke_tool
from tests.api.test_c8_project_card_wiring import _seeded_trial
from tests.api.test_c8_slice0_evidence import (
    _ANSWER,
    _QUOTE_END,
    _QUOTE_START,
    _seed_material_turns,
)
from tests.db.conftest import _db_available, run_async

TTL = 86400.0


@pytest.fixture
def stage0_db_available() -> bool:
    return _db_available()


def _registry(artifacts: Any, connection_factory: Any, *, evidence: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_stage0_inspection_tools(
        evidence=(
            ArtifactStatementEvidenceReader(artifacts=artifacts, conn_factory=connection_factory)
            if evidence
            else None
        ),
        conn_factory=connection_factory,
    ):
        registry.register(tool, make_default=True)
    return registry


def _ctx(workspace_id: str, connection_factory: Any) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=connection_factory,
        operation_id=new_operation_id(),
    )


async def _statements(registry: ToolRegistry, body: dict[str, object], ctx: ToolContext) -> Any:
    return await invoke_tool(
        registry, "inspect_statement_history", body, ctx, idempotency_ttl_s=TTL
    )


async def _readiness(registry: ToolRegistry, body: dict[str, object], ctx: ToolContext) -> Any:
    return await invoke_tool(
        registry, "inspect_readiness_history", body, ctx, idempotency_ttl_s=TTL
    )


def test_statement_history_pages_are_bounded_and_the_cursor_walks_the_whole_ledger(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-3: a 26-statement conversation is fully retrievable, 20 rows at a time, and terminates.

    The cursor walk is asserted to be a *partition* — no row seen twice, none missed — because a
    keyset cursor that repeats or skips is the classic way paginated history quietly lies while
    every individual page looks fine.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"page-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            await _seed_material_turns(
                conn, artifacts, state=trial.state, statements=20, decisions=0, first_turn=6
            )
            registry = _registry(artifacts, connection_factory)
            ctx = _ctx(trial.state.workspace_id, connection_factory)
            body: dict[str, object] = {"project_id": trial.state.project_id}

            first = await _statements(registry, body, ctx)
            assert first.references["page_size"] == MAX_INSPECTION_PAGE
            assert first.references["returned"] == MAX_INSPECTION_PAGE
            assert first.references["total_matching"] == 26
            assert first.references["has_more"] is True
            assert first.references["next_cursor"] is not None

            seen: list[str] = []
            cursor: str | None = None
            pages = 0
            while True:
                page = await _statements(
                    registry, {**body, "cursor": cursor} if cursor else body, ctx
                )
                pages += 1
                assert page.references["returned"] <= MAX_INSPECTION_PAGE
                seen.extend(row["statement_id"] for row in page.references["statements"])
                cursor = page.references["next_cursor"]
                if cursor is None:
                    break
                assert pages < 10, "the cursor walk did not terminate"

            assert pages == 2
            assert len(seen) == 26
            assert len(set(seen)) == 26, "a cursor page repeated a row"

            durable = {
                str(row[0])
                for row in (
                    await conn.execute(
                        text(
                            "SELECT id FROM volunteered_statement "
                            "WHERE workspace_id = :ws AND project_id = :project"
                        ),
                        {"ws": trial.state.workspace_id, "project": trial.state.project_id},
                    )
                ).all()
            }
            assert set(seen) == durable, "the walk did not cover the durable ledger exactly"

            # Past the end: an honest empty page, not a silent restart at page one.
            beyond = await _statements(
                registry,
                {
                    **body,
                    "cursor": encode_card_cursor(
                        {"kind": "statements", "before_statement_id": seen[-1]}
                    ),
                },
                ctx,
            )
            assert beyond.references["returned"] == 0
            assert beyond.references["statements"] == []
            assert beyond.references["has_more"] is False
            assert beyond.references["next_cursor"] is None

            # A cursor naming a row that no longer exists resumes past the end for the same reason:
            # replaying page one would look like new history.
            stale = await _statements(
                registry,
                {
                    **body,
                    "cursor": encode_card_cursor(
                        {"kind": "statements", "before_statement_id": str(uuid4())}
                    ),
                },
                ctx,
            )
            assert stale.references["returned"] == 0

    run_async(scenario())


def test_a_card_omission_cursor_resumes_exactly_where_the_card_stopped(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """The contract that makes bounding the card honest rather than lossy.

    The card emits ``statements_over_cap`` with a cursor and names no tool; the tool accepts that
    cursor and continues the same newest-first sequence. If the two orders ever diverged, the card
    would be dropping rows the agent could not actually reach.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"cursor-{uuid4().hex[:8]}") as (
            trial,
            _conn,
            artifacts,
            connection_factory,
        ):
            card = await compile_stage0_project_card(
                project_id=trial.state.project_id,
                workspace_id=trial.state.workspace_id,
                client_entity_id=EntityId(trial.state.client_entity_id),
                client_kb_version=trial.state.client_kb_version,
                evidence=ArtifactStatementEvidenceReader(
                    artifacts=artifacts, conn_factory=connection_factory
                ),
                product_id=trial.state.product_id,
                policy=Stage0CardPolicy(max_statements=2),
                conn_factory=connection_factory,
            )
            shown = [entry.statement_id for entry in card.interview.current_effective_statements]
            assert len(shown) == 2
            omission = next(
                item
                for item in card.omissions
                if item.kind is Stage0CardOmissionKind.STATEMENTS_OVER_CAP
            )
            assert omission.cursor is not None
            # The card's cursor is opaque to the model but is a card cursor, not a tool invention.
            assert decode_card_cursor(omission.cursor)["before_statement_id"] == shown[-1]

            registry = _registry(artifacts, connection_factory)
            ctx = _ctx(trial.state.workspace_id, connection_factory)
            page = await _statements(
                registry,
                {"project_id": trial.state.project_id, "cursor": omission.cursor},
                ctx,
            )
            resumed = [row["statement_id"] for row in page.references["statements"]]
            # Nothing the card already showed comes back...
            assert not set(resumed) & set(shown)
            # ...and what does come back is exactly the tail of the tool's own sequence after the
            # card's boundary row. That is the property that matters: the card's order and the
            # tool's order are one sequence, so a cursor handed across the seam means the same
            # position on both sides. (Row counts cannot be predicted from the omission count —
            # the card de-duplicates repeated `(route_key, quote)` pairs and the tool does not.)
            everything = await _statements(registry, {"project_id": trial.state.project_id}, ctx)
            order = [row["statement_id"] for row in everything.references["statements"]]
            boundary = order.index(shown[-1])
            assert resumed == order[boundary + 1 :]

    run_async(scenario())


def test_an_erased_quote_is_reported_as_excluded_and_never_fabricated(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """Quote-exclusion honesty, the same rule the card holds.

    The tool resolves quotes through the shared evidence reader, so an erased capture produces a
    named exclusion (``artifact_missing``) with a null ``quoted_text``. Two failure modes are
    ruled out: inventing words, and dropping the row so the reader never learns it existed.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"excl-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            registry = _registry(artifacts, connection_factory)
            ctx = _ctx(trial.state.workspace_id, connection_factory)
            body: dict[str, object] = {"project_id": trial.state.project_id}

            before = await _statements(registry, body, ctx)
            assert all(row["quoted_text"] for row in before.references["statements"])
            assert all(
                row["quote_excluded_reason"] is None for row in before.references["statements"]
            )

            target = before.references["statements"][0]
            key = (
                await conn.execute(
                    text(
                        "SELECT i.artifact_key FROM volunteered_statement s "
                        "JOIN onboarding_input i ON i.id = s.onboarding_input_id "
                        "WHERE s.id = :id"
                    ),
                    {"id": target["statement_id"]},
                )
            ).scalar_one()
            await mark_erased(conn, key)

            after = await _statements(registry, body, ctx)
            rows = {row["statement_id"]: row for row in after.references["statements"]}
            # Still present — the row is not hidden, only its words are gone.
            assert target["statement_id"] in rows
            erased_row = rows[target["statement_id"]]
            assert erased_row["quoted_text"] is None
            assert erased_row["quote_excluded_reason"] == "artifact_missing"
            # Its neighbours are untouched: one erasure is not a blanket degradation.
            others = [row for sid, row in rows.items() if sid != target["statement_id"]]
            assert others and all(row["quoted_text"] for row in others)

            # And the card's `excluded_statement_evidence_missing` omission has a resolver: the
            # same tool, driven by that omission's cursor, returns exactly the excluded rows.
            excluded_page = await _statements(
                registry,
                {
                    **body,
                    "cursor": encode_card_cursor({"kind": "excluded_statement_evidence"}),
                },
                ctx,
            )
            assert excluded_page.references["view"] == "excluded_statement_evidence"
            assert [row["statement_id"] for row in excluded_page.references["statements"]] == [
                target["statement_id"]
            ]
            # The exclusion view abstains from `total_matching` rather than reporting the candidate
            # pool: knowing the true total would mean resolving the whole ledger's evidence, and a
            # number that meant something else let a truncated page read as a complete one.
            assert excluded_page.references["total_matching"] is None
            assert excluded_page.references["candidates_scanned"] >= 1
            # The plain view still reports an exact total.
            assert after.references["total_matching"] == len(rows)

    run_async(scenario())


def test_the_excluded_view_cursor_walk_partitions_the_excluded_set(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """The B1 regression: >20 exclusions must all be reachable, and each exactly once.

    The first implementation kept scanning after the page filled but advanced the cursor past the
    rows it had refused to append — so with 40 candidates and 35 exclusions it returned 20, said
    ``has_more: False``, and made candidates 25..39 unreachable *forever*. Two failures at once:
    silent row loss, and a completion signal that hid it.

    So this asserts the same property the statements-view walk asserts — the pages are a
    **partition** of the excluded set (no row missed, none repeated) — plus the specific lie:
    ``has_more`` must not go false while excluded rows remain.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"exclwalk-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            # 40 candidates in total, of which 35 lose their evidence: more than one page of
            # exclusions, and enough live rows in between that a chunk-advancing bug skips some.
            await _seed_material_turns(
                conn, artifacts, state=trial.state, statements=34, decisions=0, first_turn=6
            )
            registry = _registry(artifacts, connection_factory)
            ctx = _ctx(trial.state.workspace_id, connection_factory)
            body: dict[str, object] = {"project_id": trial.state.project_id}

            everything = await _statements(registry, body, ctx)
            assert everything.references["total_matching"] == 40
            ordered = [row["statement_id"] for row in everything.references["statements"]]
            second = await _statements(
                registry, {**body, "cursor": everything.references["next_cursor"]}, ctx
            )
            ordered.extend(row["statement_id"] for row in second.references["statements"])
            assert len(ordered) == 40

            # Erase 35 of them, spread across the order so the survivors interleave.
            doomed = [sid for index, sid in enumerate(ordered) if index % 8 != 0]
            assert len(doomed) == 35
            for statement_id in doomed:
                key = (
                    await conn.execute(
                        text(
                            "SELECT i.artifact_key FROM volunteered_statement s "
                            "JOIN onboarding_input i ON i.id = s.onboarding_input_id "
                            "WHERE s.id = :id"
                        ),
                        {"id": statement_id},
                    )
                ).scalar_one()
                await mark_erased(conn, key)

            seen: list[str] = []
            cursor: str | None = None
            pages = 0
            while True:
                page = await _statements(
                    registry,
                    {
                        **body,
                        "cursor": cursor
                        or encode_card_cursor({"kind": "excluded_statement_evidence"}),
                    },
                    ctx,
                )
                pages += 1
                assert page.references["view"] == "excluded_statement_evidence"
                assert page.references["returned"] <= MAX_INSPECTION_PAGE
                seen.extend(row["statement_id"] for row in page.references["statements"])
                cursor = page.references["next_cursor"]
                if cursor is None:
                    break
                assert pages < 20, "the excluded-view cursor walk did not terminate"

            # A partition of the excluded set: every one reached, none twice, nothing else.
            assert len(seen) == len(set(seen)), "an excluded row was returned on two pages"
            assert set(seen) == set(doomed), "the walk did not cover every excluded statement"
            # And the specific defect: the first page must not have claimed completion.
            assert pages >= 2

    run_async(scenario())


def test_statement_history_returns_the_whole_correction_lineage_for_one_statement(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """A supersession id in the card raises "what replaced it?" — the tool answers both directions.

    A superseded statement is invisible to the card by design (latest-correction-wins), so this is
    the only surface that can explain a change of mind, and it has to work from *either* end of
    the chain.

    It also has to survive a **fork**. ``volunteered_statement`` is append-only and nothing stops
    two rows naming the same ``correction_of_id`` (a re-routed answer, a retry landing twice, an
    operator repair), so ``superseded_by`` is a list and the lineage walk is breadth-first. A
    last-write-wins map would have returned a chain that looked complete while one branch of what
    replaced the client's words was invisible — the wrong failure on an audit surface.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"lineage-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            state = trial.state
            original = (
                await conn.execute(
                    text(
                        "SELECT id FROM volunteered_statement WHERE workspace_id = :ws "
                        "AND project_id = :project ORDER BY created_at, id LIMIT 1"
                    ),
                    {"ws": state.workspace_id, "project": state.project_id},
                )
            ).scalar_one()

            async def _correct(label: str) -> Any:
                ref = await artifacts.persist_body(
                    workspace_id=state.workspace_id,
                    data=f"{_ANSWER} ({label})".encode(),
                    media_type="text/plain",
                )
                captured = await submit_onboarding_input(
                    conn,
                    workspace_id=state.workspace_id,
                    brand_id=state.brand_id,
                    product_id=state.product_id,
                    project_id=state.project_id,
                    client_entity_id=EntityId(state.client_entity_id),
                    kind=OnboardingInputKind.USER_TURN,
                    artifact_key=ref.artifact_key,
                    content_sha256=ref.sha256,
                    actor="human",
                )
                return await record_statement(
                    conn,
                    onboarding_input_id=captured.onboarding_input_id,
                    workspace_id=state.workspace_id,
                    brand_id=state.brand_id,
                    product_id=state.product_id,
                    project_id=state.project_id,
                    client_entity_id=EntityId(state.client_entity_id),
                    entity_id=EntityId(state.client_entity_id),
                    route_kind=StatementRoute.PROJECT_STATE,
                    route_key="target_segment",
                    quote=_ANSWER[_QUOTE_START:_QUOTE_END],
                    quote_start=_QUOTE_START,
                    quote_end=_QUOTE_END,
                    created_by_actor="agent",
                    correction_of_id=VolunteeredStatementId(original),
                )

            correction = await _correct("correction")

            registry = _registry(artifacts, connection_factory)
            ctx = _ctx(state.workspace_id, connection_factory)
            for anchor in (original, correction):
                page = await _statements(
                    registry,
                    {"project_id": state.project_id, "statement_id": str(anchor)},
                    ctx,
                )
                rows = {row["statement_id"]: row for row in page.references["statements"]}
                assert set(rows) == {str(original), str(correction)}
                assert rows[str(original)]["superseded"] is True
                assert rows[str(original)]["superseded_by"] == [str(correction)]
                assert rows[str(correction)]["supersedes"] == str(original)
                assert rows[str(correction)]["superseded"] is False
                assert rows[str(correction)]["superseded_by"] == []

            # The fork: a second correction of the same parent. Both branches must be visible, and
            # reachable from either branch — not only from the parent.
            fork = await _correct("fork")
            for anchor in (original, correction, fork):
                page = await _statements(
                    registry,
                    {"project_id": state.project_id, "statement_id": str(anchor)},
                    ctx,
                )
                rows = {row["statement_id"]: row for row in page.references["statements"]}
                assert set(rows) == {str(original), str(correction), str(fork)}
                assert sorted(rows[str(original)]["superseded_by"]) == sorted(
                    [str(correction), str(fork)]
                )

            # Both selectors at once is a refusal, never a silent intersection.
            with pytest.raises(PreconditionFailed) as ei:
                await _statements(
                    registry,
                    {
                        "project_id": state.project_id,
                        "statement_id": str(original),
                        "route_key": "target_segment",
                    },
                    ctx,
                )
            assert ei.value.reason_codes == ("statement_selector_ambiguous",)

    run_async(scenario())


def test_readiness_history_pages_the_ledger_and_annotates_the_override(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """AC-3 for the ledger, plus the shared-override contract.

    ``effective_verdict`` comes from the *same* ``readiness_override_refs`` /
    ``effective_readiness_verdict`` pair the card and the C4 readiness view use, so an overridden
    decision reads the same everywhere. The gate filter and the cursor walk are asserted on the
    same ledger so a filtered page cannot quietly page a different sequence.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"ledger-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            await _seed_material_turns(
                conn, artifacts, state=trial.state, statements=20, decisions=20, first_turn=6
            )
            registry = _registry(artifacts, connection_factory)
            ctx = _ctx(trial.state.workspace_id, connection_factory)
            body: dict[str, object] = {"project_id": trial.state.project_id}

            first = await _readiness(registry, body, ctx)
            assert first.references["returned"] == MAX_INSPECTION_PAGE
            assert first.references["ledger_length"] == 25
            assert first.references["total_matching"] == 25
            assert first.references["has_more"] is True

            seen = [row["decision_id"] for row in first.references["decisions"]]
            second = await _readiness(
                registry, {**body, "cursor": first.references["next_cursor"]}, ctx
            )
            seen.extend(row["decision_id"] for row in second.references["decisions"])
            assert second.references["has_more"] is False
            assert second.references["next_cursor"] is None
            assert len(set(seen)) == 25

            # Every row is bounded the way the card bounds a gate — no raw ledger row escapes.
            for row in first.references["decisions"]:
                assert set(row) >= {
                    "decision_id",
                    "gate",
                    "verdict",
                    "effective_verdict",
                    "decision_lineage",
                    "metrics",
                    "reason_codes",
                    "evidence_truncated",
                }
                assert "created_by_actor" in row

            # The gate filter pages the same sequence, narrowed.
            gated = await _readiness(
                registry, {**body, "gate": ReadinessGate.ICP_SYNTHESIS.value}, ctx
            )
            assert gated.references["gate"] == ReadinessGate.ICP_SYNTHESIS.value
            assert all(
                row["gate"] == ReadinessGate.ICP_SYNTHESIS.value
                for row in gated.references["decisions"]
            )

            # An override on the newest decision changes `effective_verdict`, not `verdict`.
            newest = first.references["decisions"][0]
            assert newest["override_ref"] is None
            assert newest["effective_verdict"] == newest["verdict"]
            await override_readiness(
                conn,
                decision_id=newest["decision_id"],
                workspace_id=trial.state.workspace_id,
                gate=ReadinessGate(newest["gate"]),
                actor="human",
                reason="c8 inspection tool override fixture",
            )
            annotated = (await _readiness(registry, body, ctx)).references["decisions"][0]
            assert annotated["decision_id"] == newest["decision_id"]
            assert annotated["verdict"] == newest["verdict"]
            assert annotated["effective_verdict"] == "overridden"
            assert annotated["override_ref"] is not None

    run_async(scenario())


def test_both_tools_refuse_a_foreign_project_exactly_as_they_refuse_an_absent_one(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """B3/B4 fail-closed scoping — refused, not filtered to an empty page.

    An empty page reads as "there is no history"; a refusal reads as "this is not yours". The two
    must not be confusable, and a foreign id must not be distinguishable from a nonexistent one
    (which would make the tool an existence oracle for other tenants' projects).

    A sibling project in the *same* workspace is a legitimate query, so the last assertion is the
    other half: the answer is scoped to the requested project and never bleeds.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"scope-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            state = trial.state
            registry = _registry(artifacts, connection_factory)
            body: dict[str, object] = {"project_id": state.project_id}

            foreign_ctx = _ctx("ws-somebody-else", connection_factory)
            for call in (_statements, _readiness):
                with pytest.raises(PreconditionFailed) as foreign:
                    await call(registry, body, foreign_ctx)
                with pytest.raises(PreconditionFailed) as absent:
                    await call(
                        registry,
                        {"project_id": f"project_absent_{uuid4().hex[:8]}"},
                        _ctx(state.workspace_id, connection_factory),
                    )
                assert foreign.value.reason_codes == ("stage0_project_not_found",)
                assert absent.value.reason_codes == foreign.value.reason_codes

            # A sibling project in the same workspace: allowed, and strictly isolated.
            sibling = await create_project(
                conn,
                workspace_id=state.workspace_id,
                brand_id=state.brand_id,
                product_id=state.product_id,
                name="Sibling project",
                project_id=f"{state.project_id}_sibling",
            )
            await _seed_material_turns(
                conn,
                artifacts,
                state=state.model_copy(update={"project_id": sibling.project_id}),
                statements=3,
                decisions=3,
                first_turn=100,
            )
            ctx = _ctx(state.workspace_id, connection_factory)
            mine = await _statements(registry, body, ctx)
            theirs = await _statements(registry, {"project_id": sibling.project_id}, ctx)
            assert mine.references["total_matching"] == 6
            assert theirs.references["total_matching"] == 3
            assert not (
                {row["statement_id"] for row in mine.references["statements"]}
                & {row["statement_id"] for row in theirs.references["statements"]}
            )

    run_async(scenario())


def test_a_cursor_from_the_other_tool_or_a_malformed_one_is_a_typed_refusal(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """A cursor the tool cannot resolve must refuse, not quietly serve page one.

    Silently ignoring an unrecognised position is how a paginated read starts looping forever over
    the same 20 rows while looking perfectly healthy.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"curkind-{uuid4().hex[:8]}") as (
            trial,
            _conn,
            artifacts,
            connection_factory,
        ):
            registry = _registry(artifacts, connection_factory)
            ctx = _ctx(trial.state.workspace_id, connection_factory)
            body: dict[str, object] = {"project_id": trial.state.project_id}
            readiness_cursor = encode_card_cursor({"kind": "readiness_history"})
            statement_cursor = encode_card_cursor({"kind": "statements"})

            with pytest.raises(PreconditionFailed) as crossed:
                await _statements(registry, {**body, "cursor": readiness_cursor}, ctx)
            assert crossed.value.reason_codes == ("cursor_kind_unsupported",)

            with pytest.raises(PreconditionFailed) as crossed_back:
                await _readiness(registry, {**body, "cursor": statement_cursor}, ctx)
            assert crossed_back.value.reason_codes == ("cursor_kind_unsupported",)

            for garbage in ("not-a-cursor", encode_card_cursor({"kind": "invented"})):
                with pytest.raises(PreconditionFailed) as bad:
                    await _statements(registry, {**body, "cursor": garbage}, ctx)
                assert bad.value.reason_codes in {
                    ("cursor_invalid",),
                    ("cursor_kind_unsupported",),
                }

    run_async(scenario())


def test_the_statement_tool_refuses_rather_than_serving_quoteless_rows_without_a_reader(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """Fail-closed on composition: "no reader" must never look like "the words were erased".

    Those are opposite facts — one is a deployment bug, the other is a lawful erasure — and a tool
    that rendered them identically would make an erasure indistinguishable from an outage.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"noev-{uuid4().hex[:8]}") as (
            trial,
            _conn,
            artifacts,
            connection_factory,
        ):
            registry = _registry(artifacts, connection_factory, evidence=False)
            ctx = _ctx(trial.state.workspace_id, connection_factory)
            with pytest.raises(PreconditionFailed) as ei:
                await _statements(registry, {"project_id": trial.state.project_id}, ctx)
            assert ei.value.reason_codes == ("statement_evidence_not_configured",)

            # The readiness tool needs no reader and still answers.
            page = await _readiness(registry, {"project_id": trial.state.project_id}, ctx)
            assert page.references["ledger_length"] == 5

    run_async(scenario())


def test_the_inspection_tools_write_nothing(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """Read-only by contract *and* in fact: no statement row, no ledger row, no artifact.

    ``effect_class=READ`` is a claim; this is the check. The card exists to stop context growing
    per turn, and a "read" tool that appended a row per call would reintroduce exactly that.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with _seeded_trial(tmp_path, slug=f"ro-{uuid4().hex[:8]}") as (
            trial,
            conn,
            artifacts,
            connection_factory,
        ):
            registry = _registry(artifacts, connection_factory)
            ctx = _ctx(trial.state.workspace_id, connection_factory)
            body: dict[str, object] = {"project_id": trial.state.project_id}

            async def counts() -> tuple[int, ...]:
                tallies: list[int] = []
                for table in ("volunteered_statement", "readiness_decision", "artifact"):
                    tallies.append(
                        (
                            await conn.execute(
                                text(f"SELECT count(*) FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
                                {"ws": trial.state.workspace_id},
                            )
                        ).scalar_one()
                    )
                return tuple(tallies)

            before = await counts()
            await _statements(registry, body, ctx)
            await _readiness(registry, body, ctx)
            assert await counts() == before

            for descriptor in registry.descriptors():
                assert descriptor.effect_class.value == "read"
                assert descriptor.replay.policy.value == "effect_free"
                assert descriptor.recipe_safe

    run_async(scenario())


def test_the_inspection_tools_are_granted_to_the_head_of_abm_and_nobody_else() -> None:
    """The 1.5/1.4 hand-off, now landed — this is the tripwire's designed post-grant form.

    While task 1.4 was re-versioning the head-of-abm profile in parallel these two shipped
    *registered and addressable* but granted to nobody, and this test asserted that empty state so
    the grant could not land unnoticed. It has now landed, on profile v10, in the slice-1 closing
    round: the tripwire flips to the shape it was always meant to end at rather than being deleted,
    because "granted to exactly one role" is the claim worth keeping under guard — a second role
    picking these up is a decision, not a detail.
    """

    from clue_agents import AgentRole
    from clue_api.agent_registry_wiring import C6_AGENT_TOOL_AUTHORITY, c6_roles_for_tool
    from clue_api.toolbelt_wiring import build_toolbelt

    registry = build_toolbelt(storage=None, gateway=None)
    # Both stay registered and addressable. ARV2 onboarding O6 split their grants:
    # `inspect_statement_history` reads what the human said in this conversation, which the new
    # lane still records, so the Head of ABM keeps it; `inspect_readiness_history` reads a
    # readiness decision the new lane never makes, so `head-of-abm@v44` drops it and it is granted
    # to nobody. "Granted to exactly one role" is still the claim under guard on the survivor.
    assert "inspect_statement_history" in registry.names()
    assert C6_AGENT_TOOL_AUTHORITY["inspect_statement_history"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("inspect_statement_history@1") == (AgentRole.HEAD_OF_ABM,)
    assert "inspect_readiness_history" in registry.names()
    assert C6_AGENT_TOOL_AUTHORITY["inspect_readiness_history"] == ()
    assert c6_roles_for_tool("inspect_readiness_history@1") == ()


def test_a_storageless_composition_still_builds_the_readiness_tool() -> None:
    """No DB, no storage: the pair composes and only the evidence-dependent half degrades."""

    tools = build_stage0_inspection_tools(evidence=None)
    assert [tool.name for tool in tools] == [
        "inspect_statement_history",
        "inspect_readiness_history",
    ]
    assert all(tool.descriptor.effect_class.value == "read" for tool in tools)
    # Guard against the page bound becoming a caller-supplied input.
    assert "page_size" not in tools[0].input_model.model_fields
    assert "page_size" not in tools[1].input_model.model_fields
    assert MAX_INSPECTION_PAGE <= 20
    # Referenced so an unused-import lint cannot hide the erasure contract this module leans on.
    assert ArtifactNotFound is not None
