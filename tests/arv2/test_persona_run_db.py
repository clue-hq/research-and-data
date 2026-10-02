"""The personas-only onboarding run: its row, its one step, and the request that opens it.

A ``personas`` run is the narrow sibling of the whole-brand walk. It researches nothing and buys no
provider call: it runs exactly one persona synthesis turn for one ICP document — the version a
project pinned — and finishes. Three properties are pinned here, against the real tables:

* the row is **the ICP document's**, not the workspace's: one open personas run per document, and
  the full onboarding surfaces (``read_current_run``, the start route's 409) never see it;
* the driver takes the ``personas`` branch straight to that one step, so nothing re-researches a
  brand that was onboarded months ago;
* the request is **rows first, offer second** (the O3 rule), and an offer that could not be made
  fails the run rather than stranding it at ``queued`` forever.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_api.arv2.onboarding_driver import (
    ONBOARDING_DEDUP_PREFIX,
    IcpRef,
    OnboardingRunWorkHandler,
    SynthesisOutcome,
    onboarding_work_id,
)
from clue_api.arv2.onboarding_store import (
    create_persona_run,
    create_run,
    fail_run,
    finish_run,
    open_persona_run,
    read_current_run,
)
from clue_api.onboarding_routes import ONBOARDING_TASK_PRIORITY
from clue_api.persona_request_tools import (
    DbPersonaRequestService,
    PersonaSynthesisRefused,
    PersonaSynthesisRequest,
)
from clue_config import Settings
from clue_fleet import FleetTaskKind
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.arv2.icp_fixture import (
    ICP_KEY,
    USER_ID,
    FakeQueue,
    IcpFixture,
    seed_icp_document,
    seed_icp_fixture,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

TURN = UUID("7f000000-0000-5000-8000-00000000beef")
OTHER_TURN = UUID("7f000000-0000-5000-8000-00000000cafe")


def _run_id(fixture: IcpFixture, turn_id: UUID = TURN) -> UUID:
    """The id the service derives — recomputed here rather than read back from the receipt."""

    return uuid5(
        UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8"),
        f"arv2-persona-run:{fixture.workspace_id}:{fixture.icp_document_id}:{turn_id}",
    )


async def _completed_full_run(conn: AsyncConnection, fixture: IcpFixture, domain: str) -> UUID:
    """The brand's whole-brand walk, finished — where a personas run takes its domain from."""

    run_id = uuid4()
    await create_run(
        conn,
        run_id=run_id,
        workspace_id=fixture.workspace_id,
        brand_id=fixture.brand_id,
        company_domain=domain,
        requested_by_user_id=USER_ID,
    )
    await finish_run(conn, run_id=run_id)
    return run_id


async def _run_row(conn: AsyncConnection, run_id: UUID) -> dict[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT kind, status, project_id, brand_id, persona_icp_document_id, "
                    "  company_domain, requested_by_user_id "
                    "FROM onboarding_run WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


# =================================================================================================
# the row
# =================================================================================================


def test_a_personas_run_is_open_for_exactly_one_icp_document(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            run_id = uuid4()
            await create_persona_run(
                conn,
                run_id=run_id,
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                project_id=fixture.project_id,
                persona_icp_document_id=fixture.icp_document_id,
                company_domain="clue.dev",
                requested_by_user_id=USER_ID,
            )

            row = await _run_row(conn, run_id)
            assert row["kind"] == "personas"
            assert row["status"] == "queued"
            assert row["project_id"] == fixture.project_id
            assert row["persona_icp_document_id"] == fixture.icp_document_id
            assert row["company_domain"] == "clue.dev"

            assert (
                await open_persona_run(conn, persona_icp_document_id=fixture.icp_document_id)
                == run_id
            )
            # Another document's personas are another document's run.
            other_id, _, _ = await seed_icp_document(
                conn,
                FsStorage(tmp_path),
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                path="audience/icp-other.md",
                status="proposed",
            )
            assert await open_persona_run(conn, persona_icp_document_id=other_id) is None

            # Re-inserting the same id is a no-op, never a second run for one document.
            await create_persona_run(
                conn,
                run_id=run_id,
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                project_id=fixture.project_id,
                persona_icp_document_id=fixture.icp_document_id,
                company_domain="clue.dev",
                requested_by_user_id=USER_ID,
            )
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM onboarding_run WHERE kind = 'personas'")
                )
            ).scalar_one()
            assert count == 1

            # A finished run is no longer open, so the next request may open its own.
            await finish_run(conn, run_id=run_id)
            assert (
                await open_persona_run(conn, persona_icp_document_id=fixture.icp_document_id)
                is None
            )

    run_async(scenario())


def test_the_onboarding_status_read_ignores_a_personas_run(tmp_path: Any) -> None:
    """``GET /onboarding/current`` watches the whole-brand walk. A persona run is not one."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            full = await _completed_full_run(conn, fixture, "clue.dev")
            await create_persona_run(
                conn,
                run_id=uuid4(),
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                project_id=fixture.project_id,
                persona_icp_document_id=fixture.icp_document_id,
                company_domain="clue.dev",
                requested_by_user_id=USER_ID,
            )
            # Both rows are written in one transaction, so ``now()`` gives them the same instant.
            # The personas run is aged forward so it is unambiguously the newest row — otherwise
            # the read could pass by accident on a tie rather than because it filters.
            await conn.execute(
                text(
                    "UPDATE onboarding_run SET requested_at = requested_at + interval '1 minute' "
                    "WHERE kind = 'personas'"
                )
            )

            current = await read_current_run(conn, workspace_id=fixture.workspace_id)
            assert current is not None
            # The newest row by ``requested_at`` is the personas one; the read must skip it.
            assert current.run_id == full
            assert current.status == "completed"

    run_async(scenario())


# =================================================================================================
# the driver branch
# =================================================================================================


@dataclass
class _RecordingLauncher:
    """A synthesis seam that records the ICP it was handed and never opens an ICP turn."""

    seen: list[IcpRef] = field(default_factory=list)

    async def launch_icps(self, **kwargs: Any) -> Any:
        raise AssertionError("a personas run must never open an ICP turn")

    async def launch_persona(
        self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID, icp: IcpRef
    ) -> SynthesisOutcome:
        del workspace_id, brand_id, run_id, step_id
        self.seen.append(icp)
        return SynthesisOutcome(
            status="completed", failure_code=None, failure_message=None, cost_usd=Decimal("0.25")
        )


class _UnusedArtifacts:
    async def persist_body(self, **kwargs: Any) -> ArtifactRef:
        raise AssertionError("a personas run publishes no document of its own")


def _unused_exa(*, run_id: UUID, step_label: str, raw: Any, ledger: Any) -> Any:
    del run_id, step_label, raw, ledger
    raise AssertionError("a personas run buys no provider call")


def _personas_context(
    run_id: UUID, *, workspace_id: str, brand_id: str, icp: dict[str, Any]
) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=onboarding_work_id(run_id),
        worker_id="t",
        lease_generation=LeaseGeneration(1),
        payload={
            "run_id": str(run_id),
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "company_domain": "clue.dev",
            "company_name": "Clue",
            "kind": "personas",
            "icp": icp,
        },
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


def test_a_personas_run_takes_one_persona_step_in_the_icps_own_scope(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            # The pinned ICP is a project-local variant: its personas belong to that project too,
            # so the scope has to survive the payload round trip.
            variant_id, _, _ = await seed_icp_document(
                conn,
                FsStorage(tmp_path),
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                path="audience/icp-clue-abm-buyers-dac.md",
                status="confirmed",
                project_id=fixture.project_id,
            )
            run_id = uuid4()
            await create_persona_run(
                conn,
                run_id=run_id,
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                project_id=fixture.project_id,
                persona_icp_document_id=variant_id,
                company_domain="clue.dev",
                requested_by_user_id=USER_ID,
            )
            launcher = _RecordingLauncher()
            handler = OnboardingRunWorkHandler(
                settings=Settings(_env_file=None),
                conn_factory=conn_session_factory(conn),
                artifacts=_UnusedArtifacts(),  # type: ignore[arg-type]
                exa=_unused_exa,
                synthesis=launcher,
            )

            result = await handler.handle(
                _personas_context(
                    run_id,
                    workspace_id=fixture.workspace_id,
                    brand_id=fixture.brand_id,
                    icp={
                        "document_id": str(variant_id),
                        "icp_key": "clue-abm-buyers-dac",
                        "version": 1,
                        "path": "audience/icp-clue-abm-buyers-dac.md",
                        "project_id": fixture.project_id,
                    },
                )
            )

            assert result.outcome == "completed"
            assert [
                (icp.document_id, icp.icp_key, icp.version, icp.path, icp.project_id)
                for icp in launcher.seen
            ] == [
                (
                    variant_id,
                    "clue-abm-buyers-dac",
                    1,
                    "audience/icp-clue-abm-buyers-dac.md",
                    fixture.project_id,
                )
            ]
            assert (await _run_row(conn, run_id))["status"] == "completed"
            steps = (
                (
                    await conn.execute(
                        text(
                            "SELECT kind, subject_ref, status, phase, cost_usd "
                            "FROM onboarding_step WHERE run_id = :run_id"
                        ),
                        {"run_id": run_id},
                    )
                )
                .mappings()
                .all()
            )
            # Exactly one step: no recon, no catalog sync, no ICP turn.
            assert [(row["kind"], row["subject_ref"], row["status"]) for row in steps] == [
                ("persona", "clue-abm-buyers-dac", "completed")
            ]
            assert Decimal(steps[0]["cost_usd"]) == Decimal("0.25")

    run_async(scenario())


def test_a_personas_payload_that_names_no_icp_is_invalid(tmp_path: Any) -> None:
    """The branch is welded to its subject: a personas task without one is a payload error.

    Read before anything is touched, exactly as the rest of the payload is — a task nobody can
    describe is the fleet's failure to record, not a run to open and then walk back.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            run_id = uuid4()
            await create_persona_run(
                conn,
                run_id=run_id,
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                project_id=fixture.project_id,
                persona_icp_document_id=fixture.icp_document_id,
                company_domain="clue.dev",
                requested_by_user_id=USER_ID,
            )
            handler = OnboardingRunWorkHandler(
                settings=Settings(_env_file=None),
                conn_factory=conn_session_factory(conn),
                artifacts=_UnusedArtifacts(),  # type: ignore[arg-type]
                exa=_unused_exa,
                synthesis=_RecordingLauncher(),
            )
            context = _personas_context(
                run_id,
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                icp={"document_id": str(fixture.icp_document_id)},
            )

            with pytest.raises(ValueError):
                await handler.handle(context)

    run_async(scenario())


# =================================================================================================
# the request
# =================================================================================================


def _request(fixture: IcpFixture, *, icp_key: str = ICP_KEY, turn_id: UUID = TURN) -> Any:
    return PersonaSynthesisRequest(
        workspace_id=fixture.workspace_id,
        project_id=fixture.project_id,
        brand_id=fixture.brand_id,
        turn_id=turn_id,
        user_id=USER_ID,
        icp_key=icp_key,
    )


def _service(conn: AsyncConnection, queue: FakeQueue) -> DbPersonaRequestService:
    return DbPersonaRequestService(queue=queue, conn_factory=conn_session_factory(conn))


def test_the_request_opens_one_run_for_the_pin_and_offers_it_to_the_fleet(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            await _completed_full_run(conn, fixture, "clue.dev")
            queue = FakeQueue()

            receipt = await _service(conn, queue).request(_request(fixture))

            assert receipt.run_id == _run_id(fixture)
            assert receipt.icp_key == ICP_KEY
            assert receipt.replayed is False
            row = await _run_row(conn, receipt.run_id)
            assert row["kind"] == "personas"
            assert row["persona_icp_document_id"] == fixture.icp_document_id
            assert row["project_id"] == fixture.project_id
            assert row["brand_id"] == fixture.brand_id
            # The domain is the brand's own, taken from the walk that onboarded it.
            assert row["company_domain"] == "clue.dev"
            assert row["requested_by_user_id"] == USER_ID

            offered = queue.calls[0]
            assert offered["kind"] is FleetTaskKind.ONBOARDING_RUN
            assert offered["work_id"] == onboarding_work_id(receipt.run_id)
            assert offered["dedup_key"] == f"{ONBOARDING_DEDUP_PREFIX}{receipt.run_id}"
            assert offered["priority"] == ONBOARDING_TASK_PRIORITY
            assert offered["reopen_terminal"] is False
            assert offered["payload"]["kind"] == "personas"
            assert offered["payload"]["icp"] == {
                "document_id": str(fixture.icp_document_id),
                "icp_key": ICP_KEY,
                "version": 1,
                "path": "audience/icp-clue-abm-buyers.md",
                "project_id": None,
            }
            assert offered["payload"]["company_domain"] == "clue.dev"

            # The same turn asking again finds its own run and buys nothing more.
            again = await _service(conn, queue).request(_request(fixture))
            assert (again.run_id, again.replayed) == (receipt.run_id, True)
            assert len(queue.calls) == 1

    run_async(scenario())


def test_a_second_turn_is_refused_while_that_documents_run_is_open(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            await _completed_full_run(conn, fixture, "clue.dev")
            queue = FakeQueue()
            await _service(conn, queue).request(_request(fixture))

            with pytest.raises(PersonaSynthesisRefused) as refused:
                await _service(conn, queue).request(_request(fixture, turn_id=OTHER_TURN))
            assert refused.value.code == "persona_run_already_open"
            assert len(queue.calls) == 1

    run_async(scenario())


def test_a_key_that_is_not_this_projects_pin_is_refused(tmp_path: Any) -> None:
    """The pin is the authority: an unpinned project and a wrong key refuse alike."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            await _completed_full_run(conn, fixture, "clue.dev")
            queue = FakeQueue()

            with pytest.raises(PersonaSynthesisRefused) as wrong_key:
                await _service(conn, queue).request(_request(fixture, icp_key="somebody-else"))
            assert wrong_key.value.code == "icp_not_pinned_for_project"

            unpinned = await seed_project(conn, fixture.workspace_id, name="unpinned")
            with pytest.raises(PersonaSynthesisRefused) as no_pin:
                await _service(conn, queue).request(
                    PersonaSynthesisRequest(
                        workspace_id=fixture.workspace_id,
                        project_id=unpinned.project_id,
                        brand_id=str(unpinned.brand_id),
                        turn_id=TURN,
                        user_id=USER_ID,
                        icp_key=ICP_KEY,
                    )
                )
            assert no_pin.value.code == "icp_not_pinned_for_project"
            assert queue.calls == []

    run_async(scenario())


def test_a_brand_that_was_never_onboarded_is_refused(tmp_path: Any) -> None:
    """No completed walk means no domain to write down — and an empty one would be a fabrication."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            # An open run is not an onboarded brand: only a finished walk has published a domain.
            await create_run(
                conn,
                run_id=uuid4(),
                workspace_id=fixture.workspace_id,
                brand_id=fixture.brand_id,
                company_domain="clue.dev",
                requested_by_user_id=USER_ID,
            )
            queue = FakeQueue()

            with pytest.raises(PersonaSynthesisRefused) as refused:
                await _service(conn, queue).request(_request(fixture))
            assert refused.value.code == "brand_not_onboarded"
            assert queue.calls == []

    run_async(scenario())


def test_a_run_that_could_not_be_offered_is_failed_not_stranded(tmp_path: Any) -> None:
    """Rows first, offer second — and a failed offer must not leave a run nothing will drive."""

    class _BrokenQueue:
        async def enqueue(self, **kwargs: Any) -> bool:
            raise RuntimeError("fleet queue unreachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            await _completed_full_run(conn, fixture, "clue.dev")
            service = DbPersonaRequestService(
                queue=_BrokenQueue(),  # type: ignore[arg-type]
                conn_factory=conn_session_factory(conn),
            )

            with pytest.raises(PersonaSynthesisRefused) as refused:
                await service.request(_request(fixture))
            assert refused.value.code == "enqueue_failed"
            assert (await _run_row(conn, _run_id(fixture)))["status"] == "failed"
            # And the document is free again, so a later turn may ask once the queue is back.
            assert (
                await open_persona_run(conn, persona_icp_document_id=fixture.icp_document_id)
                is None
            )

    run_async(scenario())


def test_a_same_turn_retry_after_the_run_completed_is_replayed_not_re_offered(
    tmp_path: Any,
) -> None:
    """FW1 / review I4: a settled run at this turn's own id is answered honestly.

    ``open_persona_run`` matches ``queued``/``running`` only, so once the run this turn opened has
    finished it returns ``None`` — and the old code fell through to the offer path.
    ``create_persona_run`` is a no-op on its own id, ``enqueue_personas`` is refused on a terminal
    work row (``reopen_terminal=False``), and the agent was told the job *could not be queued; ask
    again* — the opposite of the truth, and following it produced the same refusal forever, because
    a terminal run can never leave its status. ``completed_with_gaps`` is the same fact: the work
    is done, the document may be partial, and that is the persona document's story to tell.
    """

    async def scenario() -> None:
        for terminal in ("completed", "completed_with_gaps"):
            async with rollback_conn() as conn:
                fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
                await _completed_full_run(conn, fixture, "clue.dev")
                queue = FakeQueue()
                first = await _service(conn, queue).request(_request(fixture))
                await conn.execute(
                    text(
                        "UPDATE onboarding_run SET status = :status, finished_at = now() "
                        "WHERE run_id = :run_id"
                    ),
                    {"status": terminal, "run_id": first.run_id},
                )

                again = await _service(conn, queue).request(_request(fixture))

                assert (again.run_id, again.icp_key) == (first.run_id, ICP_KEY)
                assert again.replayed is True
                # Nothing was re-offered, and the settled row was not walked back.
                assert len(queue.calls) == 1
                assert (await _run_row(conn, first.run_id))["status"] == terminal

    run_async(scenario())


def test_a_same_turn_retry_after_the_run_failed_is_refused_persona_run_settled(
    tmp_path: Any,
) -> None:
    """The other settled branch: a failed run cannot be re-offered on the turn that opened it.

    ``fail_run`` is guarded on an open run, so the row can never be revived, and the fleet's
    ``reopen_terminal=False`` means this turn's work id is spent. Saying so by name — with "ask
    again on a new turn", which derives a different ``run_id`` — is the only instruction that can
    actually succeed; ``enqueue_failed``'s "ask again" could not, and carried an ERROR log line for
    a benign path.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_icp_fixture(conn, FsStorage(tmp_path))
            await _completed_full_run(conn, fixture, "clue.dev")
            queue = FakeQueue()
            first = await _service(conn, queue).request(_request(fixture))
            await fail_run(conn, run_id=first.run_id)

            with pytest.raises(PersonaSynthesisRefused) as refused:
                await _service(conn, queue).request(_request(fixture))
            assert refused.value.code == "persona_run_settled"
            assert "new turn" in str(refused.value)
            assert len(queue.calls) == 1

            # A *new* turn derives a new run id, so the honest instruction actually works.
            later = await _service(conn, queue).request(_request(fixture, turn_id=OTHER_TURN))
            assert later.run_id == _run_id(fixture, OTHER_TURN) != first.run_id
            assert later.replayed is False

    run_async(scenario())
