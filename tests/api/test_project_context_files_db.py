"""The project context files against the real rows they are compiled from.

``project/status.md`` is not a story the model tells about the project — it is the project's
own ARV2 rows, read at the moment the turn opens. These tests seed those rows by hand and assert
the compiled facts, because the thing that would silently rot is a count: a discovery run's
verified/shown/approved tallies and an account's person-job count are derived, and a derivation
that drifts from the schema reads as a confident wrong number rather than as an error.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.icp_confirmation import ConfirmedIcp, pin_project_icp
from clue_api.arv2.onboarding_store import create_persona_run
from clue_api.brand_knowledge_context import current_project_knowledge_refs
from clue_api.project_context_files import (
    CompiledProjectFile,
    ProjectFileRef,
    ProjectFilesPinConflict,
    compile_project_files_index_card,
    get_project_files_pin,
    load_or_create_project_files_pin,
    project_seed_files,
    read_pinned_project_files,
    summary_of,
)
from clue_api.project_status import (
    current_project_documents,
    load_project_decisions,
    load_project_status_facts,
    render_decisions_markdown,
    render_status_markdown,
)
from clue_api.thread_store import create_thread
from clue_core import EntityId, OnboardingInputKind, new_project_run_id
from clue_research.durable import ensure_project_run
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from clue_research.stage0 import StatementRoute, record_statement, submit_onboarding_input
from clue_spine import Project
from clue_storage import mark_erased
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

_SHA = "a" * 64
_USER = "usr-context-files"


@pytest.fixture
def require_profiling_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _seed_workspace_project(conn: AsyncConnection) -> Project:
    """A workspace, a brand and a project, plus the ``project_run`` the ARV2 runs hang off."""

    workspace_id = f"pcf-{uuid4().hex[:6]}"
    return await seed_project(conn, workspace_id, name="Project context files")


async def _seed_project_run(conn: AsyncConnection, project: Project) -> UUID:
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="gi-groups",
        icp_version=1,
    )
    return project_run_id


async def _seed_account(conn: AsyncConnection, project: Project, name: str) -> EntityId:
    account_id = await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=f"{name.split()[0].lower()}.example",
        workspace_id=project.workspace_id,
    )
    await ensure_project_account(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        account_entity_id=account_id,
        added_via="manual",
    )
    return account_id


async def _seed_discovery_run(
    conn: AsyncConnection,
    project: Project,
    project_run_id: UUID,
    *,
    asked: int,
    found_strict: int,
    found_relaxed: int,
) -> UUID:
    run_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO arv2_discovery_run (run_id, workspace_id, project_id, brand_id, "
            "project_run_id, icp_artifact_key, icp_artifact_sha256, icp_key, icp_version, "
            "requested_by_user_id, request_sha256, target_count, relaxed_enabled, "
            "criteria_gate_keys, status, asked, found_strict, found_relaxed) "
            "VALUES (:run, :ws, :project, :brand, :project_run, :key, :sha, 'gi-groups', 1, "
            ":user, :request_sha, 20, true, CAST(:gates AS jsonb), 'completed', :asked, "
            ":found_strict, :found_relaxed)"
        ),
        {
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "brand": project.brand_id,
            "project_run": project_run_id,
            "key": f"{project.workspace_id}/icp",
            "sha": _SHA,
            "user": _USER,
            "request_sha": uuid4().hex + uuid4().hex,
            "gates": json.dumps(["geography"]),
            "asked": asked,
            "found_strict": found_strict,
            "found_relaxed": found_relaxed,
        },
    )
    return run_id


async def _seed_candidate(
    conn: AsyncConnection,
    project: Project,
    run_id: UUID,
    domain: str,
    *,
    disposition: str,
    decision: str | None = None,
    judged: bool = True,
) -> None:
    """One candidate. ``judged`` writes a verdict row, which is what ``verified`` counts.

    The pre-spend dispositions (``duplicate_of_existing``, ``found_before``) are stamped
    before any gate is asked, so a candidate carrying one has no verdicts and ``status.md`` must
    not report it as a company the platform checked.
    """

    await conn.execute(
        text(
            "INSERT INTO arv2_discovery_candidate (candidate_id, run_id, workspace_id, "
            "project_id, pass, domain, name, provider_snapshot_json, verdicts_json, disposition, "
            "decision) "
            "VALUES (:candidate, :run, :ws, :project, 'strict', :domain, :name, "
            "CAST(:snapshot AS jsonb), CAST(:verdicts AS jsonb), :disposition, :decision)"
        ),
        {
            "candidate": uuid4(),
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "domain": domain,
            "name": domain,
            "snapshot": json.dumps({"domain": domain}),
            "verdicts": json.dumps(
                [{"gate_key": "geography", "verdict": "pass"}] if judged else []
            ),
            "disposition": disposition,
            "decision": decision,
        },
    )


async def _seed_research_run(conn: AsyncConnection, project: Project, project_run_id: UUID) -> UUID:
    run_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO arv2_research_run (run_id, workspace_id, project_id, brand_id, "
            "project_run_id, icp_artifact_key, icp_artifact_sha256, icp_key, icp_version, "
            "product_selection_version, effort, committee_cap, profile_ref, profile_sha256, "
            "requested_by_user_id, request_sha256, status) "
            "VALUES (:run, :ws, :project, :brand, :project_run, :key, :sha, 'gi-groups', 1, "
            "1, 'full', 5, 'account-research@v1', :sha, :user, :request_sha, 'in_progress')"
        ),
        {
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "brand": project.brand_id,
            "project_run": project_run_id,
            "key": f"{project.workspace_id}/icp",
            "sha": _SHA,
            "user": _USER,
            "request_sha": uuid4().hex + uuid4().hex,
        },
    )
    return run_id


async def _seed_job(
    conn: AsyncConnection,
    project: Project,
    run_id: UUID,
    account_id: EntityId,
    *,
    subject_type: str,
    status: str,
    stage: str | None = None,
) -> None:
    # ``arv2_research_job_finished`` makes the terminal statuses and ``finished_at`` biconditional,
    # and ``arv2_research_job_subject`` does the same for a person job and its contact.
    await conn.execute(
        text(
            "INSERT INTO arv2_research_job (job_id, run_id, workspace_id, account_entity_id, "
            "status, subject_type, subject_entity_id, stage, finished_at) "
            "VALUES (:job, :run, :ws, :account, :status, :subject_type, :subject_entity, :stage, "
            "CASE WHEN :status IN ('completed', 'needs_review') THEN now() END)"
        ),
        {
            "job": uuid4(),
            "run": run_id,
            "ws": project.workspace_id,
            "account": account_id,
            "status": status,
            "subject_type": subject_type,
            "subject_entity": uuid4() if subject_type == "person" else None,
            "stage": stage,
        },
    )


def test_status_facts_read_the_pin_the_product_set_and_the_arv2_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            ws, project_id = project.workspace_id, project.project_id

            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert facts.icp is None and facts.product_set is None and facts.discovery is None
            assert facts.research == () and facts.account_count == 0

            # One account in the project, one discovery run with two candidates (one approved),
            # one research run with one account job (stage synthesis) and two person jobs.
            account_id = await _seed_account(conn, project, "Goodman Campbell")
            project_run_id = await _seed_project_run(conn, project)
            discovery_run = await _seed_discovery_run(
                conn, project, project_run_id, asked=20, found_strict=10, found_relaxed=3
            )
            await _seed_candidate(
                conn,
                project,
                discovery_run,
                "goodman.org",
                disposition="pass",
                decision="approved",
            )
            await _seed_candidate(
                conn, project, discovery_run, "acme.org", disposition="pending", judged=False
            )
            # Stamped before any gate was asked: not pending, and not checked either — so
            # `verified` must stay at the one candidate that actually carries a verdict.
            await _seed_candidate(
                conn,
                project,
                discovery_run,
                "dupe.org",
                disposition="duplicate_of_existing",
                judged=False,
            )
            # A company a ``must_not`` gate excluded: judged (so verified), never shown, and
            # counted on its own line — and the run says why it ended.
            await _seed_candidate(conn, project, discovery_run, "rival.org", disposition="pending")
            await conn.execute(
                text(
                    "UPDATE arv2_discovery_candidate SET disposition = 'excluded', "
                    "excluded_by_gate = 'sells_it' WHERE run_id = :run AND domain = 'rival.org'"
                ),
                {"run": discovery_run},
            )
            await conn.execute(
                text("UPDATE arv2_discovery_run SET end_reason = 'dry' WHERE run_id = :run"),
                {"run": discovery_run},
            )
            research_run = await _seed_research_run(conn, project, project_run_id)
            await _seed_job(
                conn,
                project,
                research_run,
                account_id,
                subject_type="account",
                status="in_progress",
                stage="synthesis",
            )
            await _seed_job(
                conn,
                project,
                research_run,
                account_id,
                subject_type="person",
                status="not_started",
            )
            await _seed_job(
                conn,
                project,
                research_run,
                account_id,
                subject_type="person",
                status="completed",
            )

            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert facts.account_count == 1
            assert facts.discovery is not None
            assert (
                facts.discovery.found,
                facts.discovery.verified,
                facts.discovery.shown,
                facts.discovery.approved,
            ) == (13, 2, 1, 1)
            assert (facts.discovery.excluded, facts.discovery.end_reason) == (1, "dry")
            assert facts.discovery.asked == 20
            assert len(facts.research) == 1
            (job,) = facts.research[0].jobs
            assert (job.account_name, job.status, job.stage, job.person_jobs) == (
                "Goodman Campbell",
                "in_progress",
                "synthesis",
                2,
            )

    run_async(scenario())


async def _seed_submission(
    conn: AsyncConnection,
    project: Project,
    artifacts: DurableAgentArtifactStore,
    *,
    label: str,
) -> UUID:
    """One really-submitted turn, because the pin's anchor is a submission row."""

    principal = await seed_principal(
        conn,
        workspace_id=project.workspace_id,
        user_id=f"usr-pcf-{label}",
    )
    thread_id = f"thr-pcf-{label}-{uuid4().hex[:8]}"
    await create_thread(
        conn,
        thread_id=thread_id,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        created_by_user_id=principal.user_id,
        created_via_membership_id=principal.membership_id,
    )
    message = await artifacts.persist_body(
        workspace_id=project.workspace_id,
        data=f"project files turn {label}".encode(),
        media_type="text/plain",
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=project.workspace_id,
        brand_id=project.brand_id,
        project_id=project.project_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=message.artifact_key,
        content_sha256=message.sha256,
        actor="human",
    )
    turn_id = uuid4()
    _, created = await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        submitted_by_user_id=principal.user_id,
        submitted_via_membership_id=principal.membership_id,
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=message.artifact_key,
        message_sha256=message.sha256,
        idempotency_key=f"pcf-{label}-{turn_id}",
    )
    assert created is True
    return turn_id


def test_the_project_files_pin_is_insert_once_and_serves_verified_bytes() -> None:
    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            ws, project_id = project.workspace_id, project.project_id
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            turn_id = await _seed_submission(conn, project, artifacts, label="pin")
            calls = 0

            async def compile_v1() -> list[CompiledProjectFile]:
                nonlocal calls
                calls += 1
                return [
                    # The summaries are deliberately NOT the files' first prose lines: the index
                    # must render what the compiler wrote, never re-derive a line of its own.
                    CompiledProjectFile(
                        "status.md",
                        "project-status",
                        b"# Project status\n\nv1\n",
                        None,
                        "compiled",
                        "ICP, products, accounts, as of this turn.",
                    ),
                    CompiledProjectFile(
                        "decisions.md",
                        "project-decisions",
                        b"# Project decisions\n\nnone\n",
                        None,
                        "compiled",
                        "What the human told this project, in their words.",
                    ),
                ]

            async def compile_v2() -> list[CompiledProjectFile]:
                raise AssertionError("a pinned turn never recompiles")

            pin, created = await load_or_create_project_files_pin(
                conn,
                artifacts,
                workspace_id=ws,
                turn_id=turn_id,
                project_id=project_id,
                compile=compile_v1,
            )
            assert created and calls == 1
            assert [f.path for f in pin.files] == ["decisions.md", "status.md"]

            again, created_again = await load_or_create_project_files_pin(
                conn,
                artifacts,
                workspace_id=ws,
                turn_id=turn_id,
                project_id=project_id,
                compile=compile_v2,
            )
            assert not created_again and again == pin

            files = await read_pinned_project_files(conn, storage, pin=pin)
            assert [f.body for f in files] == [
                b"# Project decisions\n\nnone\n",
                b"# Project status\n\nv1\n",
            ]
            seeds = project_seed_files(files)
            assert [s.path for s in seeds] == [
                "inputs/project/decisions.md",
                "inputs/project/status.md",
            ]
            assert all(s.media_type == "text/markdown" for s in seeds)

            card = compile_project_files_index_card(project_id=project_id, files=files)
            assert card.card_kind == "project_files_index"
            assert card.files[1].workspace_path == "inputs/project/status.md"
            # The index renders the PINNED summary, not a line re-derived from the bytes. A
            # section-structured file's first prose line is one section's content, so a card that
            # re-derived it would describe ``status.md`` as whatever its first section says.
            assert card.files[1].summary == "ICP, products, accounts, as of this turn."
            assert card.files[0].summary == "What the human told this project, in their words."
            assert summary_of(files[1].body) == "v1"
            assert card.content_sha256().startswith("sha256:")
            # ``summary_of`` stays the rule for prose documents (plan 2), heading-skipping and
            # bounded.
            assert summary_of(b"# Project status\n\n" + b"x" * 200) == "x" * 159 + "…"
            assert summary_of(b"# Only a heading\n") == ""

            # The pin, not the store, says what this turn's bytes are: a ref whose digest is
            # not the digest of the blob it names is refused even though the blob is intact.
            swapped = pin.model_copy(
                update={
                    "files": (
                        pin.files[0].model_copy(
                            update={"artifact_sha256": pin.files[1].artifact_sha256}
                        ),
                        pin.files[1],
                    )
                }
            )
            with pytest.raises(ProjectFilesPinConflict, match="pinned digest"):
                await read_pinned_project_files(conn, storage, pin=swapped)

            # a moved blob is a loud refusal, not a silently different seed
            storage.blobs[pin.files[0].artifact_key] = b"tampered"
            with pytest.raises(ProjectFilesPinConflict, match="read as it was pinned"):
                await read_pinned_project_files(conn, storage, pin=pin)

    run_async(scenario())


_ANSWER = "We only want independent GI groups in the Midwest, and hospital-owned practices are out."
_QUOTE = "independent GI groups in the Midwest"


def test_project_decisions_quote_a_recorded_statement_and_drop_erased_evidence() -> None:
    """The real write path, end to end: ``record_statement`` → ``load_project_decisions``.

    ``volunteered_statement`` stores offsets and a hash, never the words, so the only proof the
    decisions file says what the client said is a round trip through the captured artifact. The
    erasure half is the other half of that contract: DSAR must shorten the file, never break it.
    """

    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            ws, project_id = project.workspace_id, project.project_id
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            ref = await artifacts.persist_body(
                workspace_id=ws, data=_ANSWER.encode(), media_type="text/plain"
            )
            captured = await submit_onboarding_input(
                conn,
                workspace_id=ws,
                brand_id=project.brand_id,
                project_id=project_id,
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=ref.artifact_key,
                content_sha256=ref.sha256,
                actor="human",
            )
            start = _ANSWER.index(_QUOTE)
            await record_statement(
                conn,
                onboarding_input_id=captured.onboarding_input_id,
                workspace_id=ws,
                brand_id=project.brand_id,
                project_id=project_id,
                route_kind=StatementRoute.PROJECT_STATE,
                route_key="target_segment",
                quote=_QUOTE,
                quote_start=start,
                quote_end=start + len(_QUOTE),
                created_by_actor="human",
            )

            items = await load_project_decisions(
                conn, artifacts, workspace_id=ws, project_id=project_id
            )
            assert [(item.route_key, item.quote) for item in items] == [("target_segment", _QUOTE)]
            assert f'- **target_segment** — "{_QUOTE}"' in render_decisions_markdown(items)

            # DSAR erases the captured turn: the item drops, the file still compiles.
            await mark_erased(conn, ref.artifact_key)
            assert (
                await load_project_decisions(
                    conn, artifacts, workspace_id=ws, project_id=project_id
                )
                == ()
            )
            assert "Nothing recorded yet." in render_decisions_markdown(())

    run_async(scenario())


async def _seed_foreign_candidate(
    conn: AsyncConnection,
    foreign: Project,
    run_id: UUID,
    domain: str,
    *,
    disposition: str,
) -> None:
    """A candidate row stamped with another workspace, inside this project's run.

    ``arv2_discovery_candidate.run_id`` is a single-column FK and nothing forces a candidate's
    workspace to equal its run's, so this row is exactly what a mis-stamped write would leave
    behind — and exactly what an unscoped counter would add to the number the model reads.
    """

    await conn.execute(
        text(
            "INSERT INTO arv2_discovery_candidate (candidate_id, run_id, workspace_id, "
            "project_id, pass, domain, name, provider_snapshot_json, verdicts_json, disposition) "
            "VALUES (:candidate, :run, :ws, :project, 'strict', :domain, :name, "
            "CAST(:snapshot AS jsonb), CAST(:verdicts AS jsonb), :disposition)"
        ),
        {
            "candidate": uuid4(),
            "run": run_id,
            "ws": foreign.workspace_id,
            "project": foreign.project_id,
            "domain": domain,
            "name": domain,
            "snapshot": json.dumps({"domain": domain}),
            "verdicts": json.dumps([{"gate_key": "geography", "verdict": "pass"}]),
            "disposition": disposition,
        },
    )


def test_status_facts_are_workspace_scoped_and_keep_person_only_accounts() -> None:
    """Two properties the file's numbers depend on, below the run.

    *Scope*: the runs are workspace-filtered, but the candidates and jobs hanging off them are not
    forced into the run's workspace by any FK — a mis-stamped row would otherwise put a foreign
    workspace's counts, and a foreign account's name, into the file the model reads.

    *Person-only accounts*: a run that launched committee work for an account whose own account
    job ran earlier still has that account in it. Keying the run's lines on account jobs alone
    dropped both the account and its person jobs — including from the run header's denominator.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            ws, project_id = project.workspace_id, project.project_id
            foreign = await _seed_workspace_project(conn)
            foreign_account = await _seed_account(conn, foreign, "Foreign Clinic")

            project_run_id = await _seed_project_run(conn, project)
            discovery_run = await _seed_discovery_run(
                conn, project, project_run_id, asked=20, found_strict=10, found_relaxed=0
            )
            await _seed_candidate(conn, project, discovery_run, "ours.org", disposition="pass")
            await _seed_foreign_candidate(
                conn, foreign, discovery_run, "theirs.org", disposition="pass"
            )

            # A second research run with a person job only — its account's own job ran earlier.
            account_id = await _seed_account(conn, project, "Goodman Campbell")
            committee_run = await _seed_research_run(conn, project, project_run_id)
            await _seed_job(
                conn,
                project,
                committee_run,
                account_id,
                subject_type="person",
                status="completed",
            )
            # …and a job in that run stamped with another workspace's account.
            await _seed_job(
                conn,
                foreign,
                committee_run,
                foreign_account,
                subject_type="account",
                status="completed",
            )

            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert facts.project_name == "Project context files"
            assert facts.discovery is not None
            # One candidate is this workspace's; the foreign one is counted nowhere.
            assert (facts.discovery.verified, facts.discovery.shown) == (1, 1)
            (run,) = facts.research
            assert [
                (job.account_name, job.status, job.stage, job.person_jobs) for job in run.jobs
            ] == [("Goodman Campbell", "person research only", None, 1)]

    run_async(scenario())


def test_status_facts_refuse_a_project_that_is_not_this_workspaces() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            other = await _seed_workspace_project(conn)
            with pytest.raises(ValueError, match="does not exist in this workspace"):
                await load_project_status_facts(
                    conn,
                    workspace_id=other.workspace_id,
                    project_id=project.project_id,
                )

    run_async(scenario())


def test_a_pinned_path_must_be_materializable_and_a_compiled_set_cannot_repeat_one() -> None:
    """Both refusals happen where a refusal is still useful — before the insert-once pin.

    A pin is read *before* the compiler runs, so anything that survives into the row fails every
    later attempt of that turn identically, forever: an absolute or dot-relative path fails in
    ``WorkspaceSeedFile``, and two files claiming one path silently seed whichever lands second.
    """

    for bad in ("/status.md", "../status.md", "a//b.md", "a\\b.md"):
        with pytest.raises(ValidationError):
            ProjectFileRef(
                path=bad,
                kind="project-status",
                version=None,
                status="compiled",
                summary="s",
                artifact_key="ws/" + "a" * 64,
                artifact_sha256="a" * 64,
            )
    # A newer worker's extra key is ignored rather than refused: the pin outlives one rollout.
    ref = ProjectFileRef.model_validate(
        {
            "path": "status.md",
            "kind": "project-status",
            "version": None,
            "status": "compiled",
            "summary": "s",
            "artifact_key": "ws/" + "a" * 64,
            "artifact_sha256": "a" * 64,
            "compiled_by": "a field this worker does not know",
        }
    )
    assert ref.path == "status.md"

    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            turn_id = await _seed_submission(conn, project, artifacts, label="dup")
            before = dict(storage.blobs)

            async def compile_duplicate() -> list[CompiledProjectFile]:
                return [
                    CompiledProjectFile("status.md", "project-status", b"a\n", None, "c", "s"),
                    CompiledProjectFile("status.md", "project-status", b"b\n", None, "c", "s"),
                ]

            with pytest.raises(ProjectFilesPinConflict, match="one path twice"):
                await load_or_create_project_files_pin(
                    conn,
                    artifacts,
                    workspace_id=project.workspace_id,
                    turn_id=turn_id,
                    project_id=project.project_id,
                    compile=compile_duplicate,
                )
            # Nothing was persisted and nothing was pinned: the turn can still be retried.
            assert (
                await get_project_files_pin(
                    conn, workspace_id=project.workspace_id, turn_id=turn_id
                )
                is None
            )
            assert storage.blobs == before

    run_async(scenario())


def test_a_compiled_file_whose_bytes_were_erased_is_a_typed_project_files_refusal() -> None:
    """An erased content address must read as a project-context error, not a store ``ValueError``.

    Compiled files are content-addressed, so an erasure elsewhere in the workspace (DSAR over a
    deleted project, whose compiled files this plan's binding now reaches) can tombstone the exact
    key a later project's identical file would land on. The store refuses to resurrect it — the
    turn must say *which file* and in whose vocabulary, so an operator is not left holding
    "erased agent artifact bytes cannot be resurrected" with no path in it.
    """

    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            ws = project.workspace_id
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            turn_id = await _seed_submission(conn, project, artifacts, label="erased")
            body = b"# Project status\n\nan empty project\n"
            # The artifact row must exist before it can be tombstoned — as it would if an earlier
            # project had compiled this very file.
            existing = await artifacts.persist_body(
                workspace_id=ws, data=body, media_type="text/markdown"
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_artifact_tombstone "
                    "(workspace_id, artifact_key, subject_entity_id, reason_code) "
                    "VALUES (:ws, :key, :subject, 'erasure_request')"
                ),
                {"ws": ws, "key": existing.artifact_key, "subject": uuid4()},
            )
            await mark_erased(conn, existing.artifact_key)

            async def compile_erased() -> list[CompiledProjectFile]:
                return [
                    CompiledProjectFile("status.md", "project-status", body, None, "c", "s"),
                ]

            with pytest.raises(ProjectFilesPinConflict, match="'status.md' was erased"):
                await load_or_create_project_files_pin(
                    conn,
                    artifacts,
                    workspace_id=ws,
                    turn_id=turn_id,
                    project_id=project.project_id,
                    compile=compile_erased,
                )

    run_async(scenario())


_PROJECT_ICP = (
    "---\nkind: icp-definition\nicp_key: gi-dac\nstatus: proposed\n---\n\n"
    "Ambulatory GI groups that run their own anesthesia service line.\n\n"
    "A second paragraph the summary never reaches.\n"
)


async def _seed_project_document(
    conn: AsyncConnection,
    project: Project,
    artifacts: DurableAgentArtifactStore,
    *,
    path: str,
    body: str,
    version: int = 1,
    status: str = "proposed",
    kind: str = "icp-definition",
    artifact_sha256: str | None = None,
    project_scoped: bool = True,
) -> UUID:
    """One ``brand_knowledge_document`` row over really-stored bytes, scoped to this project.

    ``artifact_sha256`` overrides the digest the *row* claims (the table only checks its shape),
    which is how "the stored digest moved" is reproduced without corrupting a blob.
    """

    ref = await artifacts.persist_body(
        workspace_id=project.workspace_id, data=body.encode(), media_type="text/markdown"
    )
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            "path, kind, version, status, artifact_key, artifact_sha256, project_id) "
            "VALUES (:id, :ws, :brand, :folder, :path, :kind, :version, :status, :key, :sha, "
            ":project)"
        ),
        {
            "id": document_id,
            "ws": project.workspace_id,
            "brand": project.brand_id,
            "folder": path.split("/", 1)[0],
            "path": path,
            "kind": kind,
            "version": version,
            "status": status,
            "key": ref.artifact_key,
            "sha": artifact_sha256 or ref.sha256,
            "project": project.project_id if project_scoped else None,
        },
    )
    return document_id


def test_a_project_scoped_document_joins_the_project_folder_and_the_status_file() -> None:
    """A document the project authored for itself is a file the turn can open, and is listed.

    Two surfaces, one set of rows: ``status.md``'s "Project documents" section names it at the
    path it is materialized at, and ``current_project_documents`` hands the turn its verified
    bytes to seed there. The brand-level document in the same folder is not this project's, and
    must appear in neither — it materializes under the brand prefix and is listed by the brand's
    own card.
    """

    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            ws, project_id = project.workspace_id, project.project_id
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_project_document(
                conn, project, artifacts, path="audience/icp-gi-dac.md", body=_PROJECT_ICP
            )
            await _seed_project_document(
                conn,
                project,
                artifacts,
                path="audience/icp-gi.md",
                body="---\nkind: icp-definition\n---\n\nThe brand's own ICP.\n",
                project_scoped=False,
            )

            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert [(d.path, d.version, d.status) for d in facts.documents] == [
                ("audience/icp-gi-dac.md", 1, "proposed")
            ]
            rendered = render_status_markdown(facts)
            assert "- `project/audience/icp-gi-dac.md` — version 1, proposed, updated " in rendered
            assert "icp-gi.md" not in rendered

            files = await current_project_documents(
                conn, storage, workspace_id=ws, project_id=project_id
            )
            assert [(f.path, f.kind, f.version, f.status) for f in files] == [
                ("audience/icp-gi-dac.md", "icp-definition", 1, "proposed")
            ]
            # The bytes are the document's own, so the model reads what was authored.
            assert files[0].body == _PROJECT_ICP.encode()
            # …and the index line is its first line of prose. Front matter is the document's
            # metadata, not its subject: summarizing it would put "---" in every index line.
            assert files[0].summary == (
                "Ambulatory GI groups that run their own anesthesia service line."
            )
            assert summary_of(_PROJECT_ICP.encode()) == files[0].summary

    run_async(scenario())


def test_a_project_document_whose_stored_digest_moved_is_a_typed_refusal() -> None:
    """The row says which bytes this document is; bytes that are not those bytes are refused.

    Seeding a document whose content is not the content its durable row names would hand the
    model a file the project never authored, under a name the project trusts.
    """

    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            await _seed_project_document(
                conn,
                project,
                artifacts,
                path="audience/icp-gi-dac.md",
                body=_PROJECT_ICP,
                artifact_sha256="b" * 64,
            )
            with pytest.raises(ProjectFilesPinConflict, match="stored digest"):
                await current_project_documents(
                    conn,
                    storage,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                )

    run_async(scenario())


_PINNED_ICP = (
    "---\nkind: icp-definition\nicp_key: gi-dac\nstatus: confirmed\n---\n\n"
    "The profile the human said yes to.\n"
)
_NEWER_ICP = (
    "---\nkind: icp-definition\nicp_key: gi-dac\nstatus: proposed\n---\n\n"
    "The revision the agent drafted afterwards.\n"
)


async def _pin_project_icp(
    conn: AsyncConnection, project: Project, document_id: UUID, *, icp_key: str
) -> None:
    """Pin an already-seeded document, the way the confirmation gate's approval does."""

    row = (
        (
            await conn.execute(
                text(
                    "SELECT version, artifact_key, artifact_sha256 "
                    "FROM brand_knowledge_document WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        )
        .mappings()
        .one()
    )
    await pin_project_icp(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=project.brand_id,
        document=ConfirmedIcp(
            document_id=document_id,
            icp_key=icp_key,
            version=int(row["version"]),
            artifact_key=str(row["artifact_key"]),
            artifact_sha256=str(row["artifact_sha256"]),
            supersedes_document_id=document_id,
            product_selection_version=1,
        ),
        product_selection_version=1,
        pinned_by_user_id=_USER,
    )


def test_a_pinned_project_icp_is_seeded_beside_the_newer_version_of_its_path() -> None:
    """The brand scope's pin-vs-current rule, on the project side (review I2).

    The project confirms and pins its variant, the human asks for a change, and the agent authors
    the next version at the *same* path in the *same* scope. ``current_project_knowledge_refs`` is
    ``DISTINCT ON (path) … version DESC`` — current, not pinned — so compiling only that set would
    seed v2 at the plain path while the brand card still named v1 there, and the version the human
    actually confirmed (the one every launch researches against) would be readable nowhere in the
    workspace.

    So both are compiled, exactly as ``workspace_paths`` does it for the brand: the pinned version
    keeps the plain name and the newer one is offered beside it version-qualified. The mirror of
    ``test_brand_knowledge_context_db``'s
    ``test_a_newer_proposal_on_the_pinned_path_is_offered_but_never_called_confirmed``.
    """

    async def scenario() -> None:
        storage = _MemoryStorage()
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            ws, project_id = project.workspace_id, project.project_id
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            pinned_id = await _seed_project_document(
                conn,
                project,
                artifacts,
                path="audience/icp-gi-dac.md",
                body=_PINNED_ICP,
                version=1,
                status="confirmed",
            )
            await _pin_project_icp(conn, project, pinned_id, icp_key="gi-dac")
            await _seed_project_document(
                conn,
                project,
                artifacts,
                path="audience/icp-gi-dac.md",
                body=_NEWER_ICP,
                version=2,
                status="proposed",
            )

            # The project's *current* set serves only the newest version of the path…
            refs = await current_project_knowledge_refs(
                conn, workspace_id=ws, project_id=project_id
            )
            assert [(ref.path, ref.version) for ref in refs] == [("audience/icp-gi-dac.md", 2)]

            # …and status.md lists BOTH, each at the name it is really materialized under.
            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert [(d.path, d.version, d.status) for d in facts.documents] == [
                ("audience/icp-gi-dac.md", 1, "confirmed"),
                ("audience/icp-gi-dac.v2.md", 2, "proposed"),
            ]
            rendered = render_status_markdown(facts)
            assert "- Key: `gi-dac` (version 1) — `project/audience/icp-gi-dac.md`" in (rendered)
            assert "`project/audience/icp-gi-dac.md` — version 1, confirmed" in rendered
            assert "`project/audience/icp-gi-dac.v2.md` — version 2, proposed" in rendered

            files = await current_project_documents(
                conn, storage, workspace_id=ws, project_id=project_id
            )
            assert [(f.path, f.version, f.status) for f in files] == [
                ("audience/icp-gi-dac.md", 1, "confirmed"),
                ("audience/icp-gi-dac.v2.md", 2, "proposed"),
            ]

            # Composition: the file the agent opens at the plain path holds the PINNED bytes.
            turn_id = await _seed_submission(conn, project, artifacts, label="pinned-icp")

            async def compile() -> list[CompiledProjectFile]:
                return files

            pin, created = await load_or_create_project_files_pin(
                conn,
                artifacts,
                workspace_id=ws,
                turn_id=turn_id,
                project_id=project_id,
                compile=compile,
            )
            assert created is True
            seeded = {
                seed.path: seed.content
                for seed in project_seed_files(
                    await read_pinned_project_files(conn, storage, pin=pin)
                )
            }
            assert seeded["inputs/project/audience/icp-gi-dac.md"] == _PINNED_ICP.encode()
            assert seeded["inputs/project/audience/icp-gi-dac.v2.md"] == _NEWER_ICP.encode()

    run_async(scenario())


def test_the_personas_section_reads_this_projects_personas_runs_only() -> None:
    """M3: status.md is where a personas run becomes visible, and it is scoped like every read.

    ``read_current_run`` filters ``kind = 'full'``, so nothing else in the platform surfaces a
    personas run. These rows are therefore the only place a failed or gap-filled persona turn can
    be seen — and they are read by workspace *and* project, so another project's run (or another
    tenant's) can never appear under this project's heading.
    """

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            other = await seed_project(conn, project.workspace_id, name="Another project")
            ws, project_id = project.workspace_id, project.project_id
            artifacts = DurableAgentArtifactStore(
                storage=_MemoryStorage(), conn_factory=conn_session_factory(conn)
            )
            principal = await seed_principal(conn, workspace_id=ws, user_id=f"{_USER}-personas")
            document_id = await _seed_project_document(
                conn, project, artifacts, path="audience/icp-gi-dac.md", body=_PROJECT_ICP
            )
            other_document_id = await _seed_project_document(
                conn, other, artifacts, path="audience/icp-other.md", body=_PROJECT_ICP
            )

            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert facts.personas == ()
            assert "No persona run yet." in render_status_markdown(facts)

            settled = uuid4()
            await create_persona_run(
                conn,
                run_id=settled,
                workspace_id=ws,
                brand_id=project.brand_id,
                project_id=project_id,
                persona_icp_document_id=document_id,
                company_domain="acme.example",
                requested_by_user_id=principal.user_id,
            )
            await conn.execute(
                text(
                    "UPDATE onboarding_run SET status = 'completed_with_gaps', "
                    "finished_at = now() WHERE run_id = :id"
                ),
                {"id": settled},
            )
            # Another project's personas run, in the same workspace, must stay out of this file.
            await create_persona_run(
                conn,
                run_id=uuid4(),
                workspace_id=ws,
                brand_id=other.brand_id,
                project_id=other.project_id,
                persona_icp_document_id=other_document_id,
                company_domain="acme.example",
                requested_by_user_id=principal.user_id,
            )

            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert [(run.run_id, run.status) for run in facts.personas] == [
                (settled, "completed_with_gaps")
            ]
            assert facts.personas[0].finished_at is not None
            rendered = render_status_markdown(facts)
            assert f"- Run `{settled}`: completed_with_gaps, requested " in rendered
            assert "No persona run yet." not in rendered

    run_async(scenario())
