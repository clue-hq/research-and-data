"""Comments sent from a page's comment box reach that page's design agent (2026-10-29).

A person can leave comments on any site or web page of the project and send them, whatever is open
in the chat: no design session, or one on another page or ad. The server takes the message to the
page the comments are on — no model decides it:

* the submission check accepts comments (``design_node`` refs carrying a note) on a site or web
  page of this project that is not in the open leg (a page belongs to a project only through the
  legs that name it, so every such page has one);
* before routing the turn, the worker closes any open leg that does not hold the page, then
  reopens this chat's own earlier leg for the page, or opens a leg here that copies the page's
  last leg (its brief, brand pin and parent execution) — and the turn runs on it.

A canvas selection on an ad (a ``design_node`` with no note) stays what it was: valid only beside
the open leg's own document.
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import text

from clue_agents import DomainObjectRef
from clue_api.chat.composer_context import ContextReferenceError, validated_context_refs
from clue_api.design_comment_routing import commented_document_id, move_leg_to_commented_document
from clue_api.site_documents import mint_empty_site_document
from clue_design import legs as design_legs
from clue_design.documents import create_document, get_document
from tests.api.test_design_artifact_feed_db import _seed_thread
from tests.api.test_site_lane_a_scenarios_db import (
    SCENE_ID,
    SITE_ID,
    WEB_ID,
    _design_ref,
    _seed,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

HERO = "site:/analysis#what"


def _comment(ws: str, node: str, note: str, version: int) -> DomainObjectRef:
    return DomainObjectRef(
        workspace_id=ws, object_type="design_node", object_id=node, version=version, note=note
    )


def _site_comment_refs(ws: str, *, version: int = 2) -> tuple[DomainObjectRef, ...]:
    return (
        _design_ref(ws, "design_document", SITE_ID, version),
        _comment(ws, HERO, "1. Make this headline shorter", version),
    )


async def _events(conn: Any, turn_id: Any) -> list[tuple[str, dict[str, Any]]]:
    rows = (
        await conn.execute(
            text(
                "SELECT event_type, payload FROM agent_turn_event_stream "
                "WHERE turn_id = :turn ORDER BY sequence"
            ),
            {"turn": turn_id},
        )
    ).all()
    return [(str(row[0]), dict(row[1] or {})) for row in rows]


async def _move(conn: Any, seeds: dict[str, Any], thread_id: str, refs: tuple, label: str):
    ws = seeds["workspace_id"]
    turn_id = uuid5(NAMESPACE_URL, f"comment-routing:{label}")
    open_leg = await design_legs.get_open_leg_for_thread(conn, workspace_id=ws, thread_id=thread_id)
    moved = await move_leg_to_commented_document(
        conn,
        workspace_id=ws,
        project_id=seeds["project"].project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        focus_refs=refs,
        open_leg=open_leg,
    )
    return turn_id, moved


# --- which messages carry comments ---------------------------------------------------------


def test_only_noted_design_nodes_are_comments() -> None:
    ws = "ws"
    assert commented_document_id(_site_comment_refs(ws)) == SITE_ID
    selection = (
        _design_ref(ws, "design_document", SCENE_ID, 1),
        _design_ref(ws, "design_node", "headline", 1),
    )
    assert commented_document_id(selection) is None, "an ad selection carries no note"
    assert commented_document_id((_design_ref(ws, "design_document", SITE_ID, 2),)) is None
    assert commented_document_id(()) is None


# --- the submission check ------------------------------------------------------------------------


def test_comments_on_a_page_outside_the_open_leg_are_accepted() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            for leg_documents in ((), (WEB_ID,), (SCENE_ID,)):
                refs = await validated_context_refs(
                    conn,
                    workspace_id=ws,
                    refs=_site_comment_refs(ws),
                    design_leg_document_ids=leg_documents,
                    project_id=seeds["project"].project_id,
                )
                assert [ref.object_id for ref in refs] == [SITE_ID, HERO], leg_documents
            # The comment is still checked against the stored page.
            with pytest.raises(ContextReferenceError) as missing:
                await validated_context_refs(
                    conn,
                    workspace_id=ws,
                    refs=(
                        _design_ref(ws, "design_document", SITE_ID, 2),
                        _comment(ws, "site:/analysis#nope", "1. x", 2),
                    ),
                    design_leg_document_ids=(),
                    project_id=seeds["project"].project_id,
                )
            assert missing.value.code == "CONTEXT_REF_NOT_FOUND"

    run_async(scenario())


def test_a_selection_or_an_ad_outside_the_open_leg_is_still_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            refused = {
                "a site selection with no note": (
                    _design_ref(ws, "design_document", SITE_ID, 2),
                    _design_ref(ws, "design_node", HERO, 2),
                ),
                "a comment on an ad": (
                    _design_ref(ws, "design_document", SCENE_ID, 1),
                    _comment(ws, "headline", "1. bigger", 1),
                ),
            }
            for why, refs in refused.items():
                with pytest.raises(ContextReferenceError) as error:
                    await validated_context_refs(
                        conn,
                        workspace_id=ws,
                        refs=refs,
                        design_leg_document_ids=(WEB_ID,),
                        project_id=seeds["project"].project_id,
                    )
                assert error.value.code == "CONTEXT_REF_RELATIONSHIP_MISMATCH", why

    run_async(scenario())


def test_comments_on_a_page_never_made_in_a_design_session_are_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            orphan = "doc_site_orphan"
            await create_document(
                conn,
                workspace_id=ws,
                scene=mint_empty_site_document(
                    document_id=orphan, title="Orphan", brand_kit_ref=None
                ),
                doc_kind="site",
            )
            site = (await get_document(conn, workspace_id=ws, document_id=SITE_ID))["scene"]
            from clue_design.documents import update_web_document

            await update_web_document(
                conn,
                workspace_id=ws,
                document_id=orphan,
                web_doc={**site, "id": orphan},
                intent="Site turn",
                checkpoint_label=None,
                operations=[],
                inverse_operations=None,
                expected_base_version=0,
            )
            with pytest.raises(ContextReferenceError) as error:
                await validated_context_refs(
                    conn,
                    workspace_id=ws,
                    refs=(
                        _design_ref(ws, "design_document", orphan, 1),
                        _comment(ws, HERO, "1. shorter", 1),
                    ),
                    design_leg_document_ids=(),
                    project_id=seeds["project"].project_id,
                )
            # A page belongs to a project only through the legs that name it, so a page no
            # session ever made is in no project, and the project check refuses it.
            assert error.value.code == "CONTEXT_REF_NOT_FOUND"

    run_async(scenario())


# --- moving the leg -------------------------------------------------------------------------------


def test_a_message_without_comments_or_already_on_the_page_moves_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            site_thread = f"thr_{SITE_ID}"
            turn_id, moved = await _move(
                conn, seeds, site_thread, (_design_ref(ws, "design_document", WEB_ID, 1),), "plain"
            )
            assert moved is None
            turn_id, moved = await _move(conn, seeds, site_thread, _site_comment_refs(ws), "same")
            assert moved is None, "the open leg already holds the page"
            assert await _events(conn, turn_id) == []
            open_leg = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=ws, thread_id=site_thread
            )
            assert open_leg is not None and str(open_leg["id"]) == seeds["legs"][SITE_ID]

    run_async(scenario())


def test_this_chats_own_closed_leg_for_the_page_is_reopened() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            site_thread = f"thr_{SITE_ID}"
            site_leg = seeds["legs"][SITE_ID]
            await design_legs.close_leg(
                conn, workspace_id=ws, leg_id=site_leg, reason="locked", summary_refs={}
            )
            turn_id, moved = await _move(conn, seeds, site_thread, _site_comment_refs(ws), "reopen")
            assert moved is not None and str(moved["id"]) == site_leg
            assert moved["state"] == "open_awaiting_user"
            assert await _events(conn, turn_id) == [
                ("leg.reopened", {"leg_id": site_leg, "leg_turn": True})
            ]

            # A retry of the same turn finds the page on the open leg and does nothing more.
            _, again = await _move(conn, seeds, site_thread, _site_comment_refs(ws), "reopen")
            assert again is None

    run_async(scenario())


def test_another_chat_gets_a_leg_copied_from_the_pages_last_leg() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            source = seeds["legs"][SITE_ID]
            # The page's own leg as a real one looks: a frozen brief, a brand pin and the page's
            # own words on its document row.
            await conn.execute(
                text(
                    "UPDATE design_leg SET bundle_artifact_ref = 'bundle-key', "
                    "brand_kit_id = 'kit_1', brand_kit_version = 3 WHERE id = :leg"
                ),
                {"leg": source},
            )
            await conn.execute(
                text("UPDATE design_leg_document SET note = 'For Syracuse' WHERE leg_id = :leg"),
                {"leg": source},
            )
            source_row = await design_legs.get_leg(conn, workspace_id=ws, leg_id=source)
            new_thread = await _seed_thread(
                conn, workspace_id=ws, project_id=seeds["project"].project_id, thread_id="thr_new"
            )

            turn_id, moved = await _move(conn, seeds, new_thread, _site_comment_refs(ws), "copy")

            assert moved is not None and str(moved["id"]) != source
            assert moved["thread_id"] == new_thread
            assert moved["state"] == "open_awaiting_user"
            assert moved["opened_by_turn_id"] is None, "this turn is the leg's own design turn"
            assert str(moved["parent_execution_id"]) == str(source_row["parent_execution_id"])
            assert moved["bundle_artifact_ref"] == "bundle-key"
            assert (moved["brand_kit_id"], moved["brand_kit_version"]) == ("kit_1", 3)
            assert (moved["document_id"], moved["document_version_guard"]) == (SITE_ID, 2)
            documents = await design_legs.list_leg_documents(
                conn, workspace_id=ws, leg_id=str(moved["id"])
            )
            assert [(d["document_id"], d["position"], d["note"]) for d in documents] == [
                (SITE_ID, 0, "For Syracuse")
            ]
            assert await _events(conn, turn_id) == [
                ("leg.opened", {"leg_id": str(moved["id"]), "leg_turn": True})
            ]
            assert (await design_legs.get_leg(conn, workspace_id=ws, leg_id=source))[
                "state"
            ] == "open_awaiting_user", "the page's leg in its own chat is untouched"

    run_async(scenario())


def test_a_leg_on_another_page_is_closed_before_the_page_opens() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            web_thread = f"thr_{WEB_ID}"
            web_leg = seeds["legs"][WEB_ID]

            turn_id, moved = await _move(conn, seeds, web_thread, _site_comment_refs(ws), "switch")

            assert moved is not None and moved["document_id"] == SITE_ID
            closed = await design_legs.get_leg(conn, workspace_id=ws, leg_id=web_leg)
            assert (closed["state"], closed["close_reason"]) == ("closed", "abandoned")
            journal = (
                await conn.execute(
                    text("SELECT summary_refs FROM design_leg_exit_journal WHERE leg_id = :leg"),
                    {"leg": web_leg},
                )
            ).scalar_one()
            # Not a close the turn's own judge made: the crash re-entry read must never find it.
            assert "closing_turn_id" not in journal
            assert journal["moved_to_document_id"] == SITE_ID
            assert (
                await design_legs.get_leg_closed_by_turn(conn, workspace_id=ws, turn_id=turn_id)
                is None
            )
            open_leg = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=ws, thread_id=web_thread
            )
            assert open_leg is not None and str(open_leg["id"]) == str(moved["id"])
            assert await _events(conn, turn_id) == [
                ("leg.closed", {"leg_id": web_leg, "reason": "abandoned"}),
                ("leg.opened", {"leg_id": str(moved["id"]), "leg_turn": True}),
            ]

    run_async(scenario())


# --- end to end: the real turn worker -------------------------------------------------------------


class _JudgeMustNotRun:
    """Comments on the leg's one page are the ask on that page: the exit judge is never asked."""

    calls = 0

    async def __call__(self, **kwargs: Any) -> Any:
        del kwargs
        type(self).calls += 1
        raise AssertionError("a comment turn on the leg's one page must not be judged")


async def _worker_stage(conn: Any, storage_root: Any) -> dict[str, Any]:
    """A project with two chats. In chat A the Head of ABM opened a leg on the site (through the
    real ``open_design_leg``); chat B has never had one. The leg's own first turn is not run."""

    import json as _json
    from uuid import uuid4

    from clue_api.agent_turn_wiring import DbAgentHistoryStore, DurableAgentArtifactStore
    from clue_api.design_leg_tools import OpenDesignLegTool
    from clue_api.turn_action import derive_turn_action_ref
    from clue_core import new_operation_id
    from clue_design.documents import update_web_document
    from clue_storage import FsStorage
    from clue_toolbelt import ToolContext, ToolRegistry, invoke_tool
    from tests._identity import seed_principal
    from tests._workspace import seed_project
    from tests.api.test_p34_leg_loop_gate_db import NOW_UTC, USER_ID, _submit
    from tests.api.test_site_lane_a_scenarios_db import _site
    from tests.profiling.conftest import conn_session_factory

    workspace_id = f"ws_comments_{uuid4().hex[:8]}"
    project = await seed_project(conn, workspace_id, name="Comments")
    await seed_principal(
        conn, workspace_id=workspace_id, user_id=USER_ID, membership_id=f"wsm_p34g_{workspace_id}"
    )
    for thread in ("thr_a", "thr_b"):
        await conn.execute(
            text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p)"),
            {"id": thread, "ws": workspace_id, "p": project.project_id},
        )
    cf = conn_session_factory(conn)
    storage = FsStorage(storage_root / "artifacts")
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
    await create_document(
        conn,
        workspace_id=workspace_id,
        scene=mint_empty_site_document(document_id=SITE_ID, title="Syracuse", brand_kit_ref=None),
        doc_kind="site",
    )
    await update_web_document(
        conn,
        workspace_id=workspace_id,
        document_id=SITE_ID,
        web_doc=_site(with_dotted=False),
        intent="Site turn",
        checkpoint_label=None,
        operations=[],
        inverse_operations=None,
        expected_base_version=0,
    )
    seeds = {
        "workspace_id": workspace_id,
        "project": project,
        "thread_id": "thr_a",
        "artifacts": artifacts,
        "conn_factory": cf,
    }
    strategy = await _submit(conn, seeds=seeds, label="strategy", message="Make Syracuse a site.")
    manifest = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=_json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    execution = uuid5(NAMESPACE_URL, f"comments:{workspace_id}:execution")
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            "parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'human', :h, :h)"
        ),
        {"id": execution, "ws": workspace_id, "p": project.project_id, "h": "0" * 64},
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn (id, execution_id, workspace_id, project_id, thread_id, "
            "actor_id, role, workspace_root_id, profile_name, profile_version, profile_sha256, "
            "resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            "retention_class, requested_at, submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :e, :ws, :p, 'thr_a', :u, 'head_of_abm', 'root-c', 'head-of-abm', "
            "'v24', :sha, :key, :s256, :s256, 'test', :at, :u, :m)"
        ),
        {
            "id": strategy.turn_id,
            "e": execution,
            "ws": workspace_id,
            "p": project.project_id,
            "u": USER_ID,
            "sha": "0" * 64,
            "key": manifest.artifact_key,
            "s256": manifest.sha256,
            "at": NOW_UTC,
            "m": f"wsm_p34g_{workspace_id}",
        },
    )
    tools = ToolRegistry()
    tools.register(OpenDesignLegTool(conn_factory=cf, storage=storage), make_default=True)
    opened = await invoke_tool(
        tools,
        "open_design_leg",
        {
            "source_turn_ref": derive_turn_action_ref(strategy.turn_id),
            "brief": "A one-to-one microsite for Syracuse.",
            "document_id": SITE_ID,
        },
        ToolContext(
            workspace_id=workspace_id,
            actor="agent",
            conn_factory=cf,
            operation_id=new_operation_id(),
        ),
        idempotency_ttl_s=60,
    )
    return {
        **seeds,
        "leg_id": opened.references["leg_id"],
        "history": DbAgentHistoryStore(conn_factory=cf),
    }


def _worker(stage: dict[str, Any], storage_root: Any, lane: Any) -> Any:
    from clue_api.agent_registry_wiring import build_agent_profile_registry
    from clue_api.agent_turn_fleet_wiring import ProjectConversationTurnRunner
    from clue_api.agent_turn_wiring import DbAgentTurnJournal
    from clue_api.design_leg_wiring import DesignLegTurnRunner
    from clue_api.toolbelt_wiring import build_toolbelt
    from tests.api.conftest import hermetic_flag_env
    from tests.api.test_p34_leg_loop_gate_db import _HeadOfAbmMustNotRun
    from tests.api.test_p37_exit_bridge_db import _finisher

    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    cf = stage["conn_factory"]
    turns = DbAgentTurnJournal(conn_factory=cf)
    sentinel = _HeadOfAbmMustNotRun(turns)
    runner = ProjectConversationTurnRunner(
        engine=sentinel,  # type: ignore[arg-type]
        executor=None,  # type: ignore[arg-type]
        recipes=None,  # type: ignore[arg-type]
        starter=None,  # type: ignore[arg-type]
        parameters=None,  # type: ignore[arg-type]
        design_legs=DesignLegTurnRunner(
            profiles=registry,
            artifacts=stage["artifacts"],
            turns=turns,
            history=stage["history"],
            lane=lane,
            exit_judge=_JudgeMustNotRun(),
            finisher=_finisher(stage, storage_root),
            conn_factory=cf,
        ),
        conn_factory=cf,
        streaming=False,
    )
    return runner, sentinel


async def _comment_turn(conn: Any, stage: dict[str, Any], thread_id: str, label: str) -> Any:
    from tests.api.test_p34_leg_loop_gate_db import _submit

    ws = stage["workspace_id"]
    return await _submit(
        conn,
        seeds={**stage, "thread_id": thread_id},
        label=f"comment-{label}",
        message="See annotations.",
        focus_refs=(
            _design_ref(ws, "design_document", SITE_ID, 1),
            _comment(ws, HERO, "1. Make this headline shorter", 1),
        ),
    )


def test_a_comment_from_another_chat_opens_the_sites_leg_there_and_reaches_its_agent(
    tmp_path: Any,
) -> None:
    from clue_agents import AgentExecutionStatus
    from tests.api.test_genweb_web_turn_dispatch_db import _FakeLane
    from tests.api.test_site_leg_birth_db import APPLIED_SITE_RESULT

    async def scenario() -> None:
        async with rollback_conn() as conn:
            stage = await _worker_stage(conn, tmp_path)
            lane = _FakeLane(conn_factory=stage["conn_factory"], result=APPLIED_SITE_RESULT)
            runner, sentinel = _worker(stage, tmp_path, lane)
            _JudgeMustNotRun.calls = 0

            submission = await _comment_turn(conn, stage, "thr_b", "other-chat")
            result = await runner.run(
                turn_id=submission.turn_id, workspace_id=stage["workspace_id"]
            )

            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert sentinel.calls == 0, "no Head of ABM turn"
            assert _JudgeMustNotRun.calls == 0, "no exit judge"
            assert len(lane.envelopes) == 1
            envelope = lane.envelopes[0]
            assert str(envelope.document_id) == SITE_ID
            assert envelope.config["request"]["targets"] == [
                {"object_id": HERO, "note": "1. Make this headline shorter"}
            ]
            leg = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=stage["workspace_id"], thread_id="thr_b"
            )
            assert leg is not None and leg["document_id"] == SITE_ID
            assert str(leg["id"]) != stage["leg_id"]
            # The brief the Head of ABM wrote in chat A is the one this leg designs from.
            assert (
                envelope.config["delegation_bundle"]["brief"]
                == "A one-to-one microsite for Syracuse."
            )
            assert [event for event, _ in await _events(conn, submission.turn_id)][:1] == [
                "leg.opened"
            ]

    run_async(scenario())


def test_a_comment_after_the_session_closed_reopens_this_chats_leg(tmp_path: Any) -> None:
    from tests.api.test_genweb_web_turn_dispatch_db import _FakeLane
    from tests.api.test_site_leg_birth_db import APPLIED_SITE_RESULT

    async def scenario() -> None:
        async with rollback_conn() as conn:
            stage = await _worker_stage(conn, tmp_path)
            ws = stage["workspace_id"]
            await design_legs.close_leg(
                conn, workspace_id=ws, leg_id=stage["leg_id"], reason="locked", summary_refs={}
            )
            lane = _FakeLane(conn_factory=stage["conn_factory"], result=APPLIED_SITE_RESULT)
            runner, sentinel = _worker(stage, tmp_path, lane)
            _JudgeMustNotRun.calls = 0

            submission = await _comment_turn(conn, stage, "thr_a", "reopen")
            await runner.run(turn_id=submission.turn_id, workspace_id=ws)

            assert (sentinel.calls, _JudgeMustNotRun.calls) == (0, 0)
            assert [str(envelope.document_id) for envelope in lane.envelopes] == [SITE_ID]
            leg = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=ws, thread_id="thr_a"
            )
            assert leg is not None and str(leg["id"]) == stage["leg_id"]

    run_async(scenario())


# --- the submit route -----------------------------------------------------------------------------


def test_the_route_accepts_a_comment_with_no_leg_open_and_says_design_will_answer() -> None:
    import httpx
    from httpx import ASGITransport

    from tests._identity import seed_principal
    from tests.api.test_p34_speaker_projection_db import USER_ID, _app, _MemoryStorage, _settings

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            project_id = seeds["project"].project_id
            thread = await _seed_thread(
                conn, workspace_id=ws, project_id=project_id, thread_id="thr_free"
            )
            await seed_principal(
                conn, workspace_id=ws, user_id=USER_ID, membership_id=f"wsm_p34s_{ws}"
            )
            client = httpx.AsyncClient(
                transport=ASGITransport(
                    app=_app(conn, settings=_settings(), storage=_MemoryStorage())
                ),
                base_url="http://t",
            )
            refs = [
                {"object_type": "design_document", "object_id": SITE_ID, "version": 2},
                {
                    "object_type": "design_node",
                    "object_id": HERO,
                    "version": 2,
                    "note": "1. Make this headline shorter",
                },
            ]
            accepted = await client.post(
                f"/api/v1/projects/{project_id}/threads/{thread}/turns",
                json={"message": "See annotations.", "context_refs": refs},
                headers={"X-Workspace-Id": ws, "Idempotency-Key": "comment-route"},
            )
            assert accepted.status_code == 202, accepted.text
            assert accepted.json()["data"]["routed_to"] == "design"

            # A selection with no note, outside any leg, is still refused.
            refused = await client.post(
                f"/api/v1/projects/{project_id}/threads/{thread}/turns",
                json={
                    "message": "this",
                    "context_refs": [refs[0], {**refs[1], "note": None}],
                },
                headers={"X-Workspace-Id": ws, "Idempotency-Key": "selection-route"},
            )
            assert refused.status_code == 409, refused.text
            assert refused.json()["error"]["code"] == "CONTEXT_REF_RELATIONSHIP_MISMATCH"

    run_async(scenario())
