"""FI-2 slice 0 — the one-shot membership + lineage backfill (spec §2/§3 backfill paragraphs).

Tasks 1-8 taught every *live* write site to record ``project_account`` membership and
``run_lineage`` attribution. Rows already at rest predate those writers, so a project's account
list and its claim lens are both blind to everything the dev database already holds. This suite
exercises the repair over the real Postgres tables: the six backfill sources, the merge-survivor
redirect, orphan skipping, first-add-wins across sources, the uuid5 discovery-run cross-check
against the production formula, workspace scoping, and — the property that matters most for a
script anyone may re-run — byte-identical idempotency on a second pass.

Like the membership suite, this reuses the identity harness's session-scoped migration + rollback
isolation (the fixtures it seeds are identity/durable rows).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ProjectRunId,
    ResearchMode,
    RunId,
    UseClass,
    contact_claim,
)
from clue_research.claimstore import insert_claim, project_run_ids, record_run_lineage
from clue_research.discovery_scoring import project_discovery_run_id
from clue_research.identity import (
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    stamp_reuse,
)
from clue_research.membership import accounts_for_project, ensure_project_account
from clue_research.profiling.committee import CURRENT_TITLE, load_committee_pack
from clue_research.project_lens_backfill import (
    BACKFILL_SOURCES,
    ProjectLensBackfillReport,
    backfill_project_lens,
)
from tests._workspace import seed_project, seed_workspace

# The identity harness owns the migrated-DB gate; import its fixtures into this module's namespace
# so a top-level test file (the backfill is a top-level ``clue_research`` module) gets them.
from tests.identity.conftest import migrated_db as migrated_db
from tests.identity.conftest import require_identity_db as require_identity_db
from tests.identity.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _sha(text_value: str) -> str:
    return hashlib.sha256(text_value.encode()).hexdigest()


async def _seed_project_run(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    project_run_id: UUID,
    icp_key: str = "default",
    icp_version: int = 1,
) -> None:
    """A ``project_run`` row + the ``icp_spec`` the discovery plan's FK needs."""
    await conn.execute(
        text(
            "INSERT INTO icp_spec (workspace_id, icp_key, version, status, created_from) "
            "VALUES (:w, :k, :v, 'active', 'synthesis') ON CONFLICT DO NOTHING"
        ),
        {"w": workspace_id, "k": icp_key, "v": icp_version},
    )
    brand_id = (
        await conn.execute(
            text("SELECT brand_id FROM brand WHERE workspace_id = :w LIMIT 1"),
            {"w": workspace_id},
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO project_run "
            "(id, workspace_id, project_id, brand_id, icp_key, icp_version, phase, status, "
            " created_at, updated_at) "
            "VALUES (:id, :w, :p, :b, :k, :v, 'discovery', 'active', :t, :t)"
        ),
        {
            "id": project_run_id,
            "w": workspace_id,
            "p": project_id,
            "b": brand_id,
            "k": icp_key,
            "v": icp_version,
            "t": _T0,
        },
    )


async def _seed_discovery_link(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    project_run_id: UUID,
    account_entity_id: UUID,
    survivor_entity_id: UUID | None = None,
    admission_status: str = "admitted",
    started_at: datetime = _T0,
    generation: int = 1,
) -> None:
    """A ``discovery_plan → discovery_batch → item snapshot → candidate link`` chain."""
    plan_id, batch_id, operation_id, snapshot_id = uuid4(), uuid4(), uuid4(), uuid4()
    await conn.execute(
        text(
            "INSERT INTO discovery_plan (id, workspace_id, project_id, project_run_id, icp_key, "
            " icp_version, plan_version, plan_sha256, provider_policy_version, "
            " field_policy_version, provider_contract_version, plan_json) "
            "VALUES (:id, :w, :p, :r, 'default', 1, 1, :sha, 'v1', 'v1', 'v1', '{}'::jsonb)"
        ),
        {
            "id": plan_id,
            "w": workspace_id,
            "p": project_id,
            "r": project_run_id,
            "sha": _sha(str(plan_id)),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO discovery_batch (id, workspace_id, project_id, project_run_id, icp_key, "
            " icp_version, discovery_plan_id, generation, started_at, updated_at) "
            "VALUES (:id, :w, :p, :r, 'default', 1, :plan, :gen, :t, :t)"
        ),
        {
            "id": batch_id,
            "w": workspace_id,
            "p": project_id,
            "r": project_run_id,
            "plan": plan_id,
            "gen": generation,
            "t": started_at,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO discovery_operation (id, workspace_id, batch_id, source_key, "
            " provider_api_version, request_fingerprint, observation_window, provider_external_id) "
            "VALUES (:id, :w, :b, 'exa_websets', 'v1', :fp, 'seed', :ext)"
        ),
        {
            "id": operation_id,
            "w": workspace_id,
            "b": batch_id,
            "fp": _sha(str(operation_id)),
            "ext": f"op-{operation_id}",
        },
    )
    # The snapshot cites a captured blob; ``artifact.storage_key`` is the scope-encoding
    # ``{workspace}/{sha256}`` the CHECK enforces.
    item_sha = _sha(str(snapshot_id))
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :w, :sha, 'application/json', 1) "
            "ON CONFLICT DO NOTHING"
        ),
        {"key": f"{workspace_id}/{item_sha}", "w": workspace_id, "sha": item_sha},
    )
    await conn.execute(
        text(
            "INSERT INTO discovery_item_snapshot (id, workspace_id, operation_id, "
            " provider_item_id, source_kind, source_id, raw_artifact_key, item_sha256, "
            " observed_at) "
            "VALUES (:id, :w, :op, :item, 'search', 'seed', :key, :sha, :t)"
        ),
        {
            "id": snapshot_id,
            "w": workspace_id,
            "op": operation_id,
            "item": f"item-{snapshot_id}",
            "key": f"{workspace_id}/{item_sha}",
            "sha": item_sha,
            "t": started_at,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO discovery_candidate_link (workspace_id, batch_id, item_snapshot_id, "
            " admission_status, account_entity_id, survivor_entity_id, disposition_reason, "
            " updated_at) "
            "VALUES (:w, :b, :s, CAST(:status AS discovery_candidate_admission_state), :a, :v, "
            "        :reason, :t)"
        ),
        {
            "w": workspace_id,
            "b": batch_id,
            "s": snapshot_id,
            "status": admission_status,
            "a": account_entity_id,
            "v": survivor_entity_id if survivor_entity_id is not None else account_entity_id,
            "reason": "merged into survivor" if admission_status == "merged" else None,
            "t": started_at,
        },
    )


async def _seed_directive_membership(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    account_id: UUID,
    created_at: datetime = _T0,
) -> None:
    """An ``account_research_directive`` scoping one account (the FI-2 P1 directive channel)."""
    directive_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO product (product_id, workspace_id, brand_id, name) "
            "SELECT :prod, :w, brand_id, 'Seeded product' FROM brand "
            "WHERE workspace_id = :w LIMIT 1 ON CONFLICT DO NOTHING"
        ),
        {"prod": f"prod-{workspace_id}", "w": workspace_id},
    )
    await conn.execute(
        text(
            "INSERT INTO account_research_directive (directive_id, workspace_id, project_id, "
            " product_id, icp_key, icp_version, version, content_json, created_by, "
            " source_turn_ref, draft_operation_id, draft_request_sha256, canonical_json_sha256, "
            " created_at) "
            "VALUES (:d, :w, :p, :prod, 'default', 1, 1, '{}'::jsonb, 'test', 'turn-1', :op, "
            "        :sha, :sha, :t)"
        ),
        {
            "d": directive_id,
            "w": workspace_id,
            "p": project_id,
            "prod": f"prod-{workspace_id}",
            "op": uuid4(),
            "sha": _sha(str(directive_id)),
            "t": created_at,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO account_research_directive_account (directive_id, workspace_id, "
            " account_id, scope_kind, created_at) VALUES (:d, :w, :a, 'explicit', :t)"
        ),
        {"d": directive_id, "w": workspace_id, "a": account_id, "t": created_at},
    )


async def _seed_entity_research_run(
    conn: AsyncConnection,
    *,
    research_run_id: UUID,
    workspace_id: str,
    project_id: str,
    project_run_id: UUID,
    subject_type: str = "account",
    created_at: datetime = _T0,
) -> None:
    """An M8D fleet research run (the launch row whose id every claim of the run carries).

    A ``contact_research`` run's selection FK and completeness trigger are both DEFERRABLE
    INITIALLY DEFERRED, so inside this suite's always-rolled-back transaction the row is accepted
    without the full contact-selection/launch chain. That is deliberate: the backfill reads only
    the run's identity columns, and building the real chain here would test the M8D writers, not
    this one.
    """
    run_kind = "account_research" if subject_type == "account" else "contact_research"
    selection_id = uuid4()
    lifecycle = {
        "run_id": str(research_run_id),
        "run_kind": run_kind,
        "selection": {
            "selection_id": str(selection_id),
            "subject_type": subject_type,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "product_id": f"prod-{workspace_id}",
            "project_run_id": str(project_run_id),
            "budget_envelope_ref": "envelope-1",
        },
    }
    await conn.execute(
        text(
            "INSERT INTO entity_research_run (research_run_id, run_kind, subject_type, "
            " workspace_id, project_id, product_id, project_run_id, selection_id, lifecycle_json, "
            " lifecycle_sha256, budget_envelope_ref, budget_cap_cents, concurrency_limit, "
            " created_at, updated_at, contact_selection_id) "
            "VALUES (:r, :kind, :subject, :w, :p, :prod, :run, :sel, CAST(:life AS jsonb), :sha, "
            "        'envelope-1', 1000, 1, :t, :t, :contact_sel)"
        ),
        {
            "r": research_run_id,
            "kind": run_kind,
            "subject": subject_type,
            "w": workspace_id,
            "p": project_id,
            "prod": f"prod-{workspace_id}",
            "run": project_run_id,
            "sel": selection_id,
            "life": json.dumps(lifecycle),
            "sha": _sha(str(research_run_id)),
            "t": created_at,
            "contact_sel": None if subject_type == "account" else selection_id,
        },
    )


async def _seed_account_run(
    conn: AsyncConnection,
    *,
    account_run_id: UUID,
    project_run_id: UUID,
    entity_id: UUID,
    started_at: datetime = _T0,
) -> None:
    """An M7.1 per-account research run — ``id`` is the ``claim.run_id`` its claims carry."""
    await conn.execute(
        text(
            "INSERT INTO account_run (id, project_run_id, entity_id, tier, started_at, updated_at) "
            "VALUES (:id, :run, :e, 'tier_1', :t, :t)"
        ),
        {"id": account_run_id, "run": project_run_id, "e": entity_id, "t": started_at},
    )


async def _seed_committee_claim(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: UUID,
    project_run_id: UUID,
) -> None:
    """A committee professional claim — stamped with the **project run itself** as its ``run_id``.

    The M8C C1 lineage trigger requires that shape, and the committee professional pack is the one
    production CONTACT ``project_run_pinned`` route family, so on a pre-FI-2 database these are the
    claims a project-run lens read would drop for want of a lineage row.
    """
    await load_committee_pack(conn)
    contact = await insert_contact_entity(
        conn,
        account_entity_id=account_entity_id,
        full_name="Committee Member",
        linkedin_url=f"https://linkedin.com/in/committee-{project_run_id}",
    )
    claim = contact_claim(
        entity_id=contact,
        field_key=CURRENT_TITLE,
        value_json="VP Revenue Operations",
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        confidence=0.95,
        run_id=RunId(project_run_id),
        research_mode=ResearchMode.COMMITTEE_DISCOVERY,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        source_url="https://example.com/committee",
        evidence_span="Committee member is VP Revenue Operations.",
    )
    await insert_claim(conn, stamp_reuse(claim, workspace_id=workspace_id))


async def _dump(conn: AsyncConnection) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    """Every membership + lineage row, ordered — the byte-identical idempotency probe."""
    memberships = [
        tuple(row)
        for row in (
            await conn.execute(
                text(
                    "SELECT workspace_id, project_id, account_entity_id, added_via, added_at "
                    "FROM project_account ORDER BY workspace_id, project_id, account_entity_id"
                )
            )
        ).all()
    ]
    lineage = [
        tuple(row)
        for row in (
            await conn.execute(
                text(
                    "SELECT run_id, workspace_id, project_id, project_run_id, kind, created_at "
                    "FROM run_lineage ORDER BY run_id"
                )
            )
        ).all()
    ]
    return memberships, lineage


def test_backfill_writes_all_six_sources_and_is_idempotent() -> None:
    """One pass repairs discovery/directive membership + all four lineage sources; a second
    pass writes nothing and leaves every row byte-identical."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf1"
            project = await seed_project(conn, ws)
            project_run_id = uuid4()
            await _seed_project_run(
                conn, workspace_id=ws, project_id=project.project_id, project_run_id=project_run_id
            )
            discovered = await insert_account_entity(
                conn, canonical_name="Discovered", primary_domain="disc-bf1.com", workspace_id=ws
            )
            scoped = await insert_account_entity(
                conn, canonical_name="Scoped", primary_domain="scoped-bf1.com", workspace_id=ws
            )
            await _seed_discovery_link(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                project_run_id=project_run_id,
                account_entity_id=discovered,
            )
            await _seed_directive_membership(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                account_id=scoped,
                created_at=_T0 + timedelta(days=1),
            )
            research_run_id = uuid4()
            await _seed_entity_research_run(
                conn,
                research_run_id=research_run_id,
                workspace_id=ws,
                project_id=project.project_id,
                project_run_id=project_run_id,
            )
            account_run_id = uuid4()
            await _seed_account_run(
                conn,
                account_run_id=account_run_id,
                project_run_id=project_run_id,
                entity_id=discovered,
            )
            await _seed_committee_claim(
                conn,
                workspace_id=ws,
                account_entity_id=discovered,
                project_run_id=project_run_id,
            )

            first = await backfill_project_lens(conn, workspace_id=ws)

            assert set(first.by_source) == set(BACKFILL_SOURCES)
            assert {name: counts.written for name, counts in first.by_source.items()} == {
                "discovery_membership": 1,
                "directive_membership": 1,
                "discovery_lineage": 1,
                "entity_research_lineage": 1,
                "account_run_lineage": 1,
                "committee_lineage": 1,
            }
            assert first.written == 6
            assert first.skipped_orphan == 0
            assert first.by_workspace == {ws: 6}

            # Membership: both accounts, each stamped with the channel that added it.
            assert await accounts_for_project(
                conn, workspace_id=ws, project_id=project.project_id
            ) == (discovered, scoped)
            channels = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT account_entity_id, added_via FROM project_account "
                            "WHERE workspace_id = :w"
                        ),
                        {"w": ws},
                    )
                ).all()
            )
            assert channels == {discovered: "discovered", scoped: "directive"}

            # Lineage: the derived discovery run, the M8D research run, the M7 account run, and
            # the project run's own id (the committee/enrichment writers stamp it as a run id).
            expected_discovery_run = project_discovery_run_id(
                project_run_id=ProjectRunId(project_run_id), icp_key="default", icp_version=1
            )
            assert set(
                await project_run_ids(conn, workspace_id=ws, project_id=project.project_id)
            ) == {
                UUID(str(expected_discovery_run)),
                research_run_id,
                account_run_id,
                project_run_id,
            }
            kinds = dict(
                (
                    await conn.execute(
                        text("SELECT run_id, kind FROM run_lineage WHERE workspace_id = :w"),
                        {"w": ws},
                    )
                ).all()
            )
            assert kinds == {
                UUID(str(expected_discovery_run)): "discovery",
                research_run_id: "entity_research",
                account_run_id: "entity_research",
                project_run_id: "committee",
            }

            before = await _dump(conn)
            second = await backfill_project_lens(conn, workspace_id=ws)
            assert second.written == 0
            assert second.scanned == first.scanned
            assert await _dump(conn) == before

    run_async(_run())


def test_membership_follows_the_merge_survivor_and_the_first_channel_wins() -> None:
    """A candidate link on a merged-away account joins the *survivor*, and when two sources name
    the same account the earlier event's channel is what the row records."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf2"
            project = await seed_project(conn, ws)
            project_run_id = uuid4()
            await _seed_project_run(
                conn, workspace_id=ws, project_id=project.project_id, project_run_id=project_run_id
            )
            loser = await insert_account_entity(
                conn, canonical_name="Loser", primary_domain="loser-bf2.com", workspace_id=ws
            )
            survivor = await insert_account_entity(
                conn, canonical_name="Survivor", primary_domain="surv-bf2.com", workspace_id=ws
            )
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)
            # The link still names the pre-merge id; the backfill must redirect to the survivor.
            await _seed_discovery_link(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                project_run_id=project_run_id,
                account_entity_id=loser,
                started_at=_T0,
            )
            # A *later* directive scopes the same survivor: discovery is the earlier event, so
            # ``added_via`` must stay 'discovered'.
            await _seed_directive_membership(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                account_id=survivor,
                created_at=_T0 + timedelta(days=3),
            )

            report = await backfill_project_lens(conn, workspace_id=ws)

            rows = (
                await conn.execute(
                    text(
                        "SELECT account_entity_id, added_via, added_at FROM project_account "
                        "WHERE workspace_id = :w"
                    ),
                    {"w": ws},
                )
            ).all()
            assert [tuple(row) for row in rows] == [(survivor, "discovered", _T0)]
            assert report.by_source["discovery_membership"].written == 1
            assert report.by_source["directive_membership"].written == 0

    run_async(_run())


def test_an_orphaned_run_is_skipped_and_counted_never_raised() -> None:
    """A research/account run pointing at a vanished ``project_run`` is reported, not fatal."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf3"
            project = await seed_project(conn, ws)
            await conn.execute(
                text(
                    "INSERT INTO product (product_id, workspace_id, brand_id, name) "
                    "SELECT :prod, :w, brand_id, 'Seeded product' FROM brand "
                    "WHERE workspace_id = :w LIMIT 1 ON CONFLICT DO NOTHING"
                ),
                {"prod": f"prod-{ws}", "w": ws},
            )
            orphan_project_run = uuid4()  # never inserted into project_run
            await _seed_entity_research_run(
                conn,
                research_run_id=uuid4(),
                workspace_id=ws,
                project_id=project.project_id,
                project_run_id=orphan_project_run,
            )
            await _seed_account_run(
                conn,
                account_run_id=uuid4(),
                project_run_id=orphan_project_run,
                entity_id=uuid4(),
            )

            # Unscoped, because an orphaned ``account_run`` belongs to no workspace (it derives its
            # workspace through the project run that vanished), so no tenant-scoped pass can see it.
            report = await backfill_project_lens(conn)

            assert report.by_source["entity_research_lineage"].skipped_orphan >= 1
            assert report.by_source["account_run_lineage"].skipped_orphan >= 1
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM run_lineage WHERE project_run_id = :r"),
                    {"r": orphan_project_run},
                )
            ).scalar_one() == 0
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM run_lineage WHERE workspace_id = :w"), {"w": ws}
                )
            ).scalar_one() == 0

    run_async(_run())


def test_contact_side_research_runs_are_attributed_as_contact_research() -> None:
    """The M8D contact fleet registers ``kind='contact_research'``; the backfill must match it."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf4"
            project = await seed_project(conn, ws)
            project_run_id = uuid4()
            await _seed_project_run(
                conn, workspace_id=ws, project_id=project.project_id, project_run_id=project_run_id
            )
            await conn.execute(
                text(
                    "INSERT INTO product (product_id, workspace_id, brand_id, name) "
                    "SELECT :prod, :w, brand_id, 'Seeded product' FROM brand "
                    "WHERE workspace_id = :w LIMIT 1 ON CONFLICT DO NOTHING"
                ),
                {"prod": f"prod-{ws}", "w": ws},
            )
            contact_run = uuid4()
            await _seed_entity_research_run(
                conn,
                research_run_id=contact_run,
                workspace_id=ws,
                project_id=project.project_id,
                project_run_id=project_run_id,
                subject_type="contact",
            )

            await backfill_project_lens(conn, workspace_id=ws)

            assert (
                await conn.execute(
                    text("SELECT kind FROM run_lineage WHERE run_id = :r"), {"r": contact_run}
                )
            ).scalar_one() == "contact_research"

    run_async(_run())


def test_the_derived_discovery_run_id_matches_the_production_formula() -> None:
    """The backfill re-derives the DISCOVERY phase's own run id — not a lookalike.

    ``discovery_scoring.project_discovery_run_id`` is imported, never replicated, so this asserts
    the *wiring*: the row the backfill writes is keyed on exactly what the phase would have
    written for the same ``(project_run, icp_key, icp_version)``.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf5"
            project = await seed_project(conn, ws)
            project_run_id = uuid4()
            await _seed_project_run(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                project_run_id=project_run_id,
                icp_key="enterprise",
                icp_version=3,
            )

            await backfill_project_lens(conn, workspace_id=ws)

            expected = UUID(
                str(
                    project_discovery_run_id(
                        project_run_id=ProjectRunId(project_run_id),
                        icp_key="enterprise",
                        icp_version=3,
                    )
                )
            )
            assert (
                await conn.execute(
                    text("SELECT run_id, kind FROM run_lineage WHERE workspace_id = :w"), {"w": ws}
                )
            ).all() == [(expected, "discovery")]

    run_async(_run())


def test_a_dry_run_previews_exactly_what_the_write_pass_does() -> None:
    """The preview runs the same plan and writes nothing, so it cannot under-report."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf6"
            project = await seed_project(conn, ws)
            project_run_id = uuid4()
            await _seed_project_run(
                conn, workspace_id=ws, project_id=project.project_id, project_run_id=project_run_id
            )
            account = await insert_account_entity(
                conn, canonical_name="Preview", primary_domain="prev-bf6.com", workspace_id=ws
            )
            await _seed_discovery_link(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                project_run_id=project_run_id,
                account_entity_id=account,
            )

            preview = await backfill_project_lens(conn, workspace_id=ws, dry_run=True)
            assert preview.written == 2  # one membership + the derived discovery run
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM project_account WHERE workspace_id = :w"), {"w": ws}
                )
            ).scalar_one() == 0
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM run_lineage WHERE workspace_id = :w"), {"w": ws}
                )
            ).scalar_one() == 0

            real = await backfill_project_lens(conn, workspace_id=ws)
            assert real.model_dump() == preview.model_dump()

    run_async(_run())


def test_workspace_scoping_leaves_other_workspaces_untouched() -> None:
    """``--workspace-id`` repairs one tenant only."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            mine = await seed_project(conn, "ws_bf7a")
            theirs = await seed_project(conn, "ws_bf7b")
            for ws, project in (("ws_bf7a", mine), ("ws_bf7b", theirs)):
                await _seed_project_run(
                    conn,
                    workspace_id=ws,
                    project_id=project.project_id,
                    project_run_id=uuid4(),
                )

            report = await backfill_project_lens(conn, workspace_id="ws_bf7a")

            assert report.by_workspace == {"ws_bf7a": 1}
            assert (
                await conn.execute(
                    text(
                        "SELECT workspace_id FROM run_lineage "
                        "WHERE workspace_id IN ('ws_bf7a', 'ws_bf7b')"
                    )
                )
            ).scalars().all() == ["ws_bf7a"]

    run_async(_run())


def test_an_already_written_membership_is_left_alone() -> None:
    """A live writer's row (Tasks 1-8) is never rewritten by the repair — first add wins."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf8"
            project = await seed_project(conn, ws)
            project_run_id = uuid4()
            await _seed_project_run(
                conn, workspace_id=ws, project_id=project.project_id, project_run_id=project_run_id
            )
            account = await insert_account_entity(
                conn, canonical_name="Live", primary_domain="live-bf8.com", workspace_id=ws
            )
            await ensure_project_account(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                account_entity_id=account,
                added_via="imported",
                added_at=_T0 - timedelta(days=1),
            )
            await _seed_discovery_link(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                project_run_id=project_run_id,
                account_entity_id=account,
            )

            report = await backfill_project_lens(conn, workspace_id=ws)

            assert report.by_source["discovery_membership"].scanned == 1
            assert report.by_source["discovery_membership"].written == 0
            assert [
                tuple(row)
                for row in (
                    await conn.execute(
                        text(
                            "SELECT added_via, added_at FROM project_account "
                            "WHERE workspace_id = :w"
                        ),
                        {"w": ws},
                    )
                ).all()
            ] == [("imported", _T0 - timedelta(days=1))]

    run_async(_run())


def test_an_empty_store_reports_a_converged_zero() -> None:
    """Nothing to repair is a valid, quiet outcome — not an error."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, "ws_bf9")
            report = await backfill_project_lens(conn, workspace_id="ws_bf9")
            assert report == ProjectLensBackfillReport.from_sources({})
            assert report.written == 0 and report.scanned == 0

    run_async(_run())


def test_lineage_carries_the_originating_records_own_timestamp() -> None:
    """A repaired row is stamped with when the run happened, not when the repair ran.

    ``project_run_ids`` orders by ``created_at``, so stamping ``now()`` would shove every backfilled
    run after every live-written one on a partially-repaired database.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf10"
            project = await seed_project(conn, ws)
            project_run_id = uuid4()
            await _seed_project_run(
                conn, workspace_id=ws, project_id=project.project_id, project_run_id=project_run_id
            )
            account_run_id = uuid4()
            started = _T0 + timedelta(days=2)
            await _seed_account_run(
                conn,
                account_run_id=account_run_id,
                project_run_id=project_run_id,
                entity_id=uuid4(),
                started_at=started,
            )

            await backfill_project_lens(conn, workspace_id=ws)

            stamped = dict(
                (
                    await conn.execute(
                        text("SELECT run_id, created_at FROM run_lineage WHERE workspace_id = :w"),
                        {"w": ws},
                    )
                ).all()
            )
            derived = UUID(
                str(
                    project_discovery_run_id(
                        project_run_id=ProjectRunId(project_run_id),
                        icp_key="default",
                        icp_version=1,
                    )
                )
            )
            # The discovery row takes the project run's creation time, the account-run row its own.
            assert stamped == {derived: _T0, account_run_id: started}

    run_async(_run())


def test_a_run_already_registered_under_another_workspace_is_not_re_counted() -> None:
    """``run_lineage``'s key is the run id alone, so the pre-check must span every workspace.

    A workspace-scoped probe would miss the colliding row, the insert would silently no-op, and
    ``written`` would claim a row it did not write — breaking "a second pass writes nothing".
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = "ws_bf11"
            project = await seed_project(conn, ws)
            project_run_id = uuid4()
            await _seed_project_run(
                conn, workspace_id=ws, project_id=project.project_id, project_run_id=project_run_id
            )
            derived = UUID(
                str(
                    project_discovery_run_id(
                        project_run_id=ProjectRunId(project_run_id),
                        icp_key="default",
                        icp_version=1,
                    )
                )
            )
            await seed_workspace(conn, "ws_bf11_other")
            await record_run_lineage(
                conn, run_id=derived, workspace_id="ws_bf11_other", kind="manual"
            )

            report = await backfill_project_lens(conn, workspace_id=ws)

            assert report.by_source["discovery_lineage"].scanned == 1
            assert report.by_source["discovery_lineage"].written == 0
            assert report.by_workspace == {}
            # The squatting row is left exactly as it was — the repair never rewrites.
            assert (
                await conn.execute(
                    text("SELECT workspace_id, kind FROM run_lineage WHERE run_id = :r"),
                    {"r": derived},
                )
            ).all() == [("ws_bf11_other", "manual")]

    run_async(_run())
