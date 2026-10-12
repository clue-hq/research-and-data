"""A real site document on the platform side (Wave 2 Lane A, Contracts 8 and the composer targets).

One project holds three design documents, each worked on by a leg of one of its threads: a Puck
``site``, a ``web`` page and a ``scene`` ad. The site is born the way a website leg births it
(``mint_empty_site_document`` through ``clue_design.documents.create_document``) and then written
twice through the same DAL the design API's site writes use (``update_web_document``), so it sits
at version 2 with real pages, a shell and a component whose id contains a dot.

Everything below reads those rows through the real paths — the projections app over HTTP for the
gallery feed, the artifacts library and the composer's prepare route; the real
``validated_context_refs`` over ``clue_design.documents.get_document``; the governed
``read_artifact@1`` tool; the project library compiler; the exit judge's own line builders; and the
design leg turn runner for the G2 account card. Nothing that decides the outcome is faked: the leg
runner's design lane is the suites' recording lane (no turn reaches a design runtime here), and
nothing else is stood in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_agents import AgentExecutionStatus, DomainObjectRef
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat.composer_context import (
    ContextReferenceError,
    context_ref_presentations,
    validated_context_refs,
)
from clue_api.chat.schemas import DesignArtifactListResponse, DesignArtifactResponse
from clue_api.design_leg_wiring import (
    _assistant_summary,
    _card_account_id,
    _exit_judge_artifact_lines,
    _exit_judge_tag_lines,
    batch_summary,
)
from clue_api.design_turn_targets import SiteTarget, resolve_site_targets
from clue_api.frontend_read.account_workspace import account_artifacts
from clue_api.frontend_read.artifacts import ArtifactListResponseV1
from clue_api.project_library import ensure_project_library
from clue_api.site_documents import mint_empty_site_document
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import EntityId
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.accounts import create_web_account
from clue_design.documents import (
    create_document,
    get_document,
    replace_scene,
    update_web_document,
)
from clue_design.enums import DesignRunKind
from tests._identity import seed_principal
from tests._workspace import seed_project as _seed_project_row
from tests.agents.workspace_helpers import make_factory
from tests.api.test_artifact_read_tool_db import _read, _seed_execution
from tests.api.test_design_artifact_feed_db import (
    USER_ID,
    _app,
    _client,
    _feed,
    _seed_leg,
    _seed_thread,
    _settings,
)
from tests.api.test_frontend_read_artifacts_db import _get as _get_library
from tests.api.test_genweb_web_turn_dispatch_db import (
    APPLIED_WEB_RESULT,
    _FakeLane,
    _run_turn,
    _seed_account,
    _seed_leg_conversation,
    _submit_message,
    _turn_facts,
)
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

SITE_ID = "doc_site_syracuse"
WEB_ID = "doc_web_spring"
SCENE_ID = "doc_scene_launch"
ACCOUNT_ID = "acct_syracuse"
ACCOUNT_NAME = "Syracuse City School District"

# --- the three documents -------------------------------------------------------------------------


def _site(*, with_dotted: bool) -> dict[str, Any]:
    """A two-page Puck site with a shell, in the site-kit's own JSON (the garner-syracuse fixture's
    shape, trimmed; the shell parts carry Contract 1's ``header``/``footer`` ids). ``with_dotted``
    adds the StatsBand whose id is ``proof.v2`` — Contract 1's id pattern has no dot, so only a
    write that skips the kit validator can store one, which is why the target parser must still
    read it as ONE id."""
    home = [
        {
            "type": "ClonedSection",
            "props": {
                "id": "hero",
                "fragmentId": "frg_hero",
                "slots": {"headline": "Your plan, measured"},
                "links": {},
                "replacements": {},
            },
        }
    ]
    if with_dotted:
        home.append(
            {
                "type": "StatsBand",
                "props": {
                    "id": "proof.v2",
                    "eyebrow": "Proof",
                    "heading": "What changed for districts like yours",
                    "intro": "",
                    "stats": [{"value": "12%", "label": "lower cost"}],
                    "source": "",
                    "align": "center",
                    "surface": "light",
                },
            }
        )
    return {
        "id": SITE_ID,
        "title": "Syracuse",
        "theme": {},
        "shell": {
            "header": {
                "id": "header",
                "preparedFor": ACCOUNT_NAME,
                "accountLogo": "",
                "ctaLabel": "Request the analysis",
                "ctaHref": "/analysis",
            },
            "footer": {
                "id": "footer",
                "legal": "© 2026. Prepared for Syracuse City School District.",
                "privacyHref": "https://example.com/privacy",
                "termsHref": "https://example.com/terms",
            },
        },
        "pages": {
            "/": {"root": {"props": {"title": "Syracuse"}}, "content": home},
            "/analysis": {
                "root": {"props": {"title": "The analysis"}},
                "content": [
                    {
                        "type": "FeatureSplit",
                        "props": {
                            "id": "what",
                            "eyebrow": "The analysis",
                            "heading": "What we looked at",
                            "headingRole": "h2",
                            "body": "Claims from the last plan year.",
                            "buttonLabel": "",
                            "buttonHref": "",
                            "image": "",
                            "imageSide": "right",
                            "surface": "light",
                        },
                    },
                    {
                        "type": "CtaBand",
                        "props": {
                            "id": "cta",
                            "heading": "See your numbers",
                            "body": "",
                            "buttonLabel": "Back to the overview",
                            "buttonHref": "/",
                            "surface": "dark",
                        },
                    },
                ],
            },
        },
        "agent_sections": {},
    }


def _web_page() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": WEB_ID,
        "title": "Spring launch page",
        "theme": {},
        "pages": [
            {
                "id": "home",
                "nodes": {"root": {"kind": "root"}, "frg_hero": {"kind": "fragment"}},
            }
        ],
    }


def _ad_scene() -> dict[str, Any]:
    return {
        "meta": {"id": SCENE_ID, "title": "Launch ad"},
        "pages": {"page_ad": {"id": "page_ad", "children": ["frame"]}},
        "nodes": {"frame": {"children": ["headline"]}, "headline": {"children": []}},
    }


async def _agent_write(conn: Any, workspace_id: str, document: dict[str, Any], base: int) -> None:
    """One agent write through the DAL the design API's site and web writes both use."""
    await update_web_document(
        conn,
        workspace_id=workspace_id,
        document_id=str(document["id"]),
        web_doc=document,
        intent="Site turn",
        checkpoint_label=None,
        operations=[],
        inverse_operations=None,
        expected_base_version=base,
    )


async def _seed(conn: Any) -> dict[str, Any]:
    """The project, its account, its three documents and one thread + leg per document."""
    project = await _seed_project_row(conn, f"ws-site-lane-a-{uuid4().hex[:8]}", name="Syracuse")
    ws = project.workspace_id
    await seed_principal(conn, workspace_id=ws, user_id=USER_ID)
    await create_web_account(
        conn,
        workspace_id=ws,
        account_id=ACCOUNT_ID,
        name=ACCOUNT_NAME,
        domain="syracuseschools.example",
        logo_asset_id=None,
        data={},
        notes=None,
    )
    born = await create_document(
        conn,
        workspace_id=ws,
        scene=mint_empty_site_document(document_id=SITE_ID, title="Syracuse", brand_kit_ref=None),
        doc_kind="site",
        account_id=ACCOUNT_ID,
    )
    assert (born["doc_kind"], born["current_version"]) == ("site", 0)
    await _agent_write(conn, ws, _site(with_dotted=False), base=0)
    await _agent_write(conn, ws, _site(with_dotted=True), base=1)
    # The web page and the ad each take one write, so every document has a version a ref can pin
    # (a ref's version is >= 1; a never-written document cannot be targeted at all).
    await create_document(conn, workspace_id=ws, scene=_web_page(), doc_kind="web")
    await _agent_write(conn, ws, _web_page(), base=0)
    await create_document(conn, workspace_id=ws, scene=_ad_scene())
    await replace_scene(
        conn,
        workspace_id=ws,
        document_id=SCENE_ID,
        scene=_ad_scene(),
        diagnostics=[],
        expected_base_version=0,
    )
    legs: dict[str, str] = {}
    for document_id in (SITE_ID, WEB_ID, SCENE_ID):
        thread_id = await _seed_thread(
            conn, workspace_id=ws, project_id=project.project_id, thread_id=f"thr_{document_id}"
        )
        legs[document_id] = await _seed_leg(
            conn,
            workspace_id=ws,
            project_id=project.project_id,
            thread_id=thread_id,
            document_id=document_id,
        )
    return {"project": project, "workspace_id": ws, "legs": legs}


def _design_ref(ws: str, object_type: str, object_id: str, version: int | None) -> DomainObjectRef:
    return DomainObjectRef(
        workspace_id=ws, object_type=object_type, object_id=object_id, version=version
    )


# --- 1. every list carries the site's own kind ---------------------------------------------------


def test_every_list_and_the_composer_carry_the_sites_own_kind() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws, project_id = seeds["workspace_id"], seeds["project"].project_id

            # The project's gallery feed (GET /api/v1/projects/{id}/design-artifacts).
            feed = await _feed(conn, workspace_id=ws, project_id=project_id)
            wires = DesignArtifactListResponse.model_validate({"data": feed}).data
            assert {wire.id: wire.kind for wire in wires} == {
                SITE_ID: "site",
                WEB_ID: "web",
                SCENE_ID: "ad",
            }
            site_item = next(item for item in feed if item["id"] == SITE_ID)
            assert site_item["title"] == "Syracuse"
            assert site_item["current_version_id"] == "2"
            assert site_item["origin_thread_id"] == f"thr_{SITE_ID}"
            assert site_item["account"]["id"] == ACCOUNT_ID
            assert site_item["account"]["name"] == ACCOUNT_NAME
            # A site has no page size and no ad artifact type: the card states nothing.
            assert (site_item["artifact_type"], site_item["width_px"], site_item["height_px"]) == (
                None,
                None,
                None,
            )

            # The single-artifact read the editor route resolves through.
            app = _app(conn, settings=_settings())
            async with _client(app) as client:
                one = await client.get(
                    f"/api/v1/projects/{project_id}/design-artifacts/{SITE_ID}",
                    headers={"X-Workspace-Id": ws},
                )
            assert one.status_code == 200, one.text
            assert DesignArtifactResponse.model_validate(one.json()).data.kind == "site"

            # The workspace-wide artifacts library (GET /frontend/v1/artifacts).
            library = await _get_library(conn, workspace_id=ws)
            assert library.status_code == 200, library.text
            parsed = ArtifactListResponseV1.model_validate(library.json())
            assert {row.id: row.kind for row in parsed.data.artifacts} == {
                SITE_ID: "site",
                WEB_ID: "web",
                SCENE_ID: "ad",
            }
            site_row = next(row for row in parsed.data.artifacts if row.id == SITE_ID)
            assert site_row.account is not None and site_row.account.id == ACCOUNT_ID
            assert site_row.project_title == "Syracuse"
            assert (site_row.width_px, site_row.height_px) == (None, None)

            # The account's own Artifacts tab (the account workspace read): the design account's
            # domain resolved it onto the workspace's account entity, and the site lists there.
            entity_id = (
                await conn.execute(
                    text(
                        "SELECT account_entity_id FROM design_account"
                        " WHERE workspace_id = :w AND account_id = :a"
                    ),
                    {"w": ws, "a": ACCOUNT_ID},
                )
            ).scalar_one()
            assert entity_id is not None
            assert site_row.account.account_entity_id == str(entity_id)
            tab = await account_artifacts(
                conn, workspace_id=ws, account_entity_id=EntityId(UUID(str(entity_id)))
            )
            assert [(item.id, item.type) for item in tab] == [(SITE_ID, "site")]

            # The composer. Its Microsites category is built in the browser from the feed's
            # `kind` (composer-context-catalog-site.test.ts pins site → "Microsite"
            # design_document); the backend half is the mention it accepts and the chip it
            # presents. The prepare route accepts the site's design_document mention at its
            # exact version (design refs are validated, never hydrated as entities) …
            async with _client(app) as client:
                prepared = await client.post(
                    f"/api/v1/projects/{project_id}/composer-context/prepare",
                    json={
                        "context_refs": [
                            {"object_type": "design_document", "object_id": SITE_ID, "version": 2}
                        ]
                    },
                    headers={"X-Workspace-Id": ws},
                )
                stale = await client.post(
                    f"/api/v1/projects/{project_id}/composer-context/prepare",
                    json={
                        "context_refs": [
                            {"object_type": "design_document", "object_id": SITE_ID, "version": 1}
                        ]
                    },
                    headers={"X-Workspace-Id": ws},
                )
            assert prepared.status_code == 200, prepared.text
            assert prepared.json()["data"]["context_entities"] == []
            assert stale.status_code == 409, stale.text
            assert stale.json()["error"]["code"] == "CONTEXT_REF_STALE"
            # … the submission validator accepts the same mention inside this project …
            mention = (_design_ref(ws, "design_document", SITE_ID, 2),)
            assert (
                await validated_context_refs(
                    conn, workspace_id=ws, refs=mention, project_id=project_id
                )
                == mention
            )
            # … and the transcript chip names it as a site.
            presented = await context_ref_presentations(
                conn,
                workspace_id=ws,
                refs=tuple(
                    _design_ref(ws, "design_document", doc, None)
                    for doc in (SITE_ID, WEB_ID, SCENE_ID)
                ),
            )
            assert presented == {
                ("design_document", SITE_ID): {"label": "Syracuse", "kind": "site"},
                ("design_document", WEB_ID): {"label": "Spring launch page", "kind": "web"},
                ("design_document", SCENE_ID): {"label": "Launch ad", "kind": "ad"},
            }

    run_async(scenario())


# --- 2. the Head of ABM still reads a site as "web" (founder Q1) ---------------------------------


def test_the_head_of_abm_reads_the_site_as_web(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws, project_id = seeds["workspace_id"], seeds["project"].project_id
            execution_id = await _seed_execution(
                conn, workspace_id=ws, project_id=project_id, key="hoa-turn"
            )

            # read_artifact@1, the governed tool the Head of ABM calls.
            kinds = {
                doc: (
                    await _read(conn, workspace_id=ws, execution_id=execution_id, artifact_id=doc)
                )["kind"]
                for doc in (SITE_ID, WEB_ID, SCENE_ID)
            }
            assert kinds == {SITE_ID: "web", WEB_ID: "web", SCENE_ID: "ad"}
            content = await _read(
                conn,
                workspace_id=ws,
                execution_id=execution_id,
                artifact_id=SITE_ID,
                section="content",
            )
            assert content["kind"] == "web"
            assert json.loads(content["body_text"]) == _site(with_dotted=True)
            assert content["body_truncated"] is False

            # The project library every thread mounts at project/ (artifacts/index.json).
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            root, factory, _sink = make_factory(tmp_path)
            snapshot = await ensure_project_library(
                conn, storage, artifacts, factory, workspace_id=ws, project_id=project_id
            )
            assert snapshot.index.artifacts == 3
            index = json.loads(
                (
                    root / ws / "projects" / project_id / "library" / "artifacts" / "index.json"
                ).read_text()
            )
            assert {entry["id"]: entry["doc_kind"] for entry in index["artifacts"]} == {
                SITE_ID: "web",
                WEB_ID: "web",
                SCENE_ID: "scene",
            }
            site_entry = next(entry for entry in index["artifacts"] if entry["id"] == SITE_ID)
            assert site_entry["title"] == "Syracuse"
            assert site_entry["current_version"] == 2

    run_async(scenario())


# --- 3. composer targets against the real stored site --------------------------------------------


async def _validate(
    conn: Any, seeds: dict[str, Any], document_id: str, version: int, nodes: tuple[str, ...]
) -> tuple[DomainObjectRef, ...]:
    """A focused-edit submission exactly as the chat router validates it: the open leg's whole
    document set, this project, the document ref plus its node refs at one version."""
    ws = seeds["workspace_id"]
    leg_documents = await design_legs.list_leg_documents(
        conn, workspace_id=ws, leg_id=seeds["legs"][document_id]
    )
    refs = (
        _design_ref(ws, "design_document", document_id, version),
        *(_design_ref(ws, "design_node", node, version) for node in nodes),
    )
    return await validated_context_refs(
        conn,
        workspace_id=ws,
        refs=refs,
        design_leg_document_ids=tuple(str(row["document_id"]) for row in leg_documents),
        project_id=seeds["project"].project_id,
    )


async def _refused_code(
    conn: Any, seeds: dict[str, Any], document_id: str, version: int, nodes: tuple[str, ...]
) -> str:
    with pytest.raises(ContextReferenceError) as refused:
        await _validate(conn, seeds, document_id, version, nodes)
    return refused.value.code


def test_site_targets_validate_against_the_stored_site() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            accepted_nodes = (
                "site:/analysis#what",
                "site:/analysis#what.heading",
                "site:shell#header.ctaLabel",
                "site:shell#footer",
                "site:/#proof.v2",
                "site:/#proof.v2.heading",
            )
            refs = await _validate(conn, seeds, SITE_ID, 2, accepted_nodes)
            assert tuple(ref.object_id for ref in refs) == (SITE_ID, *accepted_nodes)

            # What the dispatch will hand the site runtime, from the same stored row: the dotted
            # id is ONE component, and its prop is split off the last dot only.
            stored = await get_document(conn, workspace_id=ws, document_id=SITE_ID)
            resolved = resolve_site_targets(stored["scene"], refs)
            assert resolved is not None
            assert resolved.targets == (
                SiteTarget(route="/analysis", component_id="what", prop=None),
                SiteTarget(route="/analysis", component_id="what", prop="heading"),
                SiteTarget(route="shell", component_id="header", prop="ctaLabel"),
                SiteTarget(route="shell", component_id="footer", prop=None),
                SiteTarget(route="/", component_id="proof.v2", prop=None),
                SiteTarget(route="/", component_id="proof.v2", prop="heading"),
            )

            refusals = {
                "a selection made on the version before the agent's last write": (
                    1,
                    ("site:/analysis#what",),
                ),
                "a component the site does not have": (2, ("site:/analysis#nope",)),
                "a prop the component does not have": (2, ("site:/analysis#what.colour",)),
                "a component on the other page": (2, ("site:/#what",)),
                "a shell part that is not header or footer": (2, ("site:shell#sidebar.label",)),
                "the same target twice": (2, ("site:/analysis#what", "site:/analysis#what")),
                "a route that is not one of the site's pages": (2, ("site:/pricing#hero",)),
                "a route outside the route grammar": (2, ("site:/Analysis#what",)),
                "a web node id on a site": (2, ("frg_hero",)),
            }
            codes = {
                why: await _refused_code(conn, seeds, SITE_ID, version, nodes)
                for why, (version, nodes) in refusals.items()
            }
            assert codes == {
                "a selection made on the version before the agent's last write": (
                    "CONTEXT_REF_STALE"
                ),
                "a component the site does not have": "CONTEXT_REF_NOT_FOUND",
                "a prop the component does not have": "CONTEXT_REF_NOT_FOUND",
                "a component on the other page": "CONTEXT_REF_NOT_FOUND",
                "a shell part that is not header or footer": "CONTEXT_REF_NOT_FOUND",
                "the same target twice": "CONTEXT_REF_DUPLICATE",
                "a route that is not one of the site's pages": "CONTEXT_REF_NOT_FOUND",
                "a route outside the route grammar": "CONTEXT_REF_NOT_FOUND",
                "a web node id on a site": "CONTEXT_REF_RELATIONSHIP_MISMATCH",
            }

            # Regressions: a web document's targets and a scene document's targets validate as
            # before, against their own stored rows (both at version 1).
            web_nodes = ("frg_hero", "frg_hero#:nth-child(1) > :nth-child(2)")
            web_refs = await _validate(conn, seeds, WEB_ID, 1, web_nodes)
            assert tuple(ref.object_id for ref in web_refs) == (WEB_ID, *web_nodes)
            assert (
                await _refused_code(conn, seeds, WEB_ID, 1, ("site:/#hero",))
                == "CONTEXT_REF_NOT_FOUND"
            )
            scene_refs = await _validate(conn, seeds, SCENE_ID, 1, ("headline",))
            assert tuple(ref.object_id for ref in scene_refs) == (SCENE_ID, "headline")
            assert (
                await _refused_code(conn, seeds, SCENE_ID, 1, ("site:/#proof.v2",))
                == "CONTEXT_REF_NOT_FOUND"
            )

    run_async(scenario())


# --- 4. exit-judge and summary labels, and the G2 account card -----------------------------------


def test_the_exit_judge_names_the_site_a_web_page_with_its_account() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed(conn)
            ws = seeds["workspace_id"]
            lines: dict[str, tuple[str, ...]] = {}
            for document_id in (SITE_ID, WEB_ID, SCENE_ID):
                leg_documents = await design_legs.list_leg_documents(
                    conn, workspace_id=ws, leg_id=seeds["legs"][document_id]
                )
                lines[document_id] = await _exit_judge_artifact_lines(
                    conn, workspace_id=ws, leg_documents=leg_documents
                )
            assert lines == {
                SITE_ID: (f'1. "Syracuse" (web page) [account: {ACCOUNT_NAME}]',),
                WEB_ID: ('1. "Spring launch page" (web page)',),
                SCENE_ID: ('1. "Launch ad" (scene ad)',),
            }

            # A message that tags the site: the tag block reads the transcript's presentation
            # (kind "site") and still calls it a web page, numbered as the leg's artifact.
            site_leg_documents = await design_legs.list_leg_documents(
                conn, workspace_id=ws, leg_id=seeds["legs"][SITE_ID]
            )
            tags = await _exit_judge_tag_lines(
                conn,
                workspace_id=ws,
                focus_refs=(_design_ref(ws, "design_document", SITE_ID, 2),),
                leg_documents=site_leg_documents,
            )
            assert tags == ('design "Syracuse" (web page) (artifact 1)',)

            # The G2 card's account, read from the real stored rows.
            site = await get_document(conn, workspace_id=ws, document_id=SITE_ID)
            assert _card_account_id(site) == ACCOUNT_ID
            await conn.execute(
                text("UPDATE design_document SET account_id = :a WHERE id = :d"),
                {"a": ACCOUNT_ID, "d": SCENE_ID},
            )
            scene = await get_document(conn, workspace_id=ws, document_id=SCENE_ID)
            assert scene["account_id"] == ACCOUNT_ID
            assert _card_account_id(scene) is None, "a scene ad carries no account card"

            # The thread record over real run rows: a site run's result (Contract 7's shape, as
            # Lane B's executor writes it) reads like a website's and names its version once; the
            # ad beside it keeps the scene sentence with its version appended.
            site_result = {
                "schema_version": 1,
                "doc_kind": "site",
                "status": "applied",
                "outcome": "saved",
                "summary": "Built the analysis page.",
                "current_version": 3,
                "saved_version": 3,
                "stop_reason": None,
                "operations": [],
                "preview_paths": [],
            }
            scene_result = {
                "schema_version": 1,
                "status": "proposed",
                "acceptance_scope": "design",
                "current_version": 2,
            }
            for run_id, document_id, kind, result in (
                ("run_site_lane_a", SITE_ID, DesignRunKind.SITE_TURN, site_result),
                ("run_scene_lane_a", SCENE_ID, DesignRunKind.AGENT_TURN, scene_result),
            ):
                await design_runs.create_run(
                    conn, workspace_id=ws, run_id=run_id, document_id=document_id, kind=kind
                )
                await design_runs.set_run_result(
                    conn, workspace_id=ws, run_id=run_id, status="succeeded", result=result
                )
            site_run = await design_runs.require_run(
                conn, workspace_id=ws, run_id="run_site_lane_a"
            )
            scene_run = await design_runs.require_run(
                conn, workspace_id=ws, run_id="run_scene_lane_a"
            )
            assert _assistant_summary(site_run) == (
                f"Design turn applied on website document {SITE_ID} (now version 3): "
                "Built the analysis page."
            )
            scene_leg_documents = await design_legs.list_leg_documents(
                conn, workspace_id=ws, leg_id=seeds["legs"][SCENE_ID]
            )
            assert batch_summary(
                [(site_leg_documents[0], site_run), (scene_leg_documents[0], scene_run)]
            ).splitlines() == [
                f"Syracuse: Design turn applied on website document {SITE_ID} (now version 3): "
                "Built the analysis page.",
                "Launch ad: Design saved and accepted by the design review. (now version 2)",
            ]

    run_async(scenario())


async def _leg_with_document(
    conn: Any, tmp_path: Path, *, label: str, doc_kind: str, account_id: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A leg conversation pinned to one real document of ``doc_kind``, holding it at position 0."""
    seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label=label)
    if account_id is not None:
        await _seed_account(conn, workspace_id=seeds["workspace_id"], account_id=account_id)
    document_id = f"doc_{label}_{uuid4().hex[:8]}"
    scene = (
        mint_empty_site_document(document_id=document_id, title="Harbor & Sage", brand_kit_ref=None)
        if doc_kind == "site"
        else {"meta": {"id": document_id, "title": "Launch artboard"}}
    )
    document = await create_document(
        conn,
        workspace_id=seeds["workspace_id"],
        scene=scene,
        doc_kind=doc_kind,
        account_id=account_id,
    )
    await conn.execute(
        text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
        {"doc": document["id"], "leg": seeds["leg"]["id"]},
    )
    await design_legs.add_leg_documents(
        conn,
        workspace_id=seeds["workspace_id"],
        leg_id=str(seeds["leg"]["id"]),
        documents=[design_legs.LegDocumentSpec(document_id=str(document["id"]), position=0)],
    )
    seeds["leg"] = await design_legs.get_leg(
        conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
    )
    return seeds, document


async def _vanish_account(conn: Any, document_id: str) -> None:
    """Point the document at an account that does not exist. ``design_document_account_fk`` makes
    that impossible, so it is dropped inside this rolled-back transaction — the precedent
    ``test_genweb_web_turn_dispatch_db`` sets for reaching the G2 guard."""
    await conn.execute(
        text("ALTER TABLE design_document DROP CONSTRAINT design_document_account_fk")
    )
    await conn.execute(
        text("UPDATE design_document SET account_id = 'acct_vanished' WHERE id = :d"),
        {"d": document_id},
    )


def test_the_leg_turn_resolves_a_sites_account_card_before_dispatch(tmp_path: Path) -> None:
    """G2 through the real leg turn runner. The site runtime is not composed on this branch, so a
    site turn always ends refused BEFORE dispatch — which is exactly where G2 has already run. A
    site whose account resolves reaches the site-runtime refusal (G2 passed); a site whose account
    does not resolve stops at G2's own refusal (G2 read the site's account id); a scene ad naming
    the same unresolvable account is ignored by G2 and dispatches (scene ads carry no card).

    When Lane B composes the site runtime (B5), the resolvable case dispatches instead and should
    then assert the envelope's ``account_card`` (as the genweb suite does for web)."""

    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))

    async def resolvable() -> None:
        async with rollback_conn() as conn:
            seeds, _document = await _leg_with_document(
                conn, tmp_path / "ok", label="sitecard", doc_kind="site", account_id="acct_harbor"
            )
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="sitecard", message="Build the page for Northwind."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)
            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_site_runtime_not_composed"
            assert lane.envelopes == []
            assert await _turn_facts(conn, seeds, submission.turn_id) == {
                "runs": 0,
                "roles": ["user"],
                "commits": 0,
                "leg_state": "open_awaiting_user",
            }

    async def unresolvable_site() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _leg_with_document(
                conn, tmp_path / "gone", label="sitegone", doc_kind="site", account_id=None
            )
            await _vanish_account(conn, str(document["id"]))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="sitegone", message="Personalize the hero."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)
            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_account_unresolved"
            assert result.assistant_message is None
            assert lane.envelopes == []
            assert await _turn_facts(conn, seeds, submission.turn_id) == {
                "runs": 0,
                "roles": ["user"],
                "commits": 0,
                "leg_state": "open_awaiting_user",
            }

    async def unresolvable_scene() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _leg_with_document(
                conn, tmp_path / "scene", label="scenegone", doc_kind="scene", account_id=None
            )
            await _vanish_account(conn, str(document["id"]))
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(
                conn, seeds, label="scenegone", message="Make the headline two lines."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.outcome.failure_code is None
            assert len(lane.envelopes) == 1
            envelope = lane.envelopes[0]
            assert envelope.kind == "agent_turn"
            assert "account_card" not in envelope.config

    run_async(resolvable())
    run_async(unresolvable_site())
    run_async(unresolvable_scene())
