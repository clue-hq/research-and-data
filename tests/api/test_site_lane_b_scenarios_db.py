"""Business-logic scenarios for Wave 2 Lane B (the Puck site agent on the platform), platform side.

Task BV1b. BV1a (``subsystems/clue-design/apps/api/tests/test_site_lane_b_scenarios.py``) proved
the design side on its own. This file drives the path a marketer actually takes ACROSS the
platform/design boundary, in one test process, against the one test database:

    a chat message on a site document's design leg
      -> the platform's leg runner (``DesignLegTurnRunner.run_leg_turn``) builds the
         ``site_turn`` envelope and creates the run row
      -> the PRODUCTION design-leg lane (``clue_api.design_fleet.build_design_leg_lane_driver``:
         ``InlineDesignLaneDriver`` over the design side's ``DesignJobWorkHandler``, with the
         platform's spend drain, Langfuse factory and ``build_design_platform_reads_factory``)
         takes the work lease, claims the run row, runs the REAL ``execute_site_turn_job`` (real
         inputs, harness, site-kit validator, ``design_write_site`` save and Postgres
         checkpointer), lands the terminal row and tails the run's outbox onto the thread
      -> the runner reads the terminal row back: the thread's assistant message, the leg's
         state, the receipts; the forwarder's ``design.checkpoint`` frame; the artifact feeds.

THE ONE SEAM (as BV1a): only the chat model. ``lumen_agent.llm.init_model`` is patched to hand
back a ``site_fixtures.ScriptedModel``, and ``lumen_agent.llm.assert_model_supports_image_input``
(a network probe of the provider's catalogue) is patched with a recorder. One more seam stands in
for a real provider and is named where used: the account-logo vendor
(``lumen_agent.tools.logo_fetch.fetch_logo_family``). The account card carries a domain, so the
turn would otherwise call Brandfetch and the account's website; the recorder also proves the
frozen card reached the design side. Nothing else is faked: the lane, handler, executor, harness,
tools, ports, bundles, design store, platform reads and feeds are the shipped objects.

The design host's process-local handles are the ones a detached fleet worker builds
(``DesignTurnHost()`` defaults): storage from ``CLUE_STORAGE_FS_ROOT``, the engine cache from
``settings.lumen_asset_store_root`` and a fresh ``CoreClient``. This file points both roots at the
test's ``tmp_path``, so the production composition is used unchanged and every byte is
disposable. Hosted Langfuse is switched off before ``lumen_api.main`` is first imported (that
import installs the process's telemetry, and ``langfuse_enabled`` defaults on).

ROWS ARE COMMITTED for P1/P2. The design executor reads and writes through its own engine on its
own loop (``DesignStoreBridge``), so a rolled-back platform connection would be invisible to it.
Every row lives under a fresh ``ws_genweb_bv1b…`` workspace, and nothing is left queued or
running (see the hygiene note in the task report). P3's research rows are the exception: claims
need field registrations, and committing those would leak global rows into every other suite. So
P3 keeps the platform side (account, claims, display blocks, the reads' journal) in a rolled-back
connection that the REAL reads factory is bound to (as ``test_design_platform_reads_db`` binds
it), while the design side (site document, run row, session files) is committed under its own
``ws_bv1b_…`` workspaces.

Design-side test helpers (``site_fixtures``, ``site_kit_support``) are loaded BY PATH
(``_load_by_path``), as BV1a loads ``site_fixtures``; ``sys.path`` is not touched. BV1a's
``library_image`` (engine ingest -> ``register_engine_write`` -> governed
``design_register_asset_record``, with NO enrichment offer) is mirrored as ``_library_image``;
``POST /assets`` is never called.

A scenario that finds a defect is ``pytest.mark.xfail(strict=True, reason="DEFECT: …")``;
production code is never changed here (see the task report).
"""

from __future__ import annotations

import asyncio
import base64
import copy
import importlib.util
import io
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import Field
from sqlalchemy import text

from clue_agents import AgentExecutionStatus, AgentRole, DomainObjectRef
from clue_agents.registry import AgentCapabilityStatus
from clue_api.agent_registry_wiring import (
    C6_ACTIVE_PROFILE_VERSIONS,
    build_agent_profile_registry,
)
from clue_api.agent_turn_submission import message_artifact_ref
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.read_tools import DbArv2ReadService, claim_gate_reason
from clue_api.chat.schemas import DesignArtifactListResponse
from clue_api.chat.turn_events import TurnEventType, list_turn_events
from clue_api.design_fleet import build_design_leg_lane_driver, design_leg_lane_worker_id
from clue_api.design_leg_wiring import (
    _assistant_summary,
    design_leg_run_id,
    load_design_leg_history,
)
from clue_api.design_platform_reads import (
    DesignPlatformReadError,
    build_design_platform_reads_factory,
)
from clue_api.execution_wiring import build_tool_invoker
from clue_api.frontend_read.account_workspace import account_artifacts
from clue_api.frontend_read.artifacts import ArtifactListResponseV1
from clue_api.site_documents import mint_empty_site_document
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import load_settings
from clue_core import EntityId, EntityType
from clue_db import db_lifespan, transaction
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.accounts import create_web_account
from clue_design.documents import create_document
from clue_design.envelopes import DesignTurnEnvelope
from clue_research.claimstore.quality import inspectable_claims_by_ids
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.conftest import hermetic_flag_env
from tests.api.test_design_artifact_feed_db import USER_ID as FEED_USER_ID
from tests.api.test_design_artifact_feed_db import _feed
from tests.api.test_frontend_read_artifacts_db import _get as _get_library
from tests.api.test_genweb_web_turn_dispatch_db import (
    _card_payload,
    _runner,
    _seed_leg_conversation,
    _submit_message,
)
from tests.arv2.display._seed import write_claim
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DESIGN_APPS = _REPO_ROOT / "subsystems" / "clue-design" / "apps"


def _load_by_path(name: str, path: Path) -> Any:
    """A design-side test helper module, loaded by path (BV1a's way for ``site_fixtures``): the
    design suites' own ``conftest`` must not shadow the platform's, so their folders never join
    ``sys.path``."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


site_fixtures = _load_by_path(
    "site_fixtures", _DESIGN_APPS / "agent_runtime" / "tests" / "site_fixtures.py"
)
site_kit_support = _load_by_path(
    "site_kit_support", _DESIGN_APPS / "api" / "tests" / "site_kit_support.py"
)
call = site_fixtures.call
GARNER_KIT = json.loads((site_kit_support.FIXTURES / "kit.json").read_text(encoding="utf-8"))
GARNER_STORED = json.loads(
    (site_kit_support.FIXTURES / "garner-syracuse.json").read_text(encoding="utf-8")
)

ACCOUNT_ID = "acct_bv1b_syracuse"
ACCOUNT_NAME = "Syracuse City School District"
ACCOUNT_DOMAIN = "syracuseschools.example"
ACCOUNT_DATA = {"industry": "K-12 public schools", "employees": 4100}
ACCOUNT_NOTES = "Self-funded plan; renewal in July."

REQUEST_1 = "Make the proof section warmer."
NOTE_1 = "Warmer, and keep the 7.4%."
WARM_PROOF = "Your teachers keep their plan, and SCSD spends 7.4% less in year one."
REPLY_1 = "The proof heading now speaks to SCSD's teachers and keeps the 7.4%."
HUMAN_CTA = "Book SCSD's free analysis this month"
REQUEST_2 = "Lead the analysis page with what SCSD gets."
AGENT_WHAT = "What SCSD gets from the free analysis"
REPLY_2 = "The analysis page now leads with what SCSD gets."


# --- the model seam (BV1a's, mirrored) ----------------------------------------------------------


class Script(site_fixtures.ScriptedModel):
    """The spike's scripted model, recording what it was shown on every call."""

    seen: list = Field(default_factory=list)
    disable_streaming: bool = True

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def prompt(self) -> str:
        """The user turn the harness opened with (the composed prompt)."""
        return next(str(m.content) for m in self.seen[0] if isinstance(m, HumanMessage))

    def results(self) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for messages in self.seen:
            for message in messages:
                if isinstance(message, ToolMessage):
                    found[message.tool_call_id] = message.content
        return found

    def text_of(self, call_id: str) -> str:
        content = self.results()[call_id]
        if isinstance(content, str):
            return content
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )


_LINE_NUMBER = re.compile(r"^ *\d+(?:\.\d+)?\t", re.MULTILINE)


def _unnumbered(text_: str) -> str:
    """A ``read_file`` result without its ``cat -n`` line numbers: the file as the agent read it."""
    return _LINE_NUMBER.sub("", text_)


@dataclass
class ModelSeam:
    scripts: list[Script] = field(default_factory=list)
    built: list[dict] = field(default_factory=list)
    probed: list[str] = field(default_factory=list)

    def next(self, *steps: AIMessage) -> Script:
        script = Script(messages=iter(steps))
        self.scripts.append(script)
        return script


@pytest.fixture()
def model(monkeypatch: pytest.MonkeyPatch) -> ModelSeam:
    import lumen_agent.llm as llm

    seam = ModelSeam()
    handed: list[Script] = []

    def init_model(model_id, **kwargs):
        seam.built.append({"model_id": model_id, "role": kwargs.get("role")})
        pending = [script for script in seam.scripts if script not in handed]
        assert pending, "a site turn asked for a model but no script was queued"
        handed.append(pending[0])
        return pending[0]

    def probe(model_id, **kwargs):
        seam.probed.append(model_id)

    monkeypatch.setattr(llm, "init_model", init_model)
    monkeypatch.setattr(llm, "assert_model_supports_image_input", probe)
    return seam


@pytest.fixture()
def logos(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """The account-logo vendor seam: records who asked for which domain, finds no logo."""
    import lumen_agent.tools.logo_fetch as logo_fetch

    asked: list[dict] = []

    def fetch_logo_family(domain, *, company_name=None, cache=None, **_):
        asked.append({"domain": domain, "company_name": company_name})
        return SimpleNamespace(prepared=[], alternatives=[])

    monkeypatch.setattr(logo_fetch, "fetch_logo_family", fetch_logo_family)
    return asked


# --- the design side's process-local roots ------------------------------------------------------


@dataclass
class DesignEnv:
    root: Path
    storage: FsStorage
    agent_root: Path


@pytest.fixture(autouse=True)
def design_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DesignEnv:
    """One storage root for platform artifacts and design blobs (production shares one backend too),
    the engine cache and the agent's session folders under ``tmp_path``. A detached worker's
    ``DesignTurnHost()`` resolves exactly these."""
    from py_lumen_config import settings

    storage_root = tmp_path / "artifacts"  # ``_seed_leg_conversation``'s FsStorage root
    monkeypatch.setenv("CLUE_STORAGE_BACKEND", "fs")
    monkeypatch.setenv("CLUE_STORAGE_FS_ROOT", str(storage_root))
    monkeypatch.setattr(settings, "lumen_agent_trace_dir", None)
    monkeypatch.setattr(settings, "lumen_agent_workspace_root", tmp_path / "agent-workspace")
    monkeypatch.setattr(settings, "lumen_asset_store_root", tmp_path / "engine-cache")
    # Nothing here may drain the shared queue (an embedded worker would run other suites' jobs).
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)
    # No test may reach the Brandfetch vendor (the design conftest's D9 rule).
    monkeypatch.setattr(settings, "brandfetch_api_key", "")
    # Importing ``lumen_api.main`` installs the process's telemetry from the environment, and
    # ``langfuse_enabled`` defaults ON: with the repo's Langfuse keys exported, every scripted model
    # call would be reported to the hosted Langfuse. Off before the first import (``_design_app``
    # asserts it stayed off).
    monkeypatch.setenv("CLUE_LANGFUSE_ENABLED", "false")
    return DesignEnv(
        root=tmp_path, storage=FsStorage(storage_root), agent_root=tmp_path / "agent-workspace"
    )


def _design_app(env: DesignEnv) -> Any:
    """The design API, never entered: no lifespan, so no embedded fleet worker and no reaper. Used
    for its engine client and governed tools (library images) and for Lane A's editor routes (the
    human)."""
    from lumen_api.main import create_app

    from clue_obs.langfuse import langfuse_is_installed

    assert not langfuse_is_installed(), "a hosted Langfuse client is installed in this test process"
    site_kit_support.ensure_site_kit_dist()
    return create_app(env.root / "engine-cache", storage=env.storage)


def _session_folder(env: DesignEnv, workspace_id: str, document_id: str) -> Path:
    from clue_design.sessions import design_session_id

    return env.agent_root / "sessions" / design_session_id(workspace_id, document_id) / "workspace"


# --- Garner, the real brand, in a platform workspace (BV1a's setup, mirrored) -------------------


@dataclass
class Garner:
    kit_ref: dict
    images: dict[str, str]

    def site(self, document_id: str) -> dict:
        """Garner's garner-syracuse site (shell and kit sections) pinned to the stored kit; its two
        photos swapped for library images this workspace holds; its captured clones left out."""
        pages = copy.deepcopy(GARNER_STORED["pages"])
        for page in pages.values():
            page["content"] = [item for item in page["content"] if item["type"] != "ClonedSection"]
        text_ = json.dumps(pages)
        for old, new in self.images.items():
            text_ = text_.replace(old, new)
        return {
            "id": document_id,
            "title": ACCOUNT_NAME,
            "theme": {"brand_kit": dict(self.kit_ref)},
            "pages": json.loads(text_),
            "shell": copy.deepcopy(GARNER_STORED["shell"]),
            "agent_sections": {},
        }


def _library_image(app: Any, workspace_id: str, colour: tuple[int, int, int], label: str) -> dict:
    """BV1a's ``library_image``, mirrored: a photo in a workspace's library, made the way
    ``POST /assets`` makes one (engine ingest -> ``register_engine_write`` -> governed
    ``design_register_asset_record``) WITHOUT the asset-enrichment offer the route also makes."""
    from lumen_api.asset_custody import register_engine_write
    from lumen_api.design_store import DesignBlobStore, HybridRepository
    from PIL import Image

    from clue_design.storage import SOURCE_KEY_ASSET

    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), colour).save(buffer, format="PNG")
    asset_id = f"asset_{uuid4().hex[:12]}"
    cache_dir = Path(app.state.engine_cache_root) / workspace_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    ingested = app.state.core.ingest_asset(
        store_root=str(cache_dir),
        bytes_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
        asset_id=asset_id,
        label=label,
        declared_mime_type="image/png",
        filename=f"{label}.png",
        provenance={
            "created_by": "bv1b",
            "source_label": "upload",
            "confidence": None,
            "notes": [],
        },
        raise_on_error=False,
    )
    assert ingested.get("ok"), ingested
    record = ingested["asset"]["record"]
    register_engine_write(
        DesignBlobStore(app.state.storage, workspace_id),
        cache_dir,
        source_key=SOURCE_KEY_ASSET,
        record=record,
    )
    app.state.design_tools.invoke(
        "design_register_asset_record", {"record": record}, workspace_id=workspace_id, actor="human"
    )
    return HybridRepository(workspace_id=workspace_id).require_asset_record(asset_id)["asset"]


def _garner_kit(workspace_id: str, brand_id: str) -> dict:
    """Garner's real kit published as a ``design_brand_kit`` row of this workspace's brand."""
    from lumen_api.design_store import HybridRepository

    kit = HybridRepository(workspace_id=workspace_id).create_brand_kit(
        copy.deepcopy(GARNER_KIT), {}, [], "website", brand_id=brand_id
    )
    return {"id": kit["brand_kit"]["id"], "version": kit["brand_kit"]["version"]}


def _seed_garner(app: Any, workspace_id: str, brand_id: str) -> Garner:
    kit_ref = _garner_kit(workspace_id, brand_id)
    old: list[str] = []
    for page in GARNER_STORED["pages"].values():
        for item in page["content"]:
            image = (item.get("props") or {}).get("image")
            if item["type"] != "ClonedSection" and image and image not in old:
                old.append(image)
    images = {}
    for index, file in enumerate(old):
        asset = _library_image(
            app, workspace_id, ((index * 70) % 256, 140, 90), f"garner-photo-{index}"
        )
        images[file] = "/asset-store/" + asset["media"]["digest"]["value"]
    return Garner(kit_ref=kit_ref, images=images)


def _heading(site: dict, route: str, section_id: str) -> str:
    return next(
        item["props"]["heading"]
        for item in site["pages"][route]["content"]
        if item["props"]["id"] == section_id
    )


def _with_heading(site: dict, route: str, section_id: str, text_: str) -> dict:
    changed = copy.deepcopy(site)
    for item in changed["pages"][route]["content"]:
        if item["props"]["id"] == section_id:
            item["props"]["heading"] = text_
    return changed


def _edit_heading_call(site: dict, route: str, section_id: str, text_: str, n: int) -> dict:
    """An ``edit_file`` call the agent makes on the page file, changing one section's heading."""
    file = "/page.json" if route == "/" else f"/pages/{route.strip('/')}.json"
    old = _heading(site, route, section_id)
    return call(
        "edit_file",
        {"file_path": file, "old_string": json.dumps(old), "new_string": json.dumps(text_)},
        n,
    )


# --- the production design-leg lane --------------------------------------------------------------


class _WatchedLane:
    """The production lane, unchanged, with the envelopes it was handed kept for the assertions."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.envelopes: list[DesignTurnEnvelope] = []

    async def drive(self, *, envelope: DesignTurnEnvelope) -> None:
        self.envelopes.append(envelope)
        await self.inner.drive(envelope=envelope)

    async def drive_batch(self, *, envelopes: Any) -> None:
        self.envelopes.extend(envelopes)
        await self.inner.drive_batch(envelopes=envelopes)


def _production_lane(storage: FsStorage) -> _WatchedLane:
    """``fleet_main``'s composition: the journaled invoker over the full toolbelt with the ARV2
    reads, the design platform reads factory over it, and ``build_design_leg_lane_driver``. Must
    run on the loop that owns the pool (the reads factory captures it)."""
    settings = load_settings(_env_file=None)
    registry = build_toolbelt(
        storage=storage, settings=settings, arv2_reads=DbArv2ReadService(settings=settings)
    )
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=DbIdempotencyStore(),
        storage=storage,
        settings=settings,
    )
    reads = build_design_platform_reads_factory(
        invoker=invoker, storage=storage, conn_factory=transaction
    )
    driver = build_design_leg_lane_driver(enabled=True, platform_reads_factory=reads)
    assert driver is not None
    return _WatchedLane(driver)


# --- the site leg, committed ---------------------------------------------------------------------


@dataclass
class SiteLeg:
    seeds: dict[str, Any]
    app: Any
    document_id: str
    born: dict
    account_entity_id: str

    @property
    def workspace_id(self) -> str:
        return str(self.seeds["workspace_id"])

    @property
    def thread_id(self) -> str:
        return str(self.seeds["thread_id"])


async def _site_leg(env: DesignEnv, label: str) -> SiteLeg:
    """A project chat thread with an open design leg pinned to a real Garner-shaped site document
    whose account resolves (its design account, with a domain), committed:
    ``_seed_leg_conversation``'s conversation (workspace, project, principal, thread, delegating
    execution, delegation bundle, open leg), then the Garner kit and library photos on the design
    side, then the account, the document and the leg's document set (what ``open_design_leg``
    writes)."""
    async with transaction() as conn:
        seeds = await _seed_leg_conversation(conn, storage_root=env.root, label=label)
    # From here on every write commits on its own connection.
    seeds["conn_factory"] = transaction
    seeds["artifacts"] = DurableAgentArtifactStore(
        storage=seeds["storage"], conn_factory=transaction
    )
    workspace_id = str(seeds["workspace_id"])
    app = _design_app(env)
    garner = await asyncio.to_thread(_seed_garner, app, workspace_id, seeds["project"].brand_id)
    document_id = f"doc_site_bv1b_{uuid4().hex[:10]}"
    born = garner.site(document_id)
    async with transaction() as conn:
        await create_web_account(
            conn,
            workspace_id=workspace_id,
            account_id=ACCOUNT_ID,
            name=ACCOUNT_NAME,
            domain=ACCOUNT_DOMAIN,
            logo_asset_id=None,
            data=dict(ACCOUNT_DATA),
            notes=ACCOUNT_NOTES,
        )
        document = await create_document(
            conn, workspace_id=workspace_id, scene=born, doc_kind="site", account_id=ACCOUNT_ID
        )
        assert (document["doc_kind"], document["current_version"]) == ("site", 0)
        await conn.execute(
            text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
            {"doc": document_id, "leg": seeds["leg"]["id"]},
        )
        await design_legs.add_leg_documents(
            conn,
            workspace_id=workspace_id,
            leg_id=str(seeds["leg"]["id"]),
            documents=[design_legs.LegDocumentSpec(document_id=document_id, position=0)],
        )
        # The gallery/library reads authenticate as the feed suite's principal (Lane A's setup).
        await seed_principal(conn, workspace_id=workspace_id, user_id=FEED_USER_ID)
        seeds["leg"] = await design_legs.get_leg(
            conn, workspace_id=workspace_id, leg_id=seeds["leg"]["id"]
        )
        entity_id = (
            await conn.execute(
                text(
                    "SELECT account_entity_id FROM design_account"
                    " WHERE workspace_id = :w AND account_id = :a"
                ),
                {"w": workspace_id, "a": ACCOUNT_ID},
            )
        ).scalar_one()
    assert entity_id is not None
    return SiteLeg(
        seeds=seeds, app=app, document_id=document_id, born=born, account_entity_id=str(entity_id)
    )


async def _chat_message(
    leg: SiteLeg,
    lane: _WatchedLane,
    registry: Any,
    *,
    label: str,
    message: str,
    focus_refs: tuple[DomainObjectRef, ...] = (),
) -> tuple[Any, Any]:
    """One chat message on the leg, as the agent-turn worker runs it: the durable submission, then
    the leg runner (``_run_turn``'s body, with the reads in their own short transaction so no
    connection is held open while the design turn runs)."""
    async with transaction() as conn:
        submission = await _submit_message(conn, leg.seeds, label=label, message=message)
    async with transaction() as conn:
        open_leg = await design_legs.get_open_leg_for_thread(
            conn, workspace_id=leg.workspace_id, thread_id=leg.thread_id
        )
        assert open_leg is not None
        user_message_ref = await message_artifact_ref(conn, submission)
    result = await _runner(leg.seeds, registry, lane).run_leg_turn(
        submission=submission,
        leg=open_leg,
        user_message_ref=user_message_ref,
        focus_refs=focus_refs,
        card_payload=_card_payload(leg.seeds),
        stream=None,
    )
    return submission, result


async def _run_row(leg: SiteLeg, run_id: str) -> dict[str, Any]:
    async with transaction() as conn:
        run = await design_runs.get_run(conn, workspace_id=leg.workspace_id, run_id=run_id)
    assert run is not None
    return dict(run)


async def _run_columns(leg: SiteLeg, run_id: str) -> dict[str, Any]:
    """The run row's own columns: who claimed it, under which generation, for which leg."""
    async with transaction() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT kind, status, leased_by, lease_generation, leg_id,"
                        " checkpoint_thread_id, document_id FROM design_agent_run"
                        " WHERE workspace_id = :w AND run_id = :r"
                    ),
                    {"w": leg.workspace_id, "r": run_id},
                )
            )
            .mappings()
            .one()
        )
    return {key: (str(value) if key in ("kind", "leg_id") else value) for key, value in row.items()}


async def _frozen_envelope(run_id: str) -> DesignTurnEnvelope:
    async with transaction() as conn:
        job = await design_runs.get_run_by_work_id(
            conn, work_id=design_runs.work_id_for_run(run_id)
        )
    assert job is not None
    return DesignTurnEnvelope.model_validate(job["payload"])


async def _checkpoint_frames(leg: SiteLeg, turn_id: UUID) -> list[dict]:
    async with transaction() as conn:
        rows = await list_turn_events(conn, workspace_id=leg.workspace_id, turn_id=turn_id)
    return [
        dict(row.payload) for row in rows if row.event_type == TurnEventType.DESIGN_CHECKPOINT.value
    ]


async def _thread_messages(leg: SiteLeg) -> list[tuple[str, UUID, str]]:
    """The leg's thread record, as the next turn's envelope reads it: (role, turn, body)."""
    history = await load_design_leg_history(
        transaction,
        workspace_id=leg.workspace_id,
        thread_id=leg.thread_id,
        leg_parent_execution_id=leg.seeds["parent_execution_id"],
    )
    return [
        (item.role, item.turn_id, (await leg.seeds["artifacts"].read(item.body_ref)).decode())
        for item in history
    ]


async def _leg_state(leg: SiteLeg) -> str:
    async with transaction() as conn:
        row = await design_legs.get_leg(
            conn, workspace_id=leg.workspace_id, leg_id=leg.seeds["leg"]["id"]
        )
    return str(row["state"])


def _stored(leg: SiteLeg) -> dict:
    from lumen_api.design_store import HybridRepository

    return HybridRepository(workspace_id=leg.workspace_id).require_document(leg.document_id)


def _registry() -> Any:
    with hermetic_flag_env():
        return build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))


def _p1_script(model: ModelSeam, born: dict) -> Script:
    return model.next(
        AIMessage(
            content="",
            tool_calls=[
                call("read_file", {"file_path": "/brief.md"}, 1),
                call("read_file", {"file_path": "/page.json"}, 2),
                call("read_file", {"file_path": "/research/README.md"}, 3),
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                _edit_heading_call(born, "/", "proof", WARM_PROOF, 4),
                call("validate_page", {}, 5),
            ],
        ),
        AIMessage(content=REPLY_1),
    )


def _selection(leg: SiteLeg) -> tuple[DomainObjectRef, ...]:
    """What the composer hands the runner for a selected heading: the document, then the part with
    the person's note (ruling R9's ``design_node`` ref)."""
    return (
        DomainObjectRef(
            workspace_id=leg.workspace_id, object_type="design_document", object_id=leg.document_id
        ),
        DomainObjectRef(
            workspace_id=leg.workspace_id,
            object_type="design_node",
            object_id="site:/#proof.heading",
            note=NOTE_1,
        ),
    )


# =================================================================================================
# P1. A chat message becomes a saved website version, across the boundary.
# =================================================================================================


def test_p1_a_chat_message_becomes_a_saved_website_version_across_the_boundary(
    design_env: DesignEnv, model: ModelSeam, logos: list[dict]
) -> None:
    registry = _registry()

    async def scenario() -> None:
        async with db_lifespan():
            leg = await _site_leg(design_env, f"bv1b{uuid4().hex[:8]}")
            ws, doc = leg.workspace_id, leg.document_id
            lane = _production_lane(design_env.storage)
            script = _p1_script(model, leg.born)
            submission, result = await _chat_message(
                leg,
                lane,
                registry,
                label=f"{leg.seeds['thread_id']}-1",
                message=REQUEST_1,
                focus_refs=_selection(leg),
            )
            run_id = design_leg_run_id(submission.turn_id)

            # (a) The envelope the runner offered — the lane was handed it, and it is the run row's
            # frozen payload: a site turn on a fresh thread, the request with its target and note,
            # the account card by value.
            (envelope,) = lane.envelopes
            assert envelope == await _frozen_envelope(run_id)
            assert (envelope.kind, envelope.run_id, envelope.document_id) == (
                "site_turn",
                run_id,
                doc,
            )
            assert envelope.checkpoint_thread_id == run_id
            assert envelope.project_id == leg.seeds["project"].project_id
            assert envelope.config["request"] == {
                "prompt": REQUEST_1,
                "base_version": 0,
                "targets": [{"object_id": "site:/#proof.heading", "note": NOTE_1}],
            }
            assert envelope.config["account_card"] == {
                "account_id": ACCOUNT_ID,
                "name": ACCOUNT_NAME,
                "domain": ACCOUNT_DOMAIN,
                "logo_asset_id": None,
                "data": ACCOUNT_DATA,
                "notes": ACCOUNT_NOTES,
            }
            assert envelope.config["leg"]["thread_id"] == leg.thread_id
            assert envelope.config["leg"]["agent_turn_id"] == str(submission.turn_id)
            assert "ad_lane" not in envelope.config and "design_memory" not in envelope.config

            # The real harness ran under the production lane: one model, built for the site role,
            # probed once; the card reached the design side by value (the logo vendor was asked for
            # its domain and company, and found nothing).
            assert [b["role"] for b in model.built] == ["design_site"]
            assert model.probed == [model.built[0]["model_id"]]
            assert logos == [{"domain": ACCOUNT_DOMAIN, "company_name": ACCOUNT_NAME}]
            assert lane.inner.frames_forwarded == 1

            # (b) The prompt: the person's words, then the T15 selection block naming the part and
            # its note. The brief rides in brief.md; research is the card's account, unwritten.
            prompt = script.prompt()
            assert prompt.startswith(
                f"{REQUEST_1}\n\nThe person also pointed at parts of the site:\n"
            )
            assert (
                '- Page /, the section with id "proof", its "heading" field.'
                f' Their note: "{NOTE_1}"' in prompt
            ), prompt
            assert "DOCUMENT CHANGED" not in prompt
            assert "A coffee-roastery landing page." in script.text_of("call_1")
            assert _heading(leg.born, "/", "proof") in script.text_of("call_2")
            assert _unnumbered(script.text_of("call_3")) == (
                f"# {ACCOUNT_NAME}\n\nThere is no written research for this account yet."
            )
            assert script.text_of("call_5") == "VALID.", script.text_of("call_5")

            # (c) Version 1 holds the warmer heading, and nothing else moved; the agent wrote it.
            stored = await asyncio.to_thread(_stored, leg)
            assert stored["current_version"] == 1 and stored["doc_kind"] == "site"
            assert stored["scene"] == _with_heading(leg.born, "/", "proof", WARM_PROOF)

            # (d) The run row: claimed by the lane, terminal, the site's own result.
            run = await _run_row(leg, run_id)
            assert await _run_columns(leg, run_id) == {
                "kind": "site_turn",
                "status": "succeeded",
                # The lane's per-process worker id (2026-10-16; it was one id for every process).
                "leased_by": design_leg_lane_worker_id(),
                "lease_generation": 1,
                "leg_id": str(leg.seeds["leg"]["id"]),
                "checkpoint_thread_id": run_id,
                "document_id": doc,
            }
            result_json = run["result"]
            assert (
                result_json["status"],
                result_json["outcome"],
                result_json["doc_kind"],
                result_json["saved_version"],
                result_json["current_version"],
            ) == ("applied", "saved", "site", 1, 1)
            assert result_json["summary"] == REPLY_1
            assert len(result_json["model_calls"]) == len(script.seen) == 3
            # The production Postgres checkpointer held the graph under this request's own thread.
            async with transaction() as conn:
                checkpoints = (
                    await conn.execute(
                        text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread"),
                        {"thread": run_id},
                    )
                ).scalar_one()
            assert int(checkpoints) > 0
            # The design run's model calls, as receipts on the platform's own turn.
            async with transaction() as conn:
                receipts = (
                    await conn.execute(
                        text(
                            "SELECT sequence, role, status FROM agent_model_call"
                            " WHERE turn_id = :turn ORDER BY sequence"
                        ),
                        {"turn": submission.turn_id},
                    )
                ).all()
            assert [tuple(row) for row in receipts] == [
                (1, "design", "completed"),
                (2, "design", "completed"),
                (3, "design", "completed"),
            ]

            # (e) The thread: the person's words, then the real summary of the run (a website's).
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.outcome.failure_code is None
            assert result.assistant_message == _assistant_summary(run)
            assert result.assistant_message == (
                f"Design turn applied on website document {doc} (now version 1): {REPLY_1}"
            )
            messages = await _thread_messages(leg)
            assert [(role, body) for role, _turn, body in messages] == [
                ("user", REQUEST_1),
                ("assistant", result.assistant_message),
            ]
            assert await _leg_state(leg) == "open_awaiting_user"

            # (f) The save reached the chat as its design.checkpoint frame, naming the document
            # and version 1.
            assert await _checkpoint_frames(leg, submission.turn_id) == [
                {"document_id": doc, "version": 1}
            ]

            # (g) Lane A's reads list it as a site: the project's gallery feed, the workspace's
            # artifacts library, and the account's Artifacts tab.
            async with transaction() as conn:
                feed = await _feed(
                    conn, workspace_id=ws, project_id=leg.seeds["project"].project_id
                )
                library = await _get_library(conn, workspace_id=ws)
                tab = await account_artifacts(
                    conn, workspace_id=ws, account_entity_id=EntityId(UUID(leg.account_entity_id))
                )
            wires = DesignArtifactListResponse.model_validate({"data": feed}).data
            assert [(wire.id, wire.kind) for wire in wires] == [(doc, "site")]
            (item,) = feed
            assert (item["current_version_id"], item["origin_thread_id"]) == ("1", leg.thread_id)
            assert item["account"]["id"] == ACCOUNT_ID
            assert library.status_code == 200, library.text
            rows = ArtifactListResponseV1.model_validate(library.json()).data.artifacts
            assert [(row.id, row.kind) for row in rows] == [(doc, "site")]
            assert [(entry.id, entry.type) for entry in tab] == [(doc, "site")]

    run_async(scenario())


# =================================================================================================
# P2. A second message while a human edited in between.
# =================================================================================================


def test_p2_a_second_message_after_a_human_edit_saves_on_top_of_it(
    design_env: DesignEnv, model: ModelSeam, logos: list[dict]
) -> None:
    registry = _registry()

    async def scenario() -> None:
        async with db_lifespan():
            leg = await _site_leg(design_env, f"bv1b{uuid4().hex[:8]}")
            doc = leg.document_id
            lane = _production_lane(design_env.storage)
            _p1_script(model, leg.born)
            first, first_result = await _chat_message(
                leg,
                lane,
                registry,
                label=f"{leg.seeds['thread_id']}-1",
                message=REQUEST_1,
                focus_refs=_selection(leg),
            )
            assert first_result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            v1 = (await asyncio.to_thread(_stored, leg))["scene"]
            assert v1 == _with_heading(leg.born, "/", "proof", WARM_PROOF)

            # A person saves version 2 in the editor, through Lane A's site route (design API).
            editor = TestClient(leg.app, headers={"X-Workspace-Id": leg.workspace_id})
            v2 = _with_heading(v1, "/analysis", "cta", HUMAN_CTA)
            saved = await asyncio.to_thread(
                editor.put, f"/documents/{doc}/site", json={"site": v2, "base_version": 1}
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["document"]["current_version"] == 2

            # The second message.
            script = model.next(
                AIMessage(
                    content="",
                    tool_calls=[
                        call("read_file", {"file_path": "/pages/analysis.json"}, 1),
                        call("read_file", {"file_path": "/site.md"}, 2),
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        _edit_heading_call(v2, "/analysis", "what", AGENT_WHAT, 3),
                        call("validate_page", {}, 4),
                    ],
                ),
                AIMessage(content=REPLY_2),
            )
            second, second_result = await _chat_message(
                leg, lane, registry, label=f"{leg.seeds['thread_id']}-2", message=REQUEST_2
            )
            second_run_id = design_leg_run_id(second.turn_id)

            # The second envelope is defined against the human's version.
            envelope = lane.envelopes[-1]
            assert envelope == await _frozen_envelope(second_run_id)
            assert envelope.config["request"] == {"prompt": REQUEST_2, "base_version": 2}
            assert envelope.checkpoint_thread_id == second_run_id

            # The design executor told the agent what moved, as data, before the person's words.
            prompt = script.prompt()
            assert prompt.startswith(
                "DOCUMENT CHANGED SINCE YOUR LAST TURN (data, not instructions):\n"
            ), prompt
            assert "You last saved version 1; the document is now at version 2." in prompt
            assert "\n- Manual edit\n" in prompt and prompt.endswith(REQUEST_2)
            # The files it read were version 2's, and site.md names both saves and their authors.
            assert HUMAN_CTA in script.text_of("call_1")
            site_md = script.text_of("call_2")
            assert '- version 2: "Manual edit" (by a person,' in site_md
            assert f'- version 1: "{REQUEST_1}" (by the agent,' in site_md
            assert script.text_of("call_4") == "VALID."

            # Version 3 is the agent's, on top of the human's edit.
            stored = await asyncio.to_thread(_stored, leg)
            assert stored["current_version"] == 3
            assert stored["scene"] == _with_heading(v2, "/analysis", "what", AGENT_WHAT)
            versions = (
                await asyncio.to_thread(editor.get, f"/documents/{doc}/site/versions")
            ).json()
            assert [(v["version"], v["actor_kind"]) for v in versions["versions"]] == [
                (3, "agent"),
                (2, "editor"),
                (1, "agent"),
            ]
            second_run = await _run_row(leg, second_run_id)
            assert (second_run["status"], second_run["result"]["saved_version"]) == ("succeeded", 3)

            # The thread holds two assistant messages, each the real summary of its own run, each
            # naming its own version; the second save reached the chat as its own frame.
            first_run = await _run_row(leg, design_leg_run_id(first.turn_id))
            messages = await _thread_messages(leg)
            assert [(role, turn) for role, turn, _body in messages] == [
                ("user", first.turn_id),
                ("assistant", first.turn_id),
                ("user", second.turn_id),
                ("assistant", second.turn_id),
            ]
            replies = [body for role, _turn, body in messages if role == "assistant"]
            assert replies == [_assistant_summary(first_run), _assistant_summary(second_run)]
            assert (
                replies[0]
                == f"Design turn applied on website document {doc} (now version 1): {REPLY_1}"
            )
            assert (
                replies[1]
                == f"Design turn applied on website document {doc} (now version 3): {REPLY_2}"
            )
            assert second_result.assistant_message == replies[1]
            # The second envelope carried the first exchange by value, as the thread recorded it.
            assert envelope.config["history"] == [
                {"role": "user", "text": REQUEST_1},
                {"role": "assistant", "text": replies[0]},
            ]
            assert envelope.config["leg"]["first_turn_of_leg"] is False
            assert await _checkpoint_frames(leg, second.turn_id) == [
                {"document_id": doc, "version": 3}
            ]
            assert await _leg_state(leg) == "open_awaiting_user"

            # history.md (the agent's memory across requests) numbers the two requests.
            history = (
                _session_folder(design_env, leg.workspace_id, doc) / "history.md"
            ).read_text()
            assert [line for line in history.splitlines() if line.startswith("## ")] == [
                f"## 1. {REQUEST_1}",
                f"## 2. {REQUEST_2}",
            ]

    run_async(scenario())


# =================================================================================================
# P3. The research the site agent reads is exactly what the display gate allows, per workspace.
# =================================================================================================

ACCOUNT_A = "Premier Gastroenterology"
ACCOUNT_B = "Northwind Clinics"
SERVED_VALUE = [{"title": "Head of ABM"}, {"title": "ABM Manager"}]
SERVED_SOURCE = "https://premier-gi.example/careers"
SERVED_SPAN = "We are hiring a Head of ABM and an ABM Manager."
HELD_VALUE = {"what": "A payer billing dispute filed in March"}
HELD_SPAN = "The dispute with the payer over billing was filed in March."
SERVED_STATEMENT = "They are hiring a Head of ABM and an ABM Manager this quarter."
HELD_STATEMENT = "They are in a public billing dispute with a payer."
MISSING_STATEMENT = "Their board approved a new CRM budget."
B_STATEMENT = "Northwind is consolidating its scheduling vendors."


async def _seed_overview(
    conn: Any, *, workspace_id: str, account_id: Any, body: dict, cited: list[str]
) -> None:
    """One live legacy-lane ``display_block`` on the account's overview page (the read suites'
    seed)."""
    await conn.execute(
        text(
            "INSERT INTO display_block (workspace_id, subject_kind, subject_id, page, "
            "section_key, body_json, cited_claim_ids, model, prompt_version, recipe_version, "
            "generated_at) VALUES (:ws, 'account', :subject, 'overview', 'why-now', "
            "CAST(:body AS jsonb), CAST(:cited AS uuid[]), 'luna', 'v1+v1', 1, now())"
        ),
        {"ws": workspace_id, "subject": account_id, "body": json.dumps(body), "cited": cited},
    )


def _site_envelope(
    *, workspace_id: str, project_id: str, document_id: str, account_entity_id: str, title: str
) -> DesignTurnEnvelope:
    """A leg turn's site envelope, shaped as ``DesignLegTurnRunner._envelope`` freezes one: the
    delegation bundle names the document's research account as ``open_design_leg`` writes it."""
    run_id = f"run_site_bv1b_{uuid4().hex[:12]}"
    return DesignTurnEnvelope(
        kind="site_turn",
        work_id=design_runs.work_id_for_run(run_id),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=document_id,
        project_id=project_id,
        config={
            "request": {"prompt": "Build the account's page.", "base_version": 0},
            "delegation_bundle": {
                "brief": f"A 1:1 page for {title}.",
                "artifacts": [
                    {
                        "position": 0,
                        "title": title,
                        "note": "",
                        "account_id": account_entity_id,
                        "document_id": document_id,
                    }
                ],
            },
            "history": [],
            "leg": {
                "leg_id": str(uuid4()),
                "thread_id": f"thr_bv1b_{uuid4().hex[:8]}",
                "agent_turn_id": str(uuid4()),
                "first_turn_of_leg": True,
            },
            # The card a domain-less design account freezes: no logo lookup is attempted.
            "account_card": {
                "account_id": f"acct_{title.split()[0].lower()}",
                "name": title,
                "domain": None,
                "logo_asset_id": None,
                "data": {},
                "notes": None,
            },
        },
    )


def _executor_turn(host: Any, envelope: DesignTurnEnvelope) -> dict:
    """One site turn through the REAL executor, recorded the way the fleet records it (BV1a's
    ``open_run`` / ``run_turn`` / ``complete_turn``): the row born queued with its frozen envelope,
    claimed at generation 1, executed, completed under that generation. Runs on a worker thread."""
    from lumen_api.design_store import HybridRepository
    from lumen_api.main import execute_site_turn_job

    store = HybridRepository(workspace_id=envelope.workspace_id)
    store.create_run(
        envelope.run_id,
        envelope.document_id,
        kind="site_turn",
        payload=envelope.model_dump(mode="json"),
    )
    claimed = store._bridge._run(
        lambda conn: design_runs.claim_run_for_execution(
            conn, work_id=envelope.work_id, worker_id="worker_bv1b", lease_generation=1
        )
    )
    assert claimed is not None and claimed["status"] == "running"
    status, response, event_type, event_data = execute_site_turn_job(
        envelope, store=store, host=host, event_sink=lambda *_: None, lease_generation=1
    )
    store.complete_run(
        envelope.run_id, status, response, event_type, event_data, expected_generation=1
    )
    return store.require_run(envelope.run_id)


def _research_files(env: DesignEnv, envelope: DesignTurnEnvelope) -> dict[str, str]:
    folder = _session_folder(env, envelope.workspace_id, str(envelope.document_id)) / "research"
    return {path.name: path.read_text() for path in sorted(folder.iterdir())}


def _site_document(app: Any, workspace_id: str, brand_id: str, title: str) -> str:
    """The empty site a website leg births, pinned to Garner's kit, committed on the design side."""
    from lumen_api.design_store import HybridRepository

    kit_ref = _garner_kit(workspace_id, brand_id)
    document_id = f"doc_site_bv1b_{uuid4().hex[:10]}"
    HybridRepository(workspace_id=workspace_id).create_document(
        mint_empty_site_document(document_id=document_id, title=title, brand_kit_ref=kit_ref),
        doc_kind="site",
    )
    return document_id


def test_p3_the_research_a_site_agent_reads_is_what_the_display_gate_allows_per_workspace(
    design_env: DesignEnv, model: ModelSeam, logos: list[dict]
) -> None:
    ws_a, ws_b = f"ws_bv1b_a_{uuid4().hex[:10]}", f"ws_bv1b_b_{uuid4().hex[:10]}"

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            # Committed first, on their own connections: the two projects (workspace, brand,
            # project), then the design side's kit and empty site document in each. Nothing the
            # rolled-back connection writes below is a row the design side waits on.
            async with transaction() as committed:
                project_a = await seed_project(committed, ws_a, name="Premier GI")
                project_b = await seed_project(committed, ws_b, name="Northwind")
            app = _design_app(design_env)
            doc_a = await asyncio.to_thread(
                _site_document, app, ws_a, project_a.brand_id, ACCOUNT_A
            )
            doc_b = await asyncio.to_thread(
                _site_document, app, ws_b, project_b.brand_id, ACCOUNT_B
            )

            # Rolled back: A's account, its research page and the three ids it cites.
            account_a = await insert_account_entity(
                conn,
                canonical_name=ACCOUNT_A,
                primary_domain="premier-gi.example",
                workspace_id=ws_a,
            )
            await ensure_project_account(
                conn,
                workspace_id=ws_a,
                project_id=project_a.project_id,
                account_entity_id=account_a,
                added_via="manual",
            )
            claims: dict[str, str] = {}
            await write_claim(
                conn,
                claims,
                label="served",
                workspace_id=ws_a,
                entity_id=account_a,
                entity_type=EntityType.ACCOUNT,
                field_key="account.open_requisitions",
                value_json=SERVED_VALUE,
                source_url=SERVED_SOURCE,
                evidence_span=SERVED_SPAN,
            )
            await write_claim(
                conn,
                claims,
                label="held",
                workspace_id=ws_a,
                entity_id=account_a,
                entity_type=EntityType.ACCOUNT,
                field_key="account.reputation_risk",
                value_json=HELD_VALUE,
                source_url="https://news.example/payer-dispute",
                evidence_span=HELD_SPAN,
                outreach_safe=False,
            )
            served, held, missing = claims["served"], claims["held"], str(uuid4())
            await _seed_overview(
                conn,
                workspace_id=ws_a,
                account_id=account_a,
                cited=[served, held, missing],
                body={
                    "h1": "Why now",
                    "intro": [{"text": SERVED_STATEMENT, "claimIds": [served]}],
                    "items": [
                        {
                            "h2": "Watch-outs",
                            "body": [
                                {"text": HELD_STATEMENT, "claimIds": [held]},
                                {"text": MISSING_STATEMENT, "claimIds": [missing]},
                            ],
                        }
                    ],
                },
            )
            # The held claim is held by a real rule of the display gate, under the reads' settings.
            settings = load_settings(_env_file=None)
            loaded = await inspectable_claims_by_ids(
                conn, workspace_id=ws_a, claim_ids=[UUID(held)]
            )
            (held_claim,) = loaded.values()
            assert claim_gate_reason(held_claim, settings=settings) == "outreach_unsafe"

            # Rolled back: B's account, whose own research page cites A's claim ids.
            account_b = await insert_account_entity(
                conn,
                canonical_name=ACCOUNT_B,
                primary_domain="northwind-clinics.example",
                workspace_id=ws_b,
            )
            await ensure_project_account(
                conn,
                workspace_id=ws_b,
                project_id=project_b.project_id,
                account_entity_id=account_b,
                added_via="manual",
            )
            await _seed_overview(
                conn,
                workspace_id=ws_b,
                account_id=account_b,
                cited=[served, held],
                body={
                    "h1": "Why now",
                    "intro": [{"text": B_STATEMENT, "claimIds": [served, held]}],
                },
            )

            # The REAL reads, composed as fleet_main composes them, bound to this connection: the
            # full toolbelt's ARV2 reads behind the journaled invoker, and the reads factory the
            # fleet worker hands the design executor as ``host.platform_reads_factory``.
            cf = conn_session_factory(conn)
            registry = build_toolbelt(
                storage=design_env.storage,
                settings=settings,
                conn_factory=cf,
                arv2_reads=DbArv2ReadService(settings=settings, conn_factory=cf),
            )
            invoker = build_tool_invoker(
                registry=registry,
                idempotency_store=DbIdempotencyStore(conn_factory=cf),
                storage=design_env.storage,
                settings=settings,
                conn_factory=cf,
            )
            factory = build_design_platform_reads_factory(
                invoker=invoker, storage=design_env.storage, conn_factory=cf
            )
            from lumen_api.fleet_handler import DesignTurnHost

            host = DesignTurnHost(platform_reads_factory=factory)  # a detached worker's host

            # --- workspace A: a site turn's research files --------------------------------------
            envelope_a = _site_envelope(
                workspace_id=ws_a,
                project_id=project_a.project_id,
                document_id=doc_a,
                account_entity_id=str(account_a),
                title=ACCOUNT_A,
            )
            reads_a = factory(envelope_a)
            assert reads_a is not None
            answer = await asyncio.to_thread(
                reads_a.read_cited_claims,
                entity_id=str(account_a),
                claim_ids=[served, held, missing],
            )
            assert answer["dispositions"] == {
                served: "served",
                held: "held:outreach_unsafe",
                missing: "not_found",
            }
            assert [c["claim_id"] for c in answer["claims"]] == [served]
            assert "billing dispute" not in json.dumps(answer)

            script_a = model.next(
                AIMessage(
                    content="",
                    tool_calls=[
                        call("ls", {"path": "/research"}, 1),
                        call("read_file", {"file_path": "/research/overview.md"}, 2),
                        call("read_file", {"file_path": "/research/claims.md"}, 3),
                    ],
                ),
                AIMessage(content="I read the research; nothing to change yet."),
            )
            run_a = await asyncio.to_thread(_executor_turn, host, envelope_a)
            assert run_a["status"] == "succeeded"
            assert (run_a["result"]["outcome"], run_a["result"]["saved_version"]) == (
                "unchanged",
                None,
            )
            files_a = _research_files(design_env, envelope_a)
            assert sorted(files_a) == ["claims.md", "insights.md", "overview.md"]
            overview = files_a["overview.md"]
            # The displayable claim's statement, with its citation label; the label's claim is in
            # claims.md with what it says and its source.
            assert overview.startswith(f"# {ACCOUNT_A}: overview\n")
            assert f"- {SERVED_STATEMENT} [c1]" in overview
            assert "## c1\nSays: title: Head of ABM; title: ABM Manager\n" in files_a["claims.md"]
            assert f"Source: {SERVED_SOURCE}" in files_a["claims.md"]
            assert SERVED_SPAN in files_a["claims.md"]
            # The held claim: its statement left the research files and nothing of its value or its
            # quote is in them; it took no label.
            everything_a = "\n".join(files_a.values())
            assert HELD_STATEMENT not in everything_a
            assert "billing dispute" not in everything_a and HELD_SPAN not in everything_a
            assert "[c2]" not in everything_a
            # The missing id: its statement stays (no real rule holds it) but cites nothing.
            assert f"- {MISSING_STATEMENT}\n" in overview
            # What the model read is what is on disk.
            assert _unnumbered(script_a.text_of("call_2")) == overview.rstrip("\n")
            assert _unnumbered(script_a.text_of("call_3")) == files_a["claims.md"].rstrip("\n")

            # --- workspace B: A's ids, asked in B ----------------------------------------------
            envelope_b = _site_envelope(
                workspace_id=ws_b,
                project_id=project_b.project_id,
                document_id=doc_b,
                account_entity_id=str(account_b),
                title=ACCOUNT_B,
            )
            reads_b = factory(envelope_b)
            assert reads_b is not None
            # Under B's own account, A's claim ids do not exist.
            answer_b = await asyncio.to_thread(
                reads_b.read_cited_claims,
                entity_id=str(account_b),
                claim_ids=[served, held, missing],
            )
            assert answer_b == {
                "entity_id": str(account_b),
                "claims": [],
                "dispositions": {served: "not_found", held: "not_found", missing: "not_found"},
            }
            # Under A's account, B is refused by name before any claim or page is looked at.
            for read, kwargs, code in (
                (
                    reads_b.read_cited_claims,
                    {"entity_id": str(account_a), "claim_ids": [served]},
                    "refused:entity_not_found",
                ),
                (
                    reads_b.read_account_research,
                    {"account_entity_id": str(account_a)},
                    "refused:account_not_found",
                ),
            ):
                with pytest.raises(DesignPlatformReadError) as refused:
                    await asyncio.to_thread(read, **kwargs)
                assert str(refused.value) == code

            model.next(
                AIMessage(
                    content="",
                    tool_calls=[call("read_file", {"file_path": "/research/overview.md"}, 1)],
                ),
                AIMessage(content="I read the research; nothing to change yet."),
            )
            run_b = await asyncio.to_thread(_executor_turn, host, envelope_b)
            assert run_b["status"] == "succeeded"
            files_b = _research_files(design_env, envelope_b)
            # B's page is B's: its statement stays (an unknown id is not a real hold) and cites
            # nothing; there is no claims file, and nothing of A's is anywhere in B's research.
            assert sorted(files_b) == ["insights.md", "overview.md"]
            assert f"- {B_STATEMENT}\n" in files_b["overview.md"]
            everything_b = "\n".join(files_b.values())
            for leaked in (
                SERVED_STATEMENT,
                HELD_STATEMENT,
                MISSING_STATEMENT,
                ACCOUNT_A,
                "Head of ABM",
                "billing dispute",
                SERVED_SOURCE,
                "[c1]",
            ):
                assert leaked not in everything_b, leaked

    run_async(scenario())


# =================================================================================================
# P4. What the model is allowed to call (design@v5).
# =================================================================================================

LANE_B_TOOLS = ("read_cited_claims@1", "design_record_site_section@1")
LANE_A_SITE_WRITES = ("design_write_site@1", "design_undo_site@1", "design_redo_site@1")


def test_p4_design_v5_grants_the_lane_b_tools_to_design_alone_and_site_writes_to_none() -> None:
    registry = _registry()
    design = registry.resolve(AgentRole.DESIGN)
    assert design.profile_ref.address == "profile:design@v5"

    maps = {
        role: {item.address: item for item in registry.resolve(role).capabilities}
        for role in C6_ACTIVE_PROFILE_VERSIONS
    }
    # Every role's map discloses all five tools, whatever their status.
    for role, capabilities in maps.items():
        assert set(LANE_B_TOOLS + LANE_A_SITE_WRITES) <= set(capabilities), role

    # The two Lane B tools: available to DESIGN and to no other role.
    for address in LANE_B_TOOLS:
        holders = {
            role
            for role, capabilities in maps.items()
            if capabilities[address].status is AgentCapabilityStatus.AVAILABLE
        }
        assert holders == {AgentRole.DESIGN}, (address, holders)
    # Lane A's site writes: available to no role (ruling R6).
    for address in LANE_A_SITE_WRITES:
        assert all(
            capabilities[address].status is not AgentCapabilityStatus.AVAILABLE
            for capabilities in maps.values()
        ), address
        assert address not in {pin.address for pin in design.profile.tools}

    # Head of ABM sees the two Lane B tools disclosed as role-unavailable, not available.
    head = maps[AgentRole.HEAD_OF_ABM]
    for address in LANE_B_TOOLS:
        assert head[address].status is AgentCapabilityStatus.ROLE_UNAVAILABLE, head[address]

    # And that is what each model is told, in its generated capability map.
    design_map = design.generated_resource_map
    available = design_map.split("Governed platform tools available to this role:\n", 1)[1].split(
        "\n\n", 1
    )[0]
    for address in LANE_B_TOOLS:
        assert f"- {address} effect=" in available, address
    for address in LANE_A_SITE_WRITES:
        assert f"- {address} " not in available, address
    head_map = registry.resolve(AgentRole.HEAD_OF_ABM).generated_resource_map
    unavailable = head_map.split("Platform tools not available to this role:\n", 1)[1].split(
        "\n\n", 1
    )[0]
    for address in LANE_B_TOOLS:
        assert f"- {address} status=role_unavailable " in unavailable, address
