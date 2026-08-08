"""FI-2 slice 2 — the **lens-isolation guarantee**, asserted at the predicate level (spec §9).

Slice 2's other half migrates the C7 ``allowed_run_ids`` suppliers onto ``run_lineage`` so the
platform has one claim→project attribution mechanism. This module proves the property that
migration depends on, and it does so **below every read surface**: no endpoint, no BFF, no view
composer — just the claim table, ``run_lineage``, and the predicate the read layers embed
(``claim.run_id IN (SELECT run_id FROM run_lineage WHERE workspace_id=… AND project_id=…)``). A
guarantee asserted only through an endpoint dies with that endpoint; asserted here it outlives
every read surface the platform will grow.

The fixture is the spec §10 canonical shape narrowed to one account: workspace W, projects A and B,
**one shared account**, and five claims on it —

* A's ``project_relative`` claim, on a run registered to A;
* B's ``project_relative`` claim, on a run registered to B;
* a ``project_neutral`` claim on one of those project runs, and another on a workspace-level run
  (both must serve in *every* lens — lineage filtering is species-conditional, slice-0 handoff);
* a ``project_relative`` claim on a **NULL-project** (workspace-level) run;
* a ``project_relative`` claim on an **unregistered** run — the ``run_lineage`` module docstring's
  exemption classes (redaction/tombstone runs, pre-FI-2 historical rows).

What is asserted: each project's lens returns exactly its own relative claim and never the other's;
the narrower per-execution lens (:func:`~clue_research.claimstore.runs_for_project_run`) splits two
runs of the same project where the project lens holds both; the NULL-project and unregistered
claims are in **neither** lens (not silently attributed to one); a tombstone built by the shipped
DSAR primitive on a fresh, deliberately unregistered run reaches no lens and leaves the field
reading as absent; and the canonical merge keeps serving the neutral claims regardless of lens —
with the neutral/relative split *derived* from the registry via
:func:`~clue_core.resolve_research_scope`, never hardcoded here, so a §5.2 re-ratification moves
this test with it instead of leaving it asserting a stale species table.

Everything is workspace-scoped (this suite shares a database with suites that commit) and runs
inside the rolled-back claim-store transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    Confidence,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    ResearchScope,
    ReuseScope,
    RunId,
    account_claim,
    new_project_run_id,
    new_run_id,
    resolve_research_scope,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    current_value,
    current_values,
    get_field,
    insert_claim,
    project_run_ids,
    record_run_lineage,
    runs_for_project_run,
    supersede_claim,
)

# The redaction doctrine is asserted against the **shipped** DSAR primitive, never a copy of its
# shape: a test that hand-rolls the tombstone can drift from the erasure path it claims to pin.
from clue_research.compliance.dsar import build_tombstone
from clue_research.identity import insert_account_entity
from tests._workspace import seed_project, seed_run, seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

_WS = "ws-lens-isolation"

# The fixture's fields. Their species is *read from the registry* below, never asserted from this
# list — these names only say "the fixture writes claims on these keys".
_RELATIVE_FIELD = "account.scoring.fit"
_NEUTRAL_FIELD = "account.recent_funding"
_NEUTRAL_WORKSPACE_FIELD = "core.employee_count"

# The neutral fact project A's run paid for. Named because the species test asserts this exact
# value comes back when reading the account through project B's lens — "serves in every lens
# regardless of which project paid" is only meaningful if the *value* is the one A produced.
_NEUTRAL_VALUE_FROM_A = {"amount_usd": 25_000_000, "round": "series_b"}


# --- the predicate under test ----------------------------------------------------------------

# The project-lens predicate exactly as the read layers embed it: a correlated subselect over
# ``run_lineage``, anchored on BOTH tenancy columns. ``run_lineage.workspace_id`` is a real tenancy
# column on a real tenancy table, so the join may be workspace-filtered — unlike ``claim
# .workspace_id``, which a CHECK forces NULL on public-footprint claims (filtering on it silently
# empties a read; slice-0 handoff).
_LENS_SUBSELECT = text(
    """
    SELECT c.id FROM claim c
    WHERE c.entity_id = :entity_id
      AND c.run_id IN (
          SELECT run_id FROM run_lineage
          WHERE workspace_id = :workspace_id AND project_id = :project_id
      )
    ORDER BY c.collected_at, c.id
    """
)

# The same predicate expressed the other way the read layers may reach it: resolve the run set with
# the ``run_lineage`` helper, then filter claims by an IN-list. The two must always agree — one is
# the SQL the endpoints inline, the other is the Python seam FI-2 P2 ships.
_LENS_IN_LIST = text(
    """
    SELECT c.id FROM claim c
    WHERE c.entity_id = :entity_id AND c.run_id IN :run_ids
    ORDER BY c.collected_at, c.id
    """
).bindparams(bindparam("run_ids", expanding=True))


async def _lens(
    conn: AsyncConnection, *, entity_id: EntityId, project_id: str, workspace_id: str = _WS
) -> set[ClaimId]:
    """Every claim on ``entity_id`` visible through ``project_id``'s lens (the raw subselect)."""
    rows = await conn.execute(
        _LENS_SUBSELECT,
        {"entity_id": entity_id, "workspace_id": workspace_id, "project_id": project_id},
    )
    return {ClaimId(row) for row in rows.scalars()}


async def _lens_via_helper(
    conn: AsyncConnection, *, entity_id: EntityId, project_id: str, workspace_id: str = _WS
) -> set[ClaimId]:
    """The same lens sourced from :func:`project_run_ids` — the shipped Python seam."""
    run_ids = await project_run_ids(conn, workspace_id=workspace_id, project_id=project_id)
    if not run_ids:
        return set()
    rows = await conn.execute(_LENS_IN_LIST, {"entity_id": entity_id, "run_ids": list(run_ids)})
    return {ClaimId(row) for row in rows.scalars()}


# --- the fixture -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fixture:
    """Two projects, one shared account, and one claim per attribution case."""

    project_a: str
    project_b: str
    account: EntityId
    relative_a: ClaimId
    relative_b: ClaimId
    neutral_on_project_run: ClaimId
    neutral_on_workspace_run: ClaimId
    relative_on_null_project_run: ClaimId
    relative_on_unregistered_run: ClaimId


async def _write_claim(
    conn: AsyncConnection,
    *,
    account: EntityId,
    field_key: str,
    value: object,
    run_id: RunId,
    private: bool,
) -> ClaimId:
    claim = account_claim(
        entity_id=account,
        field_key=field_key,
        value_json=value,  # type: ignore[arg-type]
        source_tier=2,
        extraction_method=ExtractionMethod.API,
        confidence=Confidence(0.9),
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://example.test/lens",
        evidence_span="seeded for the lens-isolation fixture",
    )
    if private:
        # ``account.scoring.*`` is declared ``tenant_private`` at the field, so the write boundary
        # refuses a public stamp — this mirrors what M6.3 actually writes.
        claim = claim.model_copy(
            update={"reuse_scope": ReuseScope.TENANT_PRIVATE, "workspace_id": _WS}
        )
    return await insert_claim(conn, claim)


async def _registered_run(conn: AsyncConnection, *, kind: str, project_id: str | None) -> RunId:
    run_id = new_run_id()
    await record_run_lineage(
        conn, run_id=run_id, workspace_id=_WS, kind=kind, project_id=project_id
    )
    return run_id


async def _seed(conn: AsyncConnection) -> _Fixture:
    await seed_workspace(conn, _WS)
    project_a = (await seed_project(conn, _WS, name="Lens project A")).project_id
    project_b = (await seed_project(conn, _WS, name="Lens project B")).project_id
    account = await insert_account_entity(
        conn,
        canonical_name="Lens Shared Account",
        primary_domain="lens-shared.test",
        workspace_id=_WS,
    )

    run_a = await _registered_run(conn, kind="scoring", project_id=project_a)
    run_b = await _registered_run(conn, kind="scoring", project_id=project_b)
    run_workspace = await _registered_run(conn, kind="stage0", project_id=None)
    # Deliberately never registered — the exemption classes in ``run_lineage``'s docstring.
    run_unregistered = new_run_id()

    return _Fixture(
        project_a=project_a,
        project_b=project_b,
        account=account,
        relative_a=await _write_claim(
            conn,
            account=account,
            field_key=_RELATIVE_FIELD,
            value={"value": 0.91, "components": [], "icp_key": "icp-a", "icp_version": 1},
            run_id=run_a,
            private=True,
        ),
        relative_b=await _write_claim(
            conn,
            account=account,
            field_key=_RELATIVE_FIELD,
            value={"value": 0.12, "components": [], "icp_key": "icp-b", "icp_version": 1},
            run_id=run_b,
            private=True,
        ),
        neutral_on_project_run=await _write_claim(
            conn,
            account=account,
            field_key=_NEUTRAL_FIELD,
            value=dict(_NEUTRAL_VALUE_FROM_A),
            run_id=run_a,
            private=False,
        ),
        neutral_on_workspace_run=await _write_claim(
            conn,
            account=account,
            field_key=_NEUTRAL_WORKSPACE_FIELD,
            value=430,
            run_id=run_workspace,
            private=False,
        ),
        relative_on_null_project_run=await _write_claim(
            conn,
            account=account,
            field_key=_RELATIVE_FIELD,
            value={"value": 0.5, "components": [], "icp_key": "icp-ws", "icp_version": 1},
            run_id=run_workspace,
            private=True,
        ),
        relative_on_unregistered_run=await _write_claim(
            conn,
            account=account,
            field_key=_RELATIVE_FIELD,
            value={"value": 0.77, "components": [], "icp_key": "icp-legacy", "icp_version": 1},
            run_id=run_unregistered,
            private=True,
        ),
    )


# --- (1) the isolation guarantee ---------------------------------------------------------------


def test_each_project_lens_returns_exactly_its_own_relative_claims() -> None:
    """The whole point: one shared account, two projects, and neither sees the other's work."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fx = await _seed(conn)
            lens_a = await _lens(conn, entity_id=fx.account, project_id=fx.project_a)
            lens_b = await _lens(conn, entity_id=fx.account, project_id=fx.project_b)

            # Exact, not merely "contains": A's lens is A's relative claim plus the neutral claim
            # that happened to be written on A's run (a *lineage* fact — the neutral claim is still
            # served to every lens by the canonical merge; see the species test below).
            assert lens_a == {fx.relative_a, fx.neutral_on_project_run}
            assert lens_b == {fx.relative_b}
            # Never crossing, in either direction.
            assert fx.relative_b not in lens_a
            assert fx.relative_a not in lens_b
            assert lens_a & lens_b == set()

            # The lens is anchored on BOTH tenancy columns: another workspace asking for the same
            # project id sees nothing, so a project id is never a cross-tenant key.
            assert (
                await _lens(
                    conn,
                    entity_id=fx.account,
                    project_id=fx.project_a,
                    workspace_id="ws-lens-isolation-other",
                )
                == set()
            )

    run_async(_run())


def test_the_helper_and_the_inline_subselect_are_the_same_lens() -> None:
    """``project_run_ids`` (the Python seam) and the inlined SQL subselect cannot drift apart."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fx = await _seed(conn)
            for project_id in (fx.project_a, fx.project_b):
                assert await _lens(conn, entity_id=fx.account, project_id=project_id) == (
                    await _lens_via_helper(conn, entity_id=fx.account, project_id=project_id)
                )

    run_async(_run())


def test_a_workspace_level_run_lands_in_no_project_lens() -> None:
    """A registered run with a NULL ``project_id`` (stage 0, seeds, client-KB) belongs to no lens.

    It is not guessed onto the "nearest" project: a claim nobody can attribute must stay
    unattributed (the representative-run fiction FI-2 §7 exists to remove).
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            fx = await _seed(conn)
            lens_a = await _lens(conn, entity_id=fx.account, project_id=fx.project_a)
            lens_b = await _lens(conn, entity_id=fx.account, project_id=fx.project_b)
            assert fx.relative_on_null_project_run not in lens_a
            assert fx.relative_on_null_project_run not in lens_b

    run_async(_run())


def test_an_unregistered_run_lands_in_no_project_lens() -> None:
    """The exemption classes (``run_lineage`` docstring): no lineage row ⇒ no lens membership."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fx = await _seed(conn)
            lens_a = await _lens(conn, entity_id=fx.account, project_id=fx.project_a)
            lens_b = await _lens(conn, entity_id=fx.account, project_id=fx.project_b)
            assert fx.relative_on_unregistered_run not in lens_a
            assert fx.relative_on_unregistered_run not in lens_b

    run_async(_run())


def test_a_redaction_run_reaches_no_lens_and_never_wins_the_merge() -> None:
    """The documented redaction exemption, behaving as documented.

    DSAR/erasure mints a **fresh** run id to supersede a claim with a redacted ``REJECTED``
    tombstone and deliberately does not register it: a redaction belongs to no project's lens — it
    is an act of removal, not of research. Both halves of the docstring's promise are asserted: the
    tombstone is invisible to every lens, *and* it is merge-excluded, so no read can surface it.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            fx = await _seed(conn)
            redaction_run = new_run_id()  # never registered — that is the doctrine
            # The tombstone is the **shipped** DSAR primitive, not a copy of its shape: if the
            # erasure path's claim ever changes, this doctrine test moves with it.
            target = (
                await claims_by_ids(
                    conn, [fx.neutral_on_project_run], scope=WorkspaceScope.for_workspace(_WS)
                )
            )[fx.neutral_on_project_run]
            tombstone = build_tombstone(target, run_id=redaction_run)
            tombstone_id = await supersede_claim(
                conn, fx.neutral_on_project_run, tombstone, validate_field=False
            )

            for project_id in (fx.project_a, fx.project_b):
                assert tombstone_id not in await _lens(
                    conn, entity_id=fx.account, project_id=project_id
                )
            # And it is merge-excluded. The outcome is deterministic, not merely "not the redacted
            # value": the tombstone superseded the only live claim on that field and is itself
            # REJECTED, so the current truth is *nothing* — an erased fact reads as absent.
            merged = await current_value(
                conn,
                fx.account,
                _NEUTRAL_FIELD,
                scope=WorkspaceScope.for_workspace(_WS),
            )
            assert merged is None

    run_async(_run())


def test_the_run_level_lens_splits_where_the_project_level_lens_does_not() -> None:
    """``runs_for_project_run`` is the narrower lens: one *execution* of a project, not the project.

    Two runs of project A, each writing its own relative claim: the project lens holds both (they
    are both A's work), while each project-run lens holds only its own — the isolation a
    ``context_scope='project_run_pinned'`` read depends on.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            fx = await _seed(conn)
            claims: dict[uuid.UUID, ClaimId] = {}
            for icp_version in (1, 2):
                project_run_id = uuid.UUID(str(new_project_run_id()))
                await seed_run(
                    conn,
                    project_run_id=ProjectRunId(project_run_id),
                    workspace_id=_WS,
                    project_id=fx.project_a,
                    icp_version=icp_version,
                )
                run_id = new_run_id()
                await record_run_lineage(
                    conn,
                    run_id=run_id,
                    workspace_id=_WS,
                    kind="scoring",
                    project_id=fx.project_a,
                    project_run_id=project_run_id,
                )
                claims[project_run_id] = await _write_claim(
                    conn,
                    account=fx.account,
                    field_key=_RELATIVE_FIELD,
                    value={
                        "value": 0.4 + icp_version / 10,
                        "components": [],
                        "icp_key": "icp-a",
                        "icp_version": icp_version,
                    },
                    run_id=run_id,
                    private=True,
                )

            project_lens = await _lens(conn, entity_id=fx.account, project_id=fx.project_a)
            assert set(claims.values()) <= project_lens  # both executions are A's work
            for project_run_id, claim_id in claims.items():
                run_ids = await runs_for_project_run(
                    conn, workspace_id=_WS, project_run_id=project_run_id
                )
                rows = await conn.execute(
                    _LENS_IN_LIST, {"entity_id": fx.account, "run_ids": list(run_ids)}
                )
                assert {ClaimId(row) for row in rows.scalars()} == {claim_id}

    run_async(_run())


# --- (2) the species-conditional rule ----------------------------------------------------------


async def _neutral_and_relative(
    conn: AsyncConnection, field_keys: set[str]
) -> tuple[set[str], set[str]]:
    """Split ``field_keys`` by their **registry** species — derived, never hardcoded here."""
    neutral: set[str] = set()
    relative: set[str] = set()
    for field_key in sorted(field_keys):
        field = await get_field(conn, field_key)
        assert field is not None, f"{field_key} is not in the registry — fixture drift"
        if resolve_research_scope(field) is ResearchScope.PROJECT_NEUTRAL:
            neutral.add(field_key)
        else:
            relative.add(field_key)
    return neutral, relative


def test_the_canonical_merge_serves_neutral_fields_in_every_lens() -> None:
    """Lineage filtering is **species-conditional**: neutral facts are workspace truth.

    A neutral claim keeps serving from ``current_values`` whichever project's run paid for it —
    including the one written on project A's run, read while looking at the account "through" B.
    The neutral set is resolved from the registry, so the assertion tracks the ratified §5.2 table
    rather than restating it.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            fx = await _seed(conn)
            neutral, relative = await _neutral_and_relative(
                conn, {_RELATIVE_FIELD, _NEUTRAL_FIELD, _NEUTRAL_WORKSPACE_FIELD}
            )
            assert neutral, "fixture must hold at least one project_neutral field"
            assert relative == {_RELATIVE_FIELD}

            merged = await current_values(
                conn, [fx.account], sorted(neutral), scope=WorkspaceScope.for_workspace(_WS)
            )
            # Every neutral field answers — the merge is lens-blind, and that is correct for them.
            assert {field_key for (_, field_key) in merged} == neutral

            # And the *value* served is the one project A's run produced, even though this read is
            # the account seen through B: neutral facts are workspace truth, not A's property.
            assert fx.neutral_on_project_run not in await _lens(
                conn, entity_id=fx.account, project_id=fx.project_b
            )
            assert merged[(fx.account, _NEUTRAL_FIELD)].value_json == _NEUTRAL_VALUE_FROM_A

    run_async(_run())


def test_the_merge_alone_cannot_separate_the_two_projects_relative_claims() -> None:
    """Why the lens exists at all: the canonical merge picks *one* winner across both projects.

    ``current_value`` on the relative field answers with a single value — it has no notion of
    project — so a project-scoped read of a relative field must go through the lineage predicate,
    not the merge. This pins the failure mode slice 2's suppliers exist to prevent.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            fx = await _seed(conn)
            merged = await current_value(
                conn, fx.account, _RELATIVE_FIELD, scope=WorkspaceScope.for_workspace(_WS)
            )
            assert merged is not None
            assert isinstance(merged.value_json, dict)
            # One answer for two projects' scores — ambiguous by construction.
            assert merged.value_json.get("icp_key") in {"icp-a", "icp-b", "icp-ws", "icp-legacy"}

            # The lens, by contrast, answers per project and disagrees with itself across lenses.
            lens_a = await _lens(conn, entity_id=fx.account, project_id=fx.project_a)
            lens_b = await _lens(conn, entity_id=fx.account, project_id=fx.project_b)
            assert (fx.relative_a in lens_a) and (fx.relative_a not in lens_b)

    run_async(_run())
