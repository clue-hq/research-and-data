"""M13.1 — the review surface, on a live Postgres (the DB proofs the fakes can't make).

Composes the real :class:`~clue_research.review.ReviewSurfaceImpl` over the real claim store and the
review tables, and asserts the spec ACs: a correction wins ``current_value`` with human provenance
(the original stays queryable); a reject excludes the claim from ``current_value`` (so it can't
reach the handoff); ``open_session`` is idempotent; every action records a ``review_action`` row +
emits
the disposition seam; ``finalize`` marks the session and feeds the handoff gate; the review DB enums
match their core taxonomies. Skips without a DB (like the rest of the DB suites).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    Claim,
    EntityId,
    ExtractionMethod,
    IdentityBinding,
    ProjectRunId,
    ResearchMode,
    ReuseScope,
    ReviewAction,
    ReviewActionOutcome,
    ReviewRejectReason,
    ReviewSessionStatus,
    UseClass,
    account_claim,
    contact_claim,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    claims_for,
    current_value,
    insert_claim,
)
from clue_research.identity import insert_account_entity, insert_contact_entity, stamp_reuse
from clue_research.profiling.committee import load_committee_pack
from clue_research.review import (
    FIT_FIELD,
    ClaimNotInSession,
    InMemoryVerificationAnnotationReader,
    ReviewProjector,
    ReviewProjectScope,
    ReviewSurfaceImpl,
    finalized_review_account_ids,
)
from clue_spine import create_brand, create_product
from tests._run_lineage import assert_written_claims_are_attributable
from tests._workspace import seed_run, seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_review_db")

_CLIENT = "client-acme"
_SCOPE = WorkspaceScope.for_workspace(_CLIENT)
_PAIN = "account.operational_pain"  # a core-pack account field (string value)


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


class _RecordingEmitter:
    def __init__(self) -> None:
        self.actions: list[ReviewAction] = []

    async def on_review_action(
        self,
        outcome: ReviewActionOutcome,
        *,
        account_entity_id: EntityId,
        contact_entity_id: EntityId | None,
        project_run_id: ProjectRunId,
        actor: str,
    ) -> None:
        self.actions.append(outcome.action)


class _StaticProjectScopeReader:
    def __init__(self, product_id: str | None) -> None:
        self._product_id = product_id

    async def read_scope(
        self,
        conn: AsyncConnection,
        *,
        project_run_id: ProjectRunId,
        workspace_id: str,
    ) -> ReviewProjectScope:
        del conn, project_run_id, workspace_id
        return ReviewProjectScope(product_id=self._product_id)


def _surface(
    conn: AsyncConnection,
    *,
    emitter: _RecordingEmitter | None = None,
    product_id: str | None = "product-a",
) -> ReviewSurfaceImpl:
    return ReviewSurfaceImpl(
        projector=ReviewProjector(
            annotation_reader=InMemoryVerificationAnnotationReader(),
            project_scope_reader=_StaticProjectScopeReader(product_id),
        ),
        session_factory=_factory(conn),
        resume_hook=None,  # no campaign to resume in these surface-level proofs
        disposition_emitter=emitter,
    )


async def _account(conn: AsyncConnection) -> EntityId:
    await seed_workspace(conn, _CLIENT)
    return await insert_account_entity(
        conn,
        canonical_name="Acme",
        primary_domain="acme.com",
        status=AccountStatus.ACTIVE,
        workspace_id=_CLIENT,
    )


def _orig(entity: EntityId) -> Claim:
    """An eligible (tier-2 scrape) account claim — the current_value before any review action."""
    return account_claim(
        entity_id=entity,
        field_key=_PAIN,
        value_json="original pain",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://news.example/acme",
    )


def test_correction_wins_current_value_and_original_stays_queryable() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await _account(conn)
            orig = _orig(acct)
            await insert_claim(conn, orig)
            surface = _surface(conn)
            session = await surface.open_session(
                account_entity_id=acct, project_run_id=new_project_run_id(), workspace_id=_CLIENT
            )
            assert any(
                r.field_key == _PAIN and r.is_current for r in session.account_claims
            )  # the original is the projected current value
            outcome = await surface.apply_action(
                session_id=session.session_id,
                claim_id=orig.id,
                action=ReviewAction.CORRECT,
                actor="reviewer",
                corrected_value_json="corrected pain",
            )
            assert outcome.superseding_claim_id is not None
            cv = await current_value(conn, acct, _PAIN, scope=_SCOPE)
            assert cv is not None
            assert cv.value_json == "corrected pain"  # the human correction wins
            assert cv.provenance.source_tier == 1  # tier-1 human provenance
            hist = await claims_for(conn, acct, _PAIN, include_superseded=True, scope=_SCOPE)
            assert any(c.id == orig.id for c in hist)  # original remains queryable (append-only)
            # FI-2 P2: the human action's one-claim run is registered as `manual`. This session's
            # project_run has no row (the soft FK permits it), so it degrades to a workspace-level
            # run rather than failing the correction.
            await assert_written_claims_are_attributable(
                conn,
                (await claims_by_ids(conn, [outcome.superseding_claim_id], scope=_SCOPE))[
                    outcome.superseding_claim_id
                ].run_id,
                kind="manual",
                workspace_id=_CLIENT,
                project_id=None,
            )

    run_async(_run())


def test_human_action_run_is_attributed_to_the_sessions_project() -> None:
    """FI-2 P2: with a real project_run behind the session, the manual run carries its project."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await _account(conn)
            orig = _orig(acct)
            await insert_claim(conn, orig)
            project_run_id = new_project_run_id()
            project_id = await seed_run(conn, project_run_id=project_run_id, workspace_id=_CLIENT)
            surface = _surface(conn)
            session = await surface.open_session(
                account_entity_id=acct, project_run_id=project_run_id, workspace_id=_CLIENT
            )
            outcome = await surface.apply_action(
                session_id=session.session_id,
                claim_id=orig.id,
                action=ReviewAction.CORRECT,
                actor="reviewer",
                corrected_value_json="corrected pain",
            )
            assert outcome.superseding_claim_id is not None
            superseding = (await claims_by_ids(conn, [outcome.superseding_claim_id], scope=_SCOPE))[
                outcome.superseding_claim_id
            ]
            await assert_written_claims_are_attributable(
                conn,
                superseding.run_id,
                kind="manual",
                workspace_id=_CLIENT,
                project_id=project_id,
                project_run_id=project_run_id,
            )

    run_async(_run())


def test_reject_excludes_claim_from_current_value() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await _account(conn)
            orig = _orig(acct)
            await insert_claim(conn, orig)
            surface = _surface(conn)
            session = await surface.open_session(
                account_entity_id=acct, project_run_id=new_project_run_id(), workspace_id=_CLIENT
            )
            await surface.apply_action(
                session_id=session.session_id,
                claim_id=orig.id,
                action=ReviewAction.REJECT,
                actor="reviewer",
                reason_code=ReviewRejectReason.INACCURATE,
            )
            cv = await current_value(conn, acct, _PAIN, scope=_SCOPE)
            assert cv is None  # rejected → empty field (a correct output; absent from the handoff)

    run_async(_run())


def test_review_projection_and_actions_are_exact_product_scoped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            acct = await _account(conn)
            brand = await create_brand(
                conn, workspace_id=_CLIENT, name="Review product-scope brand"
            )
            for product_id in ("product-a", "product-b"):
                await create_product(
                    conn,
                    workspace_id=_CLIENT,
                    brand_id=brand.brand_id,
                    product_id=product_id,
                    name=product_id,
                )
            run_id = new_project_run_id()
            neutral = _orig(acct).model_copy(update={"value_json": "neutral pain"})
            product_a = _orig(acct).model_copy(
                update={
                    "value_json": "product A pain",
                    "reuse_scope": ReuseScope.TENANT_PRIVATE,
                    "workspace_id": _CLIENT,
                    "product_id": "product-a",
                }
            )
            product_b = _orig(acct).model_copy(
                update={
                    "value_json": "product B pain",
                    "reuse_scope": ReuseScope.TENANT_PRIVATE,
                    "workspace_id": _CLIENT,
                    "product_id": "product-b",
                }
            )
            for claim in (neutral, product_a, product_b):
                await insert_claim(conn, claim)

            for product_id, score_value in (("product-a", 0.91), ("product-b", 0.22)):
                score = account_claim(
                    entity_id=acct,
                    field_key=FIT_FIELD,
                    value_json={
                        "value": score_value,
                        "components": [],
                        "project_run_id": str(run_id),
                    },
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    source_url="https://scores.example/fit",
                    confidence=1.0,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                )
                await insert_claim(
                    conn,
                    stamp_reuse(score, workspace_id=_CLIENT).model_copy(
                        update={"product_id": product_id}
                    ),
                )

            contacts: list[tuple[EntityId, str]] = []
            for suffix, product_id in (("A", "product-a"), ("B", "product-b")):
                contact_id = await insert_contact_entity(
                    conn,
                    account_entity_id=acct,
                    full_name=f"Product {suffix} contact",
                    linkedin_url=f"https://linkedin.example/product-{suffix.lower()}",
                    status=AccountStatus.ACTIVE,
                )
                role = contact_claim(
                    entity_id=contact_id,
                    field_key="contact.role_on_committee",
                    value_json={"role": "champion", "plausible": True},
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    source_url=f"https://linkedin.example/product-{suffix.lower()}",
                    confidence=0.9,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.COMMITTEE_DISCOVERY,
                    identity_binding=IdentityBinding.STRONG,
                    use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                )
                await insert_claim(
                    conn,
                    stamp_reuse(role, workspace_id=_CLIENT).model_copy(
                        update={"product_id": product_id}
                    ),
                )
                contacts.append((contact_id, product_id))

            surface = _surface(conn, product_id="product-a")
            session = await surface.open_session(
                account_entity_id=acct,
                project_run_id=run_id,
                workspace_id=_CLIENT,
            )

            claim_rows = {row.claim_id: row for row in session.account_claims}
            assert neutral.id in claim_rows
            assert product_a.id in claim_rows
            assert product_b.id not in claim_rows
            assert claim_rows[product_a.id].is_current is True
            assert claim_rows[neutral.id].is_current is False
            assert session.fit_score is not None
            assert float(session.fit_score.value) == pytest.approx(0.91)
            assert {member.contact_entity_id for member in session.committee} == {contacts[0][0]}
            assert str(product_b.id) not in session.provenance_index

            corrected = await surface.apply_action(
                session_id=session.session_id,
                claim_id=product_a.id,
                action=ReviewAction.CORRECT,
                corrected_value_json="corrected product A pain",
                actor="reviewer",
            )
            assert corrected.superseding_claim_id is not None
            successor = (
                await claims_by_ids(
                    conn,
                    [corrected.superseding_claim_id],
                    scope=_SCOPE,
                )
            )[corrected.superseding_claim_id]
            assert successor.product_id == "product-a"

            with pytest.raises(ClaimNotInSession):
                await surface.apply_action(
                    session_id=session.session_id,
                    claim_id=product_b.id,
                    action=ReviewAction.APPROVE,
                    actor="reviewer",
                )

    run_async(_run())


def test_open_session_is_idempotent_and_action_emits_disposition() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await _account(conn)
            orig = _orig(acct)
            await insert_claim(conn, orig)
            emitter = _RecordingEmitter()
            surface = _surface(conn, emitter=emitter)
            run_id = new_project_run_id()
            first = await surface.open_session(
                account_entity_id=acct, project_run_id=run_id, workspace_id=_CLIENT
            )
            again = await surface.open_session(
                account_entity_id=acct, project_run_id=run_id, workspace_id=_CLIENT
            )
            assert first.session_id == again.session_id  # idempotent on (account, run, round)
            await surface.apply_action(
                session_id=first.session_id,
                claim_id=orig.id,
                action=ReviewAction.APPROVE,
                actor="reviewer",
            )
            assert emitter.actions == [ReviewAction.APPROVE]
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM review_action WHERE review_session_id = :s"),
                    {"s": first.session_id},
                )
            ).scalar_one()
            assert count == 1  # exactly one audit row per action

    run_async(_run())


def test_finalize_marks_session_and_feeds_the_handoff_gate() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await _account(conn)
            run_id = new_project_run_id()
            surface = _surface(conn)
            session = await surface.open_session(
                account_entity_id=acct, project_run_id=run_id, workspace_id=_CLIENT
            )
            assert await finalized_review_account_ids(conn, run_id) == frozenset()
            finalized = await surface.finalize(session_id=session.session_id, actor="reviewer")
            assert finalized.status is ReviewSessionStatus.FINALIZED
            assert acct in await finalized_review_account_ids(conn, run_id)  # unblocks the handoff

    run_async(_run())


def test_review_db_enums_match_core() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            for typename, enum in (
                ("review_action_kind", ReviewAction),
                ("review_session_status", ReviewSessionStatus),
                ("review_reject_reason", ReviewRejectReason),
            ):
                labels = (
                    (
                        await conn.execute(
                            text(
                                "SELECT enumlabel FROM pg_enum e JOIN pg_type t "
                                "ON e.enumtypid = t.oid "
                                "WHERE t.typname = :t ORDER BY e.enumsortorder"
                            ),
                            {"t": typename},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert list(labels) == [m.value for m in enum]

    run_async(_run())
