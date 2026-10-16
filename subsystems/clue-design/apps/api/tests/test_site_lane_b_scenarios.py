"""Business-logic scenarios for Lane B — the Puck site agent on the platform — design side (BV1a).

The unit suites beside this one pin each piece of Lane B alone. This file drives them TOGETHER, the
way a site turn really runs: ``create_app`` over the Postgres test database, the test's own blob
storage, the real site-kit Node bundles (validator, catalog, render), Lane A's real hardened
Chromium, Lane A's real HTTP routes for the human editor, and Lane B's real executor
(``execute_site_turn_job``), harness, tools and ports. ``host.site_turn_runner`` stays ``None``, so
the executor builds the REAL inputs (``build_site_turn_inputs``) and ports
(``DurableSiteAssetPort``, ``DurableSiteVersionPort``, ``PlatformSiteRenderer``).

THE ONE SEAM. Only the chat model is replaced. ``lumen_agent.harness._fresh_model`` builds every
role model through ``lumen_agent.llm.init_model`` (a lazy import, re-read on each call), so that
attribute is patched to hand back a scripted model (``site_fixtures.ScriptedModel``: a
``GenericFakeChatModel`` answering ``AIMessage(tool_calls=[...])``). ``_instrument`` itself stays
real, so the trace callback and the run's cancellation probe are attached to the scripted model
exactly as to a live one, and every tool call the script makes runs for real. The image-capability
probe (``lumen_agent.llm.assert_model_supports_image_input``, which asks the provider's catalogue
over the network) is the second patched attribute. Scenario-specific seams, each named where used:
the validator's node bundle call (E b, Lane B's own fix-round seam) and
``lumen_api.image_provider.generate`` (F d, H). No live model or image provider is ever called.

THE BRAND. Garner's real kit (site-kit's ``kit.json`` fixture) is published as a ``design_brand_kit``
row in the test's workspace and pinned on the site (``theme.brand_kit``); the brand loader
``create_app`` composes (``site_brand_loader_for``) and the turn's own builder read it from there.
The site is Garner's ``garner-syracuse`` shell and its kit-component sections; its two photos are
put in this workspace's library (engine ingest + ``design_register_asset_record``, as ``POST /assets``
does) so this workspace holds them. Garner's five captured clones are not
minted as web fragments (their stored html is the sanitizer's output and would not re-mint to the
same ids), so the ``ClonedSection`` items are left out.

A scenario that finds a defect is a ``pytest.mark.xfail(strict=True, reason="DEFECT: …")`` test;
production code is never changed here (see the task report).
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from py_lumen_config import settings
from pydantic import Field

from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from site_kit_support import FIXTURES, chromium_available, ensure_site_kit_dist

_SITE_FIXTURES = Path(__file__).resolve().parents[2] / "agent_runtime" / "tests" / "site_fixtures.py"


def _load_site_fixtures() -> Any:
    """The agent runtime's shared site fixtures, loaded by path (they live beside that suite's own
    conftest, which must not shadow this suite's)."""
    if "site_fixtures" in sys.modules:
        return sys.modules["site_fixtures"]
    spec = importlib.util.spec_from_file_location("site_fixtures", _SITE_FIXTURES)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["site_fixtures"] = module
    spec.loader.exec_module(module)
    return module


site_fixtures = _load_site_fixtures()
call = site_fixtures.call
GARNER_KIT = json.loads((FIXTURES / "kit.json").read_text(encoding="utf-8"))
GARNER_STORED = json.loads((FIXTURES / "garner-syracuse.json").read_text(encoding="utf-8"))
REQUEST_1 = "Make the closing call to action say it is free."
NEW_CTA_HEADING = "Request SCSD's free analysis today"


# --- the model seam -----------------------------------------------------------------------------


class Script(site_fixtures.ScriptedModel):
    """The spike's scripted model, recording what it was shown on every call.

    ``hooks`` maps a call number (0-based) to a callable run BEFORE that call answers: the moment
    between two of the agent's steps, after the previous step's tool results landed. That is where
    a scenario makes the world move under a running turn (a human save, a Stop press).
    """

    seen: list = Field(default_factory=list)
    hooks: dict = Field(default_factory=dict)
    disable_streaming: bool = True

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        number = len(self.seen)
        self.seen.append(list(messages))
        hook = self.hooks.get(number)
        if hook is not None:
            hook()
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    # --- what the model saw ---------------------------------------------------------------

    def prompt(self) -> str:
        """The user turn the harness opened with (the composed prompt)."""
        first = self.seen[0]
        return next(str(m.content) for m in first if isinstance(m, HumanMessage))

    def results(self) -> dict[str, Any]:
        """Every tool result the model was shown, by tool-call id."""
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
        return " ".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")

    def images_of(self, call_id: str) -> int:
        content = self.results()[call_id]
        return sum(1 for block in content if isinstance(block, dict) and block.get("type") == "image") if isinstance(content, list) else 0


@dataclass
class ModelSeam:
    """What the patched seams saw: the scripts handed out, and every capability probe."""

    scripts: list[Script] = field(default_factory=list)
    built: list[dict] = field(default_factory=list)
    probed: list[str] = field(default_factory=list)

    def next(self, *steps: AIMessage, hooks: dict | None = None) -> Script:
        """Queue the script the next site turn's model will answer with."""
        script = Script(messages=iter(steps), hooks=dict(hooks or {}))
        self.scripts.append(script)
        return script


@pytest.fixture()
def model(monkeypatch: pytest.MonkeyPatch) -> ModelSeam:
    import lumen_agent.llm as llm

    seam = ModelSeam()
    handed: list[Script] = []

    def init_model(model_id, **kwargs):
        # The harness builds exactly one model per site turn (the orchestrator role).
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


# --- the composed app ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _agent_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "agent-workspace"
    monkeypatch.setattr(settings, "lumen_agent_trace_dir", None)
    monkeypatch.setattr(settings, "lumen_agent_workspace_root", root)
    # Nothing here offers fleet work, and an embedded worker draining the shared queue would only
    # add another writer (and run the asset-analysis jobs an upload offers).
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)
    return root


@pytest.fixture(autouse=True)
def _no_run_left_open(monkeypatch: pytest.MonkeyPatch):
    """Every design run a test here creates is terminal when the test ends, whatever its outcome.

    Many scenarios end with a run deliberately still ``running`` or ``queued`` (a takeover not yet
    completed, a fenced attempt, a drained turn). The fleet reaper sweeps the WHOLE database, so a
    later test's reaper pass would re-offer such a run — with a queued ``design_job`` task that
    another suite's fleet worker then claims instead of its own (site-turn durability fix pass, F4).
    So the runs are recorded as they are made and failed at teardown through the DAL's own terminal
    write (which also prunes their working copies and checkpoints), and any live fleet task for
    them is removed. A run the test already finished is left exactly as it is."""
    from clue_design import runs as design_runs
    from sqlalchemy import text

    created: list[tuple[str, Any]] = []
    real_create_run = HybridRepository.create_run

    def recording_create_run(self, run_id, *args, **kwargs):
        row = real_create_run(self, run_id, *args, **kwargs)
        created.append((self.workspace_id, design_runs.work_id_for_run(run_id)))
        return row

    monkeypatch.setattr(HybridRepository, "create_run", recording_create_run)
    yield
    closed = {"status": "failed", "error": {"code": "test.teardown", "message": "closed by the test's teardown"}}
    for workspace_id, work_id in created:
        async def close(conn, work_id=work_id):
            await design_runs.fail_dispatched_run(conn, work_id=work_id, result=closed)
            await conn.execute(text("DELETE FROM fleet_task WHERE work_id = :w AND status IN ('queued', 'claimed')"),
                               {"w": work_id})

        HybridRepository(workspace_id=workspace_id)._bridge._run(close)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def session_folder(agent_root: Path, workspace_id: str, document_id: str) -> Path:
    from clue_design.sessions import design_session_id

    return agent_root / "sessions" / design_session_id(workspace_id, document_id)


# --- Garner: the real brand in this workspace ----------------------------------------------------


@dataclass
class Garner:
    kit_ref: dict
    #: Garner's two FeatureSplit photos, swapped for images this workspace holds: {old file: new file}.
    images: dict[str, str]

    def site(self, document_id: str) -> dict:
        """Garner's garner-syracuse site (shell and kit sections) pinned to the stored kit."""
        pages = copy.deepcopy(GARNER_STORED["pages"])
        for page in pages.values():
            page["content"] = [item for item in page["content"] if item["type"] != "ClonedSection"]
        text = json.dumps(pages)
        for old, new in self.images.items():
            text = text.replace(old, new)
        return {
            "id": document_id,
            "title": "Syracuse City School District",
            "theme": {"brand_kit": dict(self.kit_ref)},
            "pages": json.loads(text),
            "shell": copy.deepcopy(GARNER_STORED["shell"]),
            "agent_sections": {},
        }


def library_image(client: TestClient, colour: tuple[int, int, int], label: str, workspace_id: str | None = None) -> dict:
    """A photo in a workspace's library, made the way ``POST /assets`` makes one: ingested by the
    real engine (``app.state.core``), given durable custody (``register_engine_write``) and
    registered through the governed ``design_register_asset_record``.

    The route itself is not called: it also offers an asset-enrichment ingestion job to the fleet
    queue, nothing in this file drains that queue (the embedded worker is off), and an undrained job
    is later claimed by another suite's embedded worker, where it holds that client's shutdown
    open. (Found in BV1a fix round 1.)"""
    import base64
    import io
    import os

    from PIL import Image

    from clue_design.storage import SOURCE_KEY_ASSET
    from lumen_api.asset_custody import register_engine_write
    from lumen_api.design_store import DesignBlobStore

    workspace_id = workspace_id or os.environ["LUMEN_DEV_WORKSPACE_ID"]
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), colour).save(buffer, format="PNG")
    asset_id = f"asset_{uuid4().hex[:12]}"
    cache_dir = Path(client.app.state.engine_cache_root) / workspace_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    ingested = client.app.state.core.ingest_asset(
        store_root=str(cache_dir), bytes_base64=base64.b64encode(buffer.getvalue()).decode("ascii"), asset_id=asset_id,
        label=label, declared_mime_type="image/png", filename=f"{label}.png",
        provenance={"created_by": "bv1a", "source_label": "upload", "confidence": None, "notes": []},
        raise_on_error=False,
    )
    assert ingested.get("ok"), ingested
    record = ingested["asset"]["record"]
    register_engine_write(DesignBlobStore(client.app.state.storage, workspace_id), cache_dir, source_key=SOURCE_KEY_ASSET,
                          record=record)
    client.app.state.design_tools.invoke("design_register_asset_record", {"record": record}, workspace_id=workspace_id,
                                         actor="human")
    return HybridRepository(workspace_id=workspace_id).require_asset_record(asset_id)["asset"]


def asset_file(asset: dict) -> str:
    return "/asset-store/" + asset["media"]["digest"]["value"]


def seed_garner(client: TestClient) -> Garner:
    repo = HybridRepository()
    kit = repo.create_brand_kit(copy.deepcopy(GARNER_KIT), {}, [], "website")
    kit_ref = {"id": kit["brand_kit"]["id"], "version": kit["brand_kit"]["version"]}
    old = []
    for page in GARNER_STORED["pages"].values():
        for item in page["content"]:
            image = (item.get("props") or {}).get("image")
            if item["type"] != "ClonedSection" and image and image not in old:
                old.append(image)
    images = {}
    for index, file in enumerate(old):
        images[file] = asset_file(library_image(client, ((index * 70) % 256, 140, 90), f"garner-photo-{index}"))
    return Garner(kit_ref=kit_ref, images=images)


@pytest.fixture()
def garner(client: TestClient) -> Garner:
    return seed_garner(client)


def store_site(site: dict) -> dict:
    return HybridRepository().create_document(site, doc_kind="site")


# --- one site turn, recorded the way the fleet records it -----------------------------------------


@dataclass
class Turn:
    run_id: str
    status: str
    response: dict
    events: list
    #: The run row after its terminal write (empty until the turn is completed).
    row: dict
    terminal: tuple = ()


def envelope_for(document_id: str, workspace_id: str, prompt: str, *, bundle: dict | None = None,
                 leg: bool = True, targets: list | None = None):
    from clue_design import runs as design_runs
    from clue_design.envelopes import DesignTurnEnvelope

    run_id = f"run_site_{uuid4().hex[:12]}"
    request = {"prompt": prompt, "base_version": 0, **({"targets": targets} if targets else {})}
    config: dict = {"request": request, "delegation_bundle": bundle or {"brief": "Build Syracuse's 1:1 page."}}
    if leg:
        config["leg"] = {"leg_id": "leg-bv1a"}
    return DesignTurnEnvelope(kind="site_turn", work_id=design_runs.work_id_for_run(run_id), workspace_id=workspace_id,
                              run_id=run_id, checkpoint_thread_id=run_id, document_id=document_id, config=config)


def turn_host(app: Any):
    from lumen_api.fleet_handler import DesignTurnHost

    # site_turn_runner stays None: the executor builds the REAL inputs and ports.
    return DesignTurnHost(core=app.state.core, storage=app.state.storage, engine_cache_root=app.state.engine_cache_root)


def open_run(store: HybridRepository, envelope: Any, *, claim: bool = True) -> None:
    """The run row as the fleet makes it: born queued with its frozen envelope, then claimed
    (``claim_run_for_execution``, generation 1) so it is ``running`` while the turn executes."""
    from clue_design import runs as design_runs

    store.create_run(envelope.run_id, envelope.document_id, kind="site_turn", payload=envelope.model_dump(mode="json"))
    if claim:
        claimed = store._bridge._run(lambda conn: design_runs.claim_run_for_execution(
            conn, work_id=envelope.work_id, worker_id="worker_bv1a", lease_generation=1))
        assert claimed is not None and claimed["status"] == "running"


def run_turn(app: Any, store: HybridRepository, document_id: str, prompt: str, *, claim: bool = True,
             host: Any = None, envelope: Any = None, complete: bool = True, **envelope_kwargs: Any) -> Turn:
    """One site turn through the REAL executor: create + claim the run row, execute, complete
    (the terminal write fenced by the claim's generation, as the fleet lands it)."""
    from lumen_api.main import execute_site_turn_job

    envelope = envelope or envelope_for(document_id, store.workspace_id, prompt, **envelope_kwargs)
    open_run(store, envelope, claim=claim)
    events: list = []
    status, response, event_type, event_data = execute_site_turn_job(
        envelope, store=store, host=host or turn_host(app), event_sink=lambda kind, data: events.append((kind, data)),
        lease_generation=1 if claim else None,
    )
    turn = Turn(envelope.run_id, status, response, events, {}, (event_type, event_data))
    if complete:
        complete_turn(store, turn, claim=claim)
    return turn


def complete_turn(store: HybridRepository, turn: "Turn", *, claim: bool = True) -> None:
    event_type, event_data = turn.terminal
    store.complete_run(turn.run_id, turn.status, turn.response, event_type, event_data,
                       **({"expected_generation": 1} if claim else {}))
    turn.row = store.require_run(turn.run_id)


def saves(turn: Turn) -> list:
    return [(kind, data) for kind, data in turn.events if kind == "site_document_saved"]


def read_document(client: TestClient, document_id: str) -> dict:
    response = client.get(f"/documents/{document_id}")
    assert response.status_code == 200, response.text
    return response.json()


def site_versions(client: TestClient, document_id: str) -> list[dict]:
    response = client.get(f"/documents/{document_id}/site/versions")
    assert response.status_code == 200, response.text
    return response.json()["versions"]


def put_site(client: TestClient, document_id: str, site: dict, base: int):
    return client.put(f"/documents/{document_id}/site", json={"site": site, "base_version": base})


def heading(site: dict, route: str, section_id: str) -> str:
    return next(item["props"]["heading"] for item in site["pages"][route]["content"] if item["props"]["id"] == section_id)


def with_heading(site: dict, route: str, section_id: str, text: str) -> dict:
    changed = copy.deepcopy(site)
    for item in changed["pages"][route]["content"]:
        if item["props"]["id"] == section_id:
            item["props"]["heading"] = text
    return changed


def edit_heading_call(site: dict, route: str, section_id: str, text: str, n: int) -> dict:
    """An edit_file call the agent makes on the page file, changing one section's heading."""
    file = "/page.json" if route == "/" else f"/pages/{route.strip('/')}.json"
    old = heading(site, route, section_id)
    return call("edit_file", {"file_path": file, "old_string": json.dumps(old), "new_string": json.dumps(text)}, n)


def manifest_of(client: TestClient, turn: Turn) -> dict:
    sha = turn.response["session_manifest_sha256"]
    _, data = make_blob_store(client.app).read_blob(sha)
    return json.loads(data)


needs_chromium = pytest.mark.skipif(not chromium_available(), reason="Playwright Chromium is not available")


# =================================================================================================
# A. A real site turn, end to end.
# =================================================================================================


def a_real_site_turn(client: TestClient, model: ModelSeam, garner: Garner, agent_root: Path, *, render: bool) -> dict:
    """Scenario A, step by step (B continues from it). Returns what B needs."""
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    steps = [
        AIMessage(content="", tool_calls=[
            call("read_file", {"file_path": "/brief.md"}, 1),
            call("read_file", {"file_path": "/research/README.md"}, 2),
            call("read_file", {"file_path": "/pages/analysis.json"}, 3),
        ]),
        AIMessage(content="", tool_calls=[
            call("write_file", {"file_path": "/plan.md", "content": "# Plan\n\n- Close on the free analysis.\n"}, 4),
            edit_heading_call(born, "/analysis", "cta", NEW_CTA_HEADING, 5),
            call("validate_page", {}, 6),
            *([call("render_page", {"route": "/analysis"}, 7)] if render else []),
        ]),
        AIMessage(content="The closing call to action now says the analysis is free."),
    ]
    script = model.next(*steps)
    # The session's memory of an earlier fetch (fetch_page itself would go to the network): the
    # agent cannot write fetched/ (it is read-only to its file tools), so the world does, the way
    # fetch_page saves a page, before the agent's second step. fetch_page writes into the agent's
    # own workspace, which is this attempt's folder (site-turn durability, 2026-10-16).
    envelope = envelope_for(document_id, store.workspace_id, REQUEST_1)
    folder = (session_folder(agent_root, store.workspace_id, document_id) / "attempts" / f"{envelope.run_id}-g1"
              / "workspace" / "fetched")
    script.hooks[1] = lambda: (folder.mkdir(parents=True, exist_ok=True),
                               (folder / "garner-aon-study.md").write_text("Source: https://garnerhealth.com/aon\n\n7.4% lower spend.\n"))
    turn = run_turn(client.app, store, document_id, REQUEST_1, envelope=envelope)
    return {"store": store, "document_id": document_id, "born": born, "turn": turn, "script": script}


def test_a_a_real_site_turn_end_to_end(client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    render = chromium_available()
    state = a_real_site_turn(client, model, garner, _agent_root, render=render)
    store, document_id, born, turn, script = (state[k] for k in ("store", "document_id", "born", "turn", "script"))

    # The turn ran on the real harness, with the image probe asked once for the model it built. Only
    # the model's construction was replaced: _instrument still attached the trace capture and the
    # run's cancellation probe to it.
    assert len(model.built) == 1 and model.built[0]["role"] == "design_site"
    assert model.probed == [model.built[0]["model_id"]]
    assert {type(h).__name__ for h in script.callbacks} >= {"TraceCallbackHandler", "CancellationCallbackHandler"}
    assert script.prompt() == REQUEST_1  # the brief rides in brief.md, not the prompt
    assert "Build Syracuse's 1:1 page." in script.text_of("call_1")
    assert "There is no written research for this account yet." in script.text_of("call_2")
    assert script.text_of("call_6") == "VALID.", script.text_of("call_6")
    if render:
        text = script.text_of("call_7")
        assert "1440 wide:" in text and "375 wide:" in text, text
        assert text.count("broken images: 0") == 2, text
        assert script.images_of("call_7") >= 2

    # The brand the agent read is Garner's stored kit (its measured teal), not a default.
    workspace = session_folder(_agent_root, store.workspace_id, document_id) / "workspace"
    assert "| brand | Brand | surface.brand | `bg-surface-brand text-on-surface-brand` | #047464 |" in (workspace / "brand" / "brand.md").read_text()

    # Version 1 holds the new heading; nothing else moved.
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1
    assert stored["scene"] == with_heading(born, "/analysis", "cta", NEW_CTA_HEADING)
    # One edit envelope: the whole site, written by the agent.
    (envelope,) = store.list_envelopes(document_id)
    assert envelope["operations"] == [{"kind": "replace_site", "site": stored["scene"]}]
    assert envelope["inverse_operations"] == [{"kind": "replace_site", "site": born}]
    assert (envelope["actor"] or {}).get("kind") == "agent" and envelope["intent"] == REQUEST_1

    # The run's durable result.
    assert turn.status == "succeeded" and turn.row["status"] == "succeeded"
    result = turn.row["result"]
    assert (result["status"], result["outcome"], result["saved_version"], result["current_version"], result["doc_kind"]) == (
        "applied", "saved", 1, 1, "site")
    assert len(result["model_calls"]) == len(script.seen) == 3
    assert result["summary"] == "The closing call to action now says the analysis is free."

    # The chat hears about exactly one save, and it is this one.
    assert saves(turn) == [("site_document_saved", {"document_id": document_id, "version": 1})]
    # Besides the save, the sink carries only the tools' own progress events (validate_page, and
    # render_page, which validates before it draws).
    progress = ["site_valid", "site_valid", "site_render"] if render else ["site_valid"]
    assert [kind for kind, _ in turn.events] == [*progress, "site_document_saved"], turn.events

    # history.md: the person's words and the save.
    history = (workspace / "history.md").read_text()
    assert f"\n## 1. {REQUEST_1}\n" in history and "- Saved: as version 1\n" in history
    assert "/analysis: changed cta (heading)" in history

    # The session snapshot keeps the agent's memory and none of the regenerated inputs.
    files = set(manifest_of(client, turn)["files"])
    assert {"workspace/plan.md", "workspace/history.md", "workspace/fetched/garner-aon-study.md"} <= files
    regenerated = ("brief.md", "site.md", "research/", "catalog/", "brand/", "skills/", "skills-e5/",
                   "page.json", "pages/", "shell.json", "work/", "seller/", "project-context/")
    assert not [f for f in files if f.removeprefix("workspace/").startswith(regenerated)], sorted(files)

    # What the editor reads back.
    body = read_document(client, document_id)
    assert body["current_version"] == 1 and body["scene"] == stored["scene"] and body["doc_kind"] == "site"
    (latest,) = site_versions(client, document_id)
    assert (latest["version"], latest["actor_kind"], latest["intent"]) == (1, "agent", REQUEST_1)


# =================================================================================================
# B. The human and the agent take turns (Lane A's routes interleaved).
# =================================================================================================

REQUEST_2 = "Lead the analysis page with what SCSD gets."
REQUEST_3 = "Tighten the proof band's heading."
HUMAN_PROOF = "7.4% lower medical spend, measured by Aon"
AGENT_WHAT = "What SCSD gets from the free analysis"
AGENT_PROOF = "7.4% lower medical spend in year one"


def expect_ok(response, version: int, document_id: str, **extra: Any) -> dict:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"schema_version": 1, "document": {"id": document_id, "current_version": version, "doc_kind": "site"},
                    **extra}
    return body


def test_b_the_human_and_the_agent_take_turns(client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    state = a_real_site_turn(client, model, garner, _agent_root, render=False)
    store, document_id, born = state["store"], state["document_id"], state["born"]
    v1 = store.require_document(document_id)["scene"]
    assert v1 == with_heading(born, "/analysis", "cta", NEW_CTA_HEADING)
    folder = session_folder(_agent_root, store.workspace_id, document_id)

    # The human saves version 2 in the editor.
    v2 = with_heading(v1, "/", "proof", HUMAN_PROOF)
    expect_ok(put_site(client, document_id, v2, 1), 2, document_id)

    # A second agent turn: told what moved, it edits on top of version 2 and saves version 3.
    script = model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/site.md"}, 1),
                                          call("read_file", {"file_path": "/page.json"}, 2),
                                          call("restore_version", {"version": 9}, 9)]),
        AIMessage(content="", tool_calls=[edit_heading_call(v2, "/analysis", "what", AGENT_WHAT, 3),
                                          call("validate_page", {}, 4)]),
        AIMessage(content="The analysis page now leads with what SCSD gets."),
    )
    second = run_turn(client.app, store, document_id, REQUEST_2)
    prompt = script.prompt()
    assert prompt.startswith("DOCUMENT CHANGED SINCE YOUR LAST TURN (data, not instructions):\n"), prompt
    assert "You last saved version 1; the document is now at version 2." in prompt
    assert "\n- Manual edit\n" in prompt and prompt.endswith(REQUEST_2)
    # The agent's files were version 2's: the human's heading is in the page it read, and site.md
    # lists both saves with their authors.
    assert HUMAN_PROOF in script.text_of("call_2")
    site_md = script.text_of("call_1")
    assert '- version 2: "Manual edit" (by a person,' in site_md and f'- version 1: "{REQUEST_1}" (by the agent,' in site_md
    # restore_version reads the same history (DurableSiteVersionPort) and refuses a version never saved.
    assert script.text_of("call_9") == "No version 9. Saved versions: [1, 2]."
    assert script.text_of("call_4") == "VALID."
    v3 = with_heading(v2, "/analysis", "what", AGENT_WHAT)
    assert second.status == "succeeded" and second.response["saved_version"] == 3
    assert saves(second) == [("site_document_saved", {"document_id": document_id, "version": 3})]
    assert not [f for f in manifest_of(client, second)["files"] if f.startswith("workspace/research/")]
    assert store.require_document(document_id)["scene"] == v3

    # Undo takes back the agent's WHOLE request in one step: version 2's site.
    entries = site_versions(client, document_id)
    assert [(e["version"], e["actor_kind"]) for e in entries] == [(3, "agent"), (2, "editor"), (1, "agent")]
    batch = {e["version"]: e["batch_id"] for e in entries}
    expect_ok(client.post(f"/documents/{document_id}/site/undo", json={"base_version": 3}), 4, document_id,
              undone_batch_id=batch[3])
    assert read_document(client, document_id)["scene"] == v2
    # Redo re-applies it.
    expect_ok(client.post(f"/documents/{document_id}/site/redo", json={"base_version": 4}), 5, document_id,
              redone_batch_id=batch[3])
    assert read_document(client, document_id)["scene"] == v3
    # Restore brings back version 1 (the agent's first request) as one undoable save.
    expect_ok(client.post(f"/documents/{document_id}/site/versions/{batch[1]}/restore", json={"base_version": 5}), 6,
              document_id)
    assert read_document(client, document_id)["scene"] == v1
    # Undo of the restore returns to version 3's site.
    restored = read_document(client, document_id)["undo_stack"][-1]
    expect_ok(client.post(f"/documents/{document_id}/site/undo", json={"base_version": 6}), 7, document_id,
              undone_batch_id=restored)
    assert read_document(client, document_id)["scene"] == v3

    # A fresh worker: the session folder is gone. Its memory comes back from the stamped manifest;
    # the research is rebuilt from the request's own inputs (this one names the account).
    plan = (folder / "workspace" / "plan.md").read_text()
    shutil.rmtree(folder)
    script = model.next(
        AIMessage(content="", tool_calls=[
            call("read_file", {"file_path": "/plan.md"}, 1),
            call("read_file", {"file_path": "/fetched/garner-aon-study.md"}, 2),
            call("read_file", {"file_path": "/research/README.md"}, 3),
            call("ls", {"path": "/research"}, 4),
        ]),
        AIMessage(content="", tool_calls=[edit_heading_call(v3, "/", "proof", AGENT_PROOF, 5),
                                          call("validate_page", {}, 6)]),
        AIMessage(content="The proof band's heading is shorter."),
    )
    bundle = {"brief": "Build Syracuse's 1:1 page.",
              "artifact": {"position": 0, "count": 1, "title": "Syracuse City School District", "note": ""}}
    third = run_turn(client.app, store, document_id, REQUEST_3, bundle=bundle)
    assert "Close on the free analysis." in script.text_of("call_1") and plan.endswith("Close on the free analysis.\n")
    assert "7.4% lower spend." in script.text_of("call_2")
    research = script.text_of("call_3")
    assert research.count("# Syracuse City School District") == 1, research  # rebuilt, not request 1's "the account"
    assert "README.md" in script.text_of("call_4") and "overview" not in script.text_of("call_4")
    # The drift note names every outside move since the agent's version 3.
    assert "You last saved version 3; the document is now at version 7." in script.prompt()
    assert third.status == "succeeded" and third.response["saved_version"] == 8
    assert store.require_document(document_id)["scene"] == with_heading(v3, "/", "proof", AGENT_PROOF)
    history = (folder / "workspace" / "history.md").read_text()
    assert [line for line in history.splitlines() if line.startswith("## ")] == [
        f"## 1. {REQUEST_1}", f"## 2. {REQUEST_2}", f"## 3. {REQUEST_3}"]
    assert "- Saved: as version 8\n" in history


# =================================================================================================
# C. A race the agent loses.
# =================================================================================================

HUMAN_CTA = "Request the analysis (human edit)"


def manifest_text(client: TestClient, turn: Turn, key: str) -> str:
    entry = manifest_of(client, turn)["files"][key]
    _, data = make_blob_store(client.app).read_blob(entry["sha256"])
    return data.decode("utf-8")


def lose_the_race(client: TestClient, model: ModelSeam, garner: Garner, *, human_write: Callable[[str, dict], None],
                  claim: bool, complete: bool = True) -> dict:
    """A turn during which someone else saves the site; the agent then tries to save its own."""
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    human = with_heading(born, "/analysis", "cta", HUMAN_CTA)
    envelope = envelope_for(document_id, store.workspace_id, REQUEST_1)
    script = model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/pages/analysis.json"}, 1)]),
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/analysis", "cta", NEW_CTA_HEADING, 2),
                                          call("validate_page", {}, 3)]),
        AIMessage(content="The closing call to action now says the analysis is free."),
        # Between the agent's read and its edit, the other writer saves.
        hooks={1: lambda: human_write(envelope.run_id, human)},
    )
    turn = run_turn(client.app, store, document_id, REQUEST_1, claim=claim, envelope=envelope, complete=complete)
    return {"store": store, "document_id": document_id, "born": born, "human": human, "turn": turn, "script": script}


def test_c_a_race_the_agent_loses_to_a_human_save(client: TestClient, model: ModelSeam, garner: Garner,
                                                  _agent_root: Path) -> None:
    """The brief's race: the human saves through Lane A's save route while the request runs.

    The editor's save route refuses while the turn's row is RUNNING (scenario D, the lock), so this
    turn's row is left queued — the shape Task 12's own suite records it in — which the lock does not
    see. What is proven is the second line of defence on its own: the executor's CAS on the version
    it read when the request started."""
    landed: list = []

    def human_saves(run_id: str, site: dict) -> None:
        landed.append(put_site(client, site["id"], site, 0))

    state = lose_the_race(client, model, garner, human_write=human_saves, claim=False)
    store, document_id, human, turn, script = (state[k] for k in ("store", "document_id", "human", "turn", "script"))
    (saved,) = landed
    expect_ok(saved, 1, document_id)
    assert script.text_of("call_3") == "VALID."

    # The human's version stands; the agent's save was refused as a version conflict.
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1 and stored["scene"] == human
    (envelope,) = store.list_envelopes(document_id)
    assert (envelope["actor"] or {}).get("kind") == "editor"
    assert turn.status == "failed" and turn.response["status"] == "conflicted"
    assert turn.response["error"]["code"] == "site_turn.version_conflict"
    assert (turn.response["saved_version"], turn.response["current_version"], turn.response["base_version"]) == (None, 1, 0)
    assert saves(turn) == []
    # history says the site changed under the request, and the session's memory is still snapshotted.
    line = "- Saved: no, the site changed while this request ran\n"
    workspace = session_folder(_agent_root, store.workspace_id, document_id) / "workspace"
    assert line in (workspace / "history.md").read_text()
    assert turn.row["result"]["session_manifest_sha256"] == turn.response["session_manifest_sha256"]
    assert line in manifest_text(client, turn, "workspace/history.md")


def test_c_a_takeover_that_saved_first_wins_the_race(client: TestClient, model: ModelSeam, garner: Garner) -> None:
    """The race the lock cannot stop: a lease takeover. The fleet re-grants the running row to a
    second worker (generation 2) whose own persist lands first; the first worker (generation 1) runs
    on, and its save must lose to the version it never saw. Since site-turn durability (2026-10-16)
    it loses one step earlier than the version CAS: the save itself is fenced by the attempt's
    generation, so it is refused as no longer holding the run. Its terminal write is fenced too."""
    from clue_design import runs as design_runs
    from clue_design.errors import DesignRunFencedError

    def takeover_saves(run_id: str, site: dict) -> None:
        store = HybridRepository()
        claimed = store._bridge._run(lambda conn: design_runs.claim_run_for_execution(
            conn, work_id=design_runs.work_id_for_run(run_id), worker_id="worker_takeover", lease_generation=2))
        assert claimed is not None and claimed["lease_generation"] == 2
        client.app.state.design_tools.invoke(
            "design_write_site",
            {"document_id": site["id"], "site": site, "expected_base_version": 0, "intent": REQUEST_1,
             "actor_kind": "agent", "source": "agent"},
            workspace_id=store.workspace_id, actor="agent", actor_id=run_id)

    state = lose_the_race(client, model, garner, human_write=takeover_saves, claim=True, complete=False)
    store, document_id, human, turn = (state[k] for k in ("store", "document_id", "human", "turn"))
    # The zombie's save lost: fenced, nothing announced; the takeover's version stands alone.
    assert turn.status == "fenced" and turn.response["error"]["code"] == "site_turn.fenced"
    assert saves(turn) == []
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1 and stored["scene"] == human
    assert len(store.list_envelopes(document_id)) == 1
    # The fleet lands no terminal write for a fenced attempt; and one attempted anyway is refused:
    # the row belongs to generation 2 now.
    with pytest.raises(DesignRunFencedError):
        store.complete_run(turn.run_id, "failed", turn.response, *turn.terminal, expected_generation=1)
    assert store.require_run(turn.run_id)["status"] == "running"


def test_c_a_lost_race_is_remembered_by_a_fresh_worker(client: TestClient, model: ModelSeam, garner: Garner,
                                                       _agent_root: Path) -> None:
    """Task 12 snapshots the session's memory on a conflicted (or refused) request on purpose
    (fix round 1 a). The next request, landing on a worker that never ran this session, must get
    that memory back: history.md says request 1 lost the race, and this request is number 2."""

    def human_saves(run_id: str, site: dict) -> None:
        assert put_site(client, site["id"], site, 0).status_code == 200

    state = lose_the_race(client, model, garner, human_write=human_saves, claim=False)
    store, document_id = state["store"], state["document_id"]
    folder = session_folder(_agent_root, store.workspace_id, document_id)
    shutil.rmtree(folder)  # a fresh worker
    script = model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/history.md"}, 1)]),
        AIMessage(content="Nothing to change."),
    )
    run_turn(client.app, store, document_id, "Try that again.")
    assert "the site changed while this request ran" in script.text_of("call_1")
    history = (folder / "workspace" / "history.md").read_text()
    assert [line for line in history.splitlines() if line.startswith("## ")] == [f"## 1. {REQUEST_1}", "## 2. Try that again."]


# =================================================================================================
# D. The agent-run lock.
# =================================================================================================


def test_d_the_agent_run_lock(client: TestClient, model: ModelSeam, garner: Garner) -> None:
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    first, second = with_heading(born, "/", "proof", "First save"), with_heading(born, "/", "proof", "Second save")
    expect_ok(put_site(client, document_id, first, 0), 1, document_id)
    expect_ok(put_site(client, document_id, second, 1), 2, document_id)
    undo_top = read_document(client, document_id)["undo_stack"][-1]
    expect_ok(client.post(f"/documents/{document_id}/site/undo", json={"base_version": 2}), 3, document_id,
              undone_batch_id=undo_top)
    # Both stacks are non-empty, so undo and redo below can only refuse because of the lock.
    held = read_document(client, document_id)
    assert (held["current_version"], len(held["undo_stack"]), len(held["redo_stack"])) == (3, 1, 1)
    b1 = held["undo_stack"][0]

    envelope = envelope_for(document_id, store.workspace_id, REQUEST_1)
    refusals: dict[str, Any] = {}

    def editor_tries_everything() -> None:
        refusals["put"] = put_site(client, document_id, with_heading(first, "/", "proof", "Mid-run edit"), 3)
        refusals["undo"] = client.post(f"/documents/{document_id}/site/undo", json={"base_version": 3})
        refusals["redo"] = client.post(f"/documents/{document_id}/site/redo", json={"base_version": 3})
        refusals["restore"] = client.post(f"/documents/{document_id}/site/versions/{b1}/restore", json={"base_version": 3})
        refusals["agent_run"] = client.get(f"/documents/{document_id}/agent-run").json()
        refusals["scene"] = read_document(client, document_id)["scene"]

    model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/pages/analysis.json"}, 1)]),
        AIMessage(content="", tool_calls=[edit_heading_call(first, "/analysis", "cta", NEW_CTA_HEADING, 2),
                                          call("validate_page", {}, 3)]),
        AIMessage(content="Done."),
        hooks={1: editor_tries_everything},
    )
    turn = run_turn(client.app, store, document_id, REQUEST_1, envelope=envelope)

    for name in ("put", "undo", "redo", "restore"):
        response = refusals[name]
        assert response.status_code == 409, (name, response.text)
        assert response.json()["detail"] == {"code": "document.agent_run_active", "run_id": envelope.run_id}, name
    assert refusals["scene"] == first
    assert (refusals["agent_run"]["active"], refusals["agent_run"]["run_id"]) == (True, envelope.run_id)

    # The run's own persist (design_write_site, as the agent) was admitted while the lock held.
    assert turn.status == "succeeded" and turn.response["saved_version"] == 4
    after_turn = with_heading(first, "/analysis", "cta", NEW_CTA_HEADING)
    assert store.require_document(document_id)["scene"] == after_turn

    # The run completed: the lock lifts by itself and every route works again.
    assert client.get(f"/documents/{document_id}/agent-run").json()["active"] is False
    agent_batch = read_document(client, document_id)["undo_stack"][-1]
    expect_ok(client.post(f"/documents/{document_id}/site/undo", json={"base_version": 4}), 5, document_id,
              undone_batch_id=agent_batch)
    expect_ok(client.post(f"/documents/{document_id}/site/redo", json={"base_version": 5}), 6, document_id,
              redone_batch_id=agent_batch)
    expect_ok(client.post(f"/documents/{document_id}/site/versions/{b1}/restore", json={"base_version": 6}), 7, document_id)
    expect_ok(put_site(client, document_id, with_heading(first, "/", "proof", "After the run"), 7), 8, document_id)


# =================================================================================================
# E. Every refusal a site turn can meet.
# =================================================================================================


def history_of(agent_root: Path, store: HybridRepository, document_id: str) -> str:
    return (session_folder(agent_root, store.workspace_id, document_id) / "workspace" / "history.md").read_text()


def nothing_saved(store: HybridRepository, document_id: str, turn: Turn) -> None:
    assert store.require_document(document_id)["current_version"] == 0
    assert store.list_envelopes(document_id) == []
    assert saves(turn) == []


def test_e_a_an_invalid_site_is_never_saved(client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """The agent puts a surface the brand lacks on the page and tries to finish. The real harness
    refuses to end on an invalid page (two reminders, then "completed with errors"), so the turn
    fails as site_invalid BEFORE any save is tried — a stronger guard than the save's own refusal,
    which the stubbed runner of Task 12's suite reached instead (E b and E f prove that refused shape)."""
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    store_site(garner.site(document_id))
    script = model.next(
        AIMessage(content="", tool_calls=[
            call("edit_file", {"file_path": "/pages/analysis.json", "old_string": '"surface": "brand"',
                               "new_string": '"surface": "green"'}, 1),
            call("validate_page", {}, 2),
        ]),
        AIMessage(content="Done."), AIMessage(content="Done."), AIMessage(content="Done, but green is not a surface."),
    )
    turn = run_turn(client.app, store, document_id, REQUEST_1)
    assert "content.2(cta).surface" in script.text_of("call_2") and script.text_of("call_2").startswith("INVALID")
    reminders = [m for m in script.seen[-1] if isinstance(m, HumanMessage) and "still invalid" in str(m.content)]
    assert len(reminders) == 2 and len(script.seen) == 4
    assert turn.status == "failed" and turn.response["stop_reason"] == "site_invalid"
    assert turn.response["error"]["code"] == "site_turn.site_invalid"
    assert turn.response["summary"].startswith("The page was still invalid, so nothing was saved: ")
    assert "surface" in turn.response["summary"] and "green" in turn.response["summary"]
    nothing_saved(store, document_id, turn)
    assert "- Saved: no, the page was still invalid\n" in history_of(_agent_root, store, document_id)


def test_e_b_a_validator_that_cannot_check_is_a_refused_save(client: TestClient, model: ModelSeam, garner: Garner,
                                                              _agent_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The site-kit validator cannot run (its node bundle call fails: the narrowest real seam,
    Task 12's own). The turn's validate_page and the save's check both go through that one call
    (``site_doc_validate.run_site_validator``), so there is no seam that breaks the save alone.
    Task 12 (fix round 1 a) rules a "cannot check now" error a REFUSED SAVE: "The website could not
    be saved: <why>", history "the save was refused", memory still written. The finish leaves the
    verdict to that save: no reminder, not site_invalid (BV1a fix round 1, was DEFECT 2)."""
    import lumen_api.site_doc_validate as site_doc_validate
    from lumen_api.site_kit_cli import SiteKitCliError

    def bundle_missing(*args, **kwargs):
        raise SiteKitCliError("site_kit.unavailable", "site-kit validator bundle missing")

    monkeypatch.setattr(site_doc_validate, "run_site_kit_bundle", bundle_missing)
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    script = model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/analysis", "cta", NEW_CTA_HEADING, 1),
                                          call("validate_page", {}, 2)]),
        AIMessage(content="Done."),
    )
    turn = run_turn(client.app, store, document_id, REQUEST_1)
    # validate_page's own words are unchanged; the finish sent no reminder (two model calls, no more).
    assert script.text_of("call_2").startswith("INVALID (1 error):\n- validator crashed: site-kit validator bundle missing")
    assert len(script.seen) == 2
    nothing_saved(store, document_id, turn)
    assert turn.response["error"]["code"] == "site_turn.write_refused" and turn.response["stop_reason"] is None
    assert turn.status == "failed" and turn.response["session_manifest_sha256"]
    assert turn.response["summary"].startswith("The website could not be saved: "), turn.response["summary"]
    assert "site-kit validator bundle missing" in turn.response["summary"]
    assert "- Saved: no, the save was refused\n" in history_of(_agent_root, store, document_id)


def test_e_c_a_turn_addressed_to_a_web_document_is_refused(client: TestClient, model: ModelSeam) -> None:
    store = HybridRepository()
    created = client.post("/documents", json={"doc_kind": "web", "title": "A web page"})
    assert created.status_code == 200, created.text
    web_id = created.json()["document"]["id"]
    turn = run_turn(client.app, store, web_id, REQUEST_1)
    assert turn.status == "failed" and turn.row["status"] == "failed"
    assert turn.response["doc_kind"] == "site"
    assert [d["code"] for d in turn.response["diagnostics"]] == ["site_turn.not_a_site"]
    assert model.built == [] and model.probed == []  # no model was ever built for it
    assert store.require_document(web_id)["current_version"] == 0 and turn.events == []


def test_e_d_stop_pressed_mid_run(client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    envelope = envelope_for(document_id, store.workspace_id, REQUEST_1)
    pressed: dict = {}

    def stop() -> None:
        pressed["response"] = client.post(f"/agent/runs/{envelope.run_id}/cancel")

    script = model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/pages/analysis.json"}, 1)]),
        # Stop is pressed while this answer is being produced; its edit must never run.
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/analysis", "cta", NEW_CTA_HEADING, 2),
                                          call("validate_page", {}, 3)]),
        AIMessage(content="Done."),
        hooks={1: stop},
    )
    turn = run_turn(client.app, store, document_id, REQUEST_1, envelope=envelope)
    assert pressed["response"].status_code == 200 and pressed["response"].json()["cancellation"] == "requested"
    from lumen_agent.site.harness import CANCELLED_SUMMARY

    assert len(script.seen) == 2 and "call_2" not in script.results()
    assert turn.status == "failed" and turn.response["summary"] == CANCELLED_SUMMARY
    assert turn.response["stop_reason"] == "cancelled_by_request"
    assert turn.response["error"]["code"] == "site_turn.cancelled_by_request"
    nothing_saved(store, document_id, turn)
    workspace = session_folder(_agent_root, store.workspace_id, document_id) / "workspace"
    assert NEW_CTA_HEADING not in (workspace / "pages" / "analysis.json").read_text()
    assert "- Saved: no, it was stopped\n" in history_of(_agent_root, store, document_id)


def _fleet_context(payload: dict, work_id: Any):
    import asyncio

    from clue_fleet import WorkContext

    return WorkContext(task_id=uuid4(), work_id=work_id, worker_id="worker_bv1a", lease_generation=1, payload=payload,
                       stop_requested=asyncio.Event(), lease_lost=asyncio.Event())


def _unknown_kind_task(client: TestClient, garner: Garner) -> tuple[HybridRepository, str, Any, dict]:
    """A real queued run row for a site document, and the fleet task for it carrying a turn kind
    no executor knows."""
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    store_site(garner.site(document_id))
    envelope = envelope_for(document_id, store.workspace_id, REQUEST_1)
    open_run(store, envelope, claim=False)
    payload = {**envelope.model_dump(mode="json"), "kind": "poster_turn"}
    return store, document_id, envelope, payload


def test_e_e_a_turn_outside_the_pool_is_refused_before_its_row_is_touched(client: TestClient, model: ModelSeam,
                                                                         garner: Garner) -> None:
    """The fleet given a turn its pool does not serve. ``executor_for_kind`` refuses an unknown kind
    (never the web executor by default), and the handler's capability check is the POOL BOUNDARY:
    it raises before the claim, so it never runs, claims or terminalizes a row that is not its
    pool's (an ingestion-only pool must never fail a turn row; the claim-time SQL capabilities route
    work, and ``design_agent_run.kind`` is a database enum, so a real row cannot carry an unknown
    kind). A row left that way is the reaper's. Controller ruling, BV1a fix round 1 (was DEFECT 3)."""
    import asyncio

    from lumen_api.fleet_handler import DesignJobWorkHandler, DesignTurnJobError, executor_for_kind

    with pytest.raises(DesignTurnJobError, match="poster_turn"):
        executor_for_kind("poster_turn")
    store, document_id, envelope, payload = _unknown_kind_task(client, garner)
    pools = (
        (DesignJobWorkHandler(host_provider=lambda: turn_host(client.app), named_trace=False), payload),
        # The real site_turn envelope offered to the ingestion-only pool: outside that pool too.
        (DesignJobWorkHandler(host_provider=lambda: turn_host(client.app), named_trace=False, ingestion_only=True),
         envelope.model_dump(mode="json")),
    )
    for handler, offered in pools:
        with pytest.raises(DesignTurnJobError, match="outside this worker's execution pool"):
            asyncio.run(handler.handle(_fleet_context(offered, envelope.work_id)))
        # A run row carries its terminal error in result_json (it has no error_json column).
        (row,) = query("SELECT status, result_json, leased_by, lease_generation, leased_at FROM design_agent_run "
                       "WHERE run_id = :r", {"r": envelope.run_id})
        assert row == {"status": "queued", "result_json": None, "leased_by": None, "lease_generation": None,
                       "leased_at": None}, row
    # No executor ran: no model, no write, no envelope.
    assert model.built == []
    assert store.require_document(document_id)["current_version"] == 0 and store.list_envelopes(document_id) == []


def test_e_f_an_image_this_workspace_does_not_hold(client: TestClient, model: ModelSeam, garner: Garner,
                                                    _agent_root: Path) -> None:
    """A library photo whose bytes this workspace no longer holds (its blob purged; the record
    stays). search_assets offers it, the agent places it, validate_page passes (the turn's brand
    lists it); render_page shows it broken; the save's custody check refuses it."""
    store = HybridRepository()
    lost = library_image(client, (200, 40, 40), "lost classroom photo")
    lost_file = asset_file(lost)
    assert make_blob_store(client.app).delete(lost["media"]["digest"]["value"]) is True
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    after_image = next(item["props"]["image"] for item in born["pages"]["/analysis"]["content"] if item["props"]["id"] == "after")
    render = chromium_available()
    script = model.next(
        AIMessage(content="", tool_calls=[call("search_assets", {"q": "lost classroom"}, 1)]),
        AIMessage(content="", tool_calls=[
            call("edit_file", {"file_path": "/pages/analysis.json", "old_string": json.dumps(after_image),
                               "new_string": json.dumps(lost_file)}, 2),
            call("validate_page", {}, 3),
            *([call("render_page", {"route": "/analysis"}, 4)] if render else []),
        ]),
        AIMessage(content="Placed the classroom photo."),
    )
    turn = run_turn(client.app, store, document_id, REQUEST_1)
    found = json.loads(script.text_of("call_1"))
    assert lost_file in [row.get("file") for row in found["results"]], found
    assert script.text_of("call_3") == "VALID."
    if render:
        text = script.text_of("call_4")
        assert text.count("broken images: 1") == 2, text
    assert turn.status == "failed" and turn.response["error"]["code"] == "site_turn.write_refused"
    summary = turn.response["summary"]
    assert summary.startswith(f"The website could not be saved: image {lost_file} is not stored in this workspace"), summary
    nothing_saved(store, document_id, turn)
    assert "- Saved: no, the save was refused\n" in history_of(_agent_root, store, document_id)


# =================================================================================================
# F. Tenancy across two workspaces.
# =================================================================================================

#: A plain site site-kit's validator passes with no kit at all (Task 12's), for workspace B.
PLAIN_SHELL = {"header": {"id": "header", "preparedFor": "Acme", "ctaLabel": "Book a demo",
                          "ctaHref": "https://seller.example/demo"},
               "footer": {"id": "footer", "legal": "© Seller"}}


def plain_site(document_id: str) -> dict:
    return {"id": document_id, "title": "S", "theme": {}, "shell": PLAIN_SHELL, "agent_sections": {},
            "pages": {"/": {"root": {"props": {"title": "S"}}, "content": [{"type": "CtaBand", "props": {
                "id": "c", "surface": "brand", "heading": "Hello", "buttonLabel": "Book a demo",
                "buttonHref": "https://seller.example/demo"}}]}}}


@dataclass
class Tenant:
    workspace_id: str
    store: HybridRepository
    client: TestClient
    blobs: Any


def second_tenant(client: TestClient) -> Tenant:
    from lumen_api.design_store import DesignBlobStore

    workspace_id = f"ws_test_b_{uuid4().hex[:14]}"
    return Tenant(workspace_id, HybridRepository(workspace_id=workspace_id),
                  TestClient(client.app, headers={"X-Workspace-Id": workspace_id}),
                  DesignBlobStore(client.app.state.storage, workspace_id))


def quote_module(marker: str) -> tuple[str, str, str]:
    """A real compiled agent section (Lane A's QUOTE_JS), its source and CSS — made unique, so no
    other tenant's blob can share their bytes."""
    from site_kit_support import QUOTE_JS

    module_js = QUOTE_JS + f"// {marker}\n"
    source = f"// {marker}\nexport const schema = z.object({{ id: z.string() }});\n"
    css = f".quote-{marker}{{font-style:italic}}"
    return module_js, source, css


def record_section(client: TestClient, workspace_id: str, name: str, module_js: str, source: str, css: str,
                   run_id: str = "run_bv1a_sections"):
    return client.app.state.design_tools.invoke(
        "design_record_site_section", {"name": name, "source": source, "module_js": module_js, "css": css},
        workspace_id=workspace_id, actor="agent", actor_id=run_id)


@needs_chromium
def test_f_a_b_a_section_recorded_in_one_workspace_is_invisible_to_another(client: TestClient, model: ModelSeam,
                                                                          workspace_id: str) -> None:
    other = second_tenant(client)
    marker = uuid4().hex
    module_js, source, css = quote_module(marker)
    ref = record_section(client, workspace_id, "QuoteBand", module_js, source, css).references
    digest = hashlib.sha256(module_js.encode()).hexdigest()
    assert ref["digest"] == digest
    # B records its own section too (another name, other bytes).
    b_module, b_source, b_css = quote_module(marker + "b")
    b_ref = record_section(client, other.workspace_id, "StepsBand", b_module, b_source, b_css).references

    # (a) Each holds only its own — by digest, by the newest-of-each-name listing, and in a turn.
    store = HybridRepository()
    assert [row["name"] for row in store.get_site_sections([digest, b_ref["digest"]])] == ["QuoteBand"]
    assert [row["name"] for row in store.list_latest_site_sections()] == ["QuoteBand"]
    assert [row["name"] for row in other.store.get_site_sections([digest, b_ref["digest"]])] == ["StepsBand"]
    assert [row["name"] for row in other.store.list_latest_site_sections()] == ["StepsBand"]
    for tenant_store in (store, other.store):
        document_id = f"site_bv1a_{uuid4().hex[:10]}"
        tenant_store.create_document(plain_site(document_id), doc_kind="site")
        script = model.next(
            AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/catalog/seller-components.md"}, 1)]),
            AIMessage(content="Nothing to change."),
        )
        turn = run_turn(client.app, tenant_store, document_id, "Which sections can I use?")
        assert turn.status == "succeeded" and turn.response["outcome"] == "unchanged"
        listed = script.text_of("call_1")
        mine, theirs = ("QuoteBand", "StepsBand") if tenant_store is store else ("StepsBand", "QuoteBand")
        assert f"## {mine}" in listed and theirs not in listed, listed

    # (b) The public byte route serves none of either workspace's section files (to anyone), while
    # an ordinary image blob of A is served.
    for blobs, refs in ((make_blob_store(client.app), ref), (other.blobs, b_ref)):
        for file_digest in (refs["digest"], refs["source_sha256"], refs["css_sha256"]):
            assert blobs.read(file_digest)  # the workspace holds the bytes ...
            assert client.get(f"/asset-store/{file_digest}").status_code == 404  # ... and they are never served
            assert other.client.get(f"/asset-store/{file_digest}").status_code == 404
    photo = library_image(client, (12, 34, 56), f"ordinary-{marker}")
    served = other.client.get(asset_file(photo))
    assert served.status_code == 200 and hashlib.sha256(served.content).hexdigest() == photo["media"]["digest"]["value"]


def test_f_c_an_envelope_for_another_workspaces_document_writes_nothing(client: TestClient, model: ModelSeam,
                                                                       garner: Garner) -> None:
    store = HybridRepository()
    other = second_tenant(client)
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    # A's document id, executed under B's workspace (B's store, B's envelope, B's run row).
    turn = run_turn(client.app, other.store, document_id, REQUEST_1)
    assert turn.status == "failed" and turn.row["status"] == "failed"
    (diagnostic,) = turn.response["diagnostics"]
    assert "not found" in str(diagnostic.get("hint") or ""), diagnostic
    # Reported as a crash of the turn, naming the missing document (not a typed not-found code).
    assert diagnostic["code"] == "agent_runtime.failed"
    assert model.built == [] and turn.events == []
    stored = store.require_document(document_id)
    assert stored["current_version"] == 0 and stored["scene"] == born and store.list_envelopes(document_id) == []
    assert other.client.get(f"/documents/{document_id}").status_code == 404


def fake_image_provider(monkeypatch: pytest.MonkeyPatch, colour: tuple[int, int, int] = (90, 160, 200)) -> list:
    """``lumen_api.image_provider.generate`` returning real PNG bytes (no provider call)."""
    from PIL import Image
    import io

    import lumen_api.image_provider as image_provider

    asked: list = []

    def generate(*, prompt, aspect_ratio=None, reference_images=None, **kwargs):
        asked.append({"prompt": prompt, "aspect_ratio": aspect_ratio, "references": len(reference_images or [])})
        buffer = io.BytesIO()
        Image.new("RGB", (160, 120), colour).save(buffer, format="PNG")
        return image_provider.ImageGenerationResult(
            image_bytes=buffer.getvalue(), mime_type="image/png", model="fake/image-model",
            provenance={"provider": "fake", "prompt": prompt}, width=160, height=120)

    monkeypatch.setattr(image_provider, "generate", generate)
    return asked


def library(tenant_client: TestClient) -> list[dict]:
    response = tenant_client.get("/assets", params={"limit": 200})
    assert response.status_code == 200, response.text
    return response.json()["assets"]


def generated_file(script: Script, call_id: str) -> str:
    text = script.text_of(call_id)
    assert text.startswith("/asset-store/"), text
    return text.split(" ", 1)[0]


def test_f_d_a_generated_image_stays_in_its_workspace(client: TestClient, model: ModelSeam, garner: Garner,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    asked = fake_image_provider(monkeypatch)
    store = HybridRepository()
    other = second_tenant(client)
    prompt = "A calm classroom in morning light"

    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    store_site(garner.site(document_id))
    script = model.next(
        AIMessage(content="", tool_calls=[call("generate_image", {"prompt": prompt, "aspect_ratio": "4:3"}, 1)]),
        AIMessage(content="Made an image; it is not placed yet."),
    )
    turn = run_turn(client.app, store, document_id, "Make a classroom photo.")
    assert turn.status == "succeeded" and asked and asked[0]["prompt"] == prompt
    file = generated_file(script, "call_1")
    digest = file.rsplit("/", 1)[1]

    # A's library holds it as an AI-generated asset, with readable bytes in A's custody.
    from lumen_api.design_store import CustodyState

    (row,) = [asset for asset in library(client) if (asset.get("media") or {}).get("digest", {}).get("value") == digest]
    assert (row.get("source") or {}).get("kind") == "generated" and row["label"] == prompt
    assert make_blob_store(client.app).custody_states([digest]).get(digest) is CustodyState.READABLE

    # B's library does not list it, and B's search_assets does not find it (B's own photo, found by
    # the same words, proves the search ran over a non-empty library).
    assert digest not in json.dumps(library(other.client))
    own = library_image(client, (40, 160, 60), "calm classroom morning light (B)", workspace_id=other.workspace_id)
    b_document = f"site_bv1a_{uuid4().hex[:10]}"
    other.store.create_document(plain_site(b_document), doc_kind="site")
    b_script = model.next(
        AIMessage(content="", tool_calls=[call("search_assets", {"q": "calm classroom morning light"}, 1)]),
        AIMessage(content="Nothing to change."),
    )
    run_turn(client.app, other.store, b_document, "Find a classroom photo.")
    found = json.loads(b_script.text_of("call_1"))
    assert [row["asset_id"] for row in found["results"]] == [own["id"]], found
    assert digest not in b_script.text_of("call_1")


# =================================================================================================
# G. The section tool under governance.
# =================================================================================================


def query(sql: str, params: dict) -> list[dict]:
    """One read of the platform journal tables the design invoker writes."""
    import asyncio

    from clue_db import create_engine
    from sqlalchemy import text

    async def run() -> list[dict]:
        engine = create_engine()
        try:
            async with engine.connect() as conn:
                return [dict(row) for row in (await conn.execute(text(sql), params)).mappings().all()]
        finally:
            await engine.dispose()

    return asyncio.run(run())


#: A module site-kit compiles but whose props schema cannot be read: it exports no `schema`.
NO_SCHEMA_JS = """import { jsx } from "react/jsx-runtime";
export function render(props, kit) {
  return jsx(kit.Shell, { surface: props.surface, children: jsx("p", { children: props.quote }) });
}
"""


@needs_chromium
def test_g_the_section_tool_under_governance(client: TestClient, workspace_id: str) -> None:
    from lumen_api.toolbelt.site_sections import SiteSectionRefused

    marker = uuid4().hex
    module_js, source, css = quote_module(marker)
    digest = hashlib.sha256(module_js.encode()).hexdigest()
    store, blobs = HybridRepository(), make_blob_store(client.app)

    first = record_section(client, workspace_id, "QuoteBand", module_js, source, css, run_id="run_bv1a_g1").references
    assert first == {"digest": digest, "name": "QuoteBand", "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                     "css_sha256": hashlib.sha256(css.encode()).hexdigest()}
    (row,) = store.get_site_sections([digest])
    # The schema is the module's OWN, read in the hardened page: zod's object, as JSON Schema.
    assert row["created_by_run_id"] == "run_bv1a_g1"
    assert set(row["props_schema"]["properties"]) == {"id", "surface", "quote"}
    assert row["props_schema"]["properties"]["surface"]["enum"] == ["page", "card", "muted", "brandSubtle", "brand", "inverse"]
    assert (blobs.read(digest).decode(), blobs.read(first["source_sha256"]).decode(), blobs.read(first["css_sha256"]).decode()) == (
        module_js, source, css)

    # The same module again converges on the one row.
    again = record_section(client, workspace_id, "QuoteBand", module_js, source, css, run_id="run_bv1a_g2").references
    assert again == first
    assert len(store.get_site_sections([digest])) == 1
    assert [r["digest"] for r in store.list_latest_site_sections()] == [digest]

    # A module whose schema cannot be read is refused, and nothing is stored.
    bad_js = NO_SCHEMA_JS + f"// {marker}-bad\n"
    bad = hashlib.sha256(bad_js.encode()).hexdigest()
    with pytest.raises(SiteSectionRefused) as refused:
        record_section(client, workspace_id, "BrokenBand", bad_js, f"// {marker}-bad-source\n", "", run_id="run_bv1a_g3")
    assert refused.value.code == "render.failed" and "schema" in refused.value.message, refused.value.message
    assert store.get_site_sections([bad]) == [] and [r["name"] for r in store.list_latest_site_sections()] == ["QuoteBand"]
    from lumen_api.design_store import CustodyState

    assert blobs.custody_states([bad]).get(bad) is not CustodyState.READABLE

    # Journaled like every governed design write: three invocations on the platform journal.
    nodes = query(
        "SELECT n.id, n.tool_name, n.tool_version, n.parameter_artifact_key, n.display_params_json, n.definition_json "
        "FROM execution_node n JOIN execution e ON e.id = n.execution_id "
        "WHERE e.workspace_id = :w AND n.tool_name = 'design_record_site_section' ORDER BY n.created_at",
        {"w": workspace_id})
    assert [(n["tool_version"], n["display_params_json"]) for n in nodes] == [
        ("1", {"name": "QuoteBand"}), ("1", {"name": "QuoteBand"}), ("1", {"name": "BrokenBand"})]
    assert all(str(n["parameter_artifact_key"]).startswith(f"{workspace_id}/") for n in nodes)
    events = query(
        "SELECT ev.* FROM execution_event ev JOIN execution e ON e.id = ev.execution_id WHERE e.workspace_id = :w "
        "ORDER BY ev.seq", {"w": workspace_id})
    by_node = {n["id"]: [ev["event_type"] for ev in events if ev["node_id"] == n["id"]] for n in nodes}
    outcomes = [[t for t in by_node[n["id"]] if t.startswith("node.") and t not in ("node.scheduled", "node.started")]
                for n in nodes]
    assert outcomes == [["node.completed"], ["node.completed"], ["node.failed"]], outcomes
    # The A9 record holds the two completed writes; the refused one is a failed node, never cached.
    invocations = query("SELECT * FROM tool_invocation WHERE workspace_id = :w AND tool_name = 'design_record_site_section@1'",
                        {"w": workspace_id})
    assert sorted(row["status"] for row in invocations) == ["completed", "completed"], invocations
    # The module's code never lands in the journal's own rows: only the safe-display name does.
    journal = json.dumps([*nodes, *invocations, *events], default=str)
    assert marker not in journal and "jsx(kit.Shell" not in journal


# --- G, continued: a recorded section, offered to the next turn ---------------------------------


def place_a_recorded_section(client: TestClient, model: ModelSeam, garner: Garner, workspace_id: str) -> dict:
    """Task 14 records a section; Task 8 offers it to the next turn (catalog/seller-components.md);
    the agent places it; Task 6 validates it by its STORED schema; Task 9 draws it in the hardened
    page; Task 12 persists the site through Lane A's save."""
    marker = uuid4().hex
    module_js, source, css = quote_module(marker)
    digest = record_section(client, workspace_id, "QuoteBand", module_js, source, css).references["digest"]
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    store_site(garner.site(document_id))
    quote = {"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": "Fewer surprises for SCSD."}}
    script = model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/catalog/seller-components.md"}, 1)]),
        AIMessage(content="", tool_calls=[
            call("edit_file", {"file_path": "/page.json", "old_string": '"content": [',
                               "new_string": '"content": [' + json.dumps(quote) + ","}, 2),
            call("validate_page", {}, 3),
            call("render_page", {"route": "/"}, 4),
        ]),
        AIMessage(content="Added the seller's quote band."),
    )
    turn = run_turn(client.app, store, document_id, "Add the quote band under the proof.")
    return {"store": store, "document_id": document_id, "digest": digest, "quote": quote, "turn": turn, "script": script}


@needs_chromium
def test_g_a_recorded_section_is_offered_validated_and_drawn(client: TestClient, model: ModelSeam, garner: Garner,
                                                             workspace_id: str) -> None:
    state = place_a_recorded_section(client, model, garner, workspace_id)
    script = state["script"]
    assert "## QuoteBand" in script.text_of("call_1") and '"quote"' in script.text_of("call_1")
    assert script.text_of("call_3") == "VALID."
    drawn = script.text_of("call_4")
    assert drawn.count("broken images: 0") == 2 and "NOT RENDERED" not in drawn, drawn


@needs_chromium
def test_g_a_recorded_section_placed_by_the_agent_is_saved(client: TestClient, model: ModelSeam, garner: Garner,
                                                           workspace_id: str) -> None:
    """The turn host's design_write_site loads the workspace's recorded modules, so a section the turn
    offers is saved once placed (Lane B Task 15 composed the loader; was DEFECT 4)."""
    state = place_a_recorded_section(client, model, garner, workspace_id)
    turn, store, document_id = state["turn"], state["store"], state["document_id"]
    assert turn.status == "succeeded" and turn.response["saved_version"] == 1, turn.response.get("summary")
    stored = store.require_document(document_id)["scene"]
    assert stored["agent_sections"] == {"QuoteBand": state["digest"]}
    assert stored["pages"]["/"]["content"][0] == state["quote"]


# =================================================================================================
# H. A generated image, placed and saved.
# =================================================================================================


def test_h_a_generated_image_placed_and_saved(client: TestClient, model: ModelSeam, garner: Garner,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """One turn: generate_image (the provider faked; the bytes ingested by the REAL engine core,
    ``create_app``'s ``app.state.core``, through the real ``DurableSiteAssetPort``) → the agent puts
    the path it was given into an image prop → validate_page → render_page → the save."""
    from lumen_api.design_store import CustodyState

    asked = fake_image_provider(monkeypatch, colour=(30, 120, 110))
    store = HybridRepository()
    document_id = f"site_bv1a_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    after_image = next(item["props"]["image"] for item in born["pages"]["/analysis"]["content"] if item["props"]["id"] == "after")
    prompt = "An HR team reviewing a provider report, morning light"
    render = chromium_available()
    holder: dict = {}

    def steps():
        yield AIMessage(content="", tool_calls=[call("generate_image", {"prompt": prompt, "aspect_ratio": "4:3"}, 1)])
        # The path the tool returned, as the agent read it from the tool's answer.
        holder["file"] = generated_file(holder["script"], "call_1")
        yield AIMessage(content="", tool_calls=[
            call("edit_file", {"file_path": "/pages/analysis.json", "old_string": json.dumps(after_image),
                               "new_string": json.dumps(holder["file"])}, 2),
            call("validate_page", {}, 3),
            *([call("render_page", {"route": "/analysis"}, 4)] if render else []),
        ])
        yield AIMessage(content="The after-the-review section shows the new photo.")

    holder["script"] = script = Script(messages=steps())
    model.scripts.append(script)
    turn = run_turn(client.app, store, document_id, "Give the after-the-review section its own photo.")
    file = holder["file"]
    digest = file.rsplit("/", 1)[1]

    assert asked == [{"prompt": prompt, "aspect_ratio": "4:3", "references": 0}]
    assert script.images_of("call_1") == 1  # the agent was shown its image
    # Custody: the bytes are durable and readable in this workspace; the library row is AI-generated.
    blobs = make_blob_store(client.app)
    assert blobs.custody_states([digest]).get(digest) is CustodyState.READABLE
    media_type, data = blobs.read_blob(digest)
    assert media_type == "image/png" and hashlib.sha256(data).hexdigest() == digest
    (row,) = [asset for asset in library(client) if (asset.get("media") or {}).get("digest", {}).get("value") == digest]
    assert (row["source"] or {}).get("kind") == "generated" and row["id"].startswith("asset_gen_")
    assert (row["source"] or {}).get("model") == "fake/image-model" and row["label"] == prompt

    assert script.text_of("call_3") == "VALID."
    if render:
        assert script.text_of("call_4").count("broken images: 0") == 2, script.text_of("call_4")
    # The save accepted it (custody satisfied); version 1 holds the path.
    assert turn.status == "succeeded" and turn.response["saved_version"] == 1, turn.response
    stored = store.require_document(document_id)
    after = next(item for item in stored["scene"]["pages"]["/analysis"]["content"] if item["props"]["id"] == "after")
    assert after["props"]["image"] == file and stored["current_version"] == 1
    assert saves(turn) == [("site_document_saved", {"document_id": document_id, "version": 1})]
    # The editor's read serves the bytes the page names.
    served = client.get(file)
    assert served.status_code == 200 and served.content == data


# =================================================================================================
# I. The fenced, idempotent save (site-turn durability, K4-1, 2026-10-16).
#
# Each attempt below holds the run the way the fleet holds it: a REAL ``work_lease`` row taken
# with ``clue_fleet``'s own acquire (generations never repeat, Task 1), then the run claimed under
# that generation. A takeover lets the lease lapse and acquires it as another worker, exactly the
# state a dead or stalled worker leaves behind.
# =================================================================================================

PROOF_A = "Attempt A's proof heading"
PROOF_B = "Attempt B's proof heading"


def take_lease(store: HybridRepository, work_id: Any, worker_id: str) -> int:
    from clue_fleet.lease import acquire_work_lease

    lease = store._bridge._run(lambda conn: acquire_work_lease(conn, work_id=work_id, worker_id=worker_id))
    assert lease is not None, f"{worker_id} could not take the lease"
    return int(lease.generation)


def lapse_lease(store: HybridRepository, work_id: Any) -> None:
    from sqlalchemy import text

    store._bridge._run(lambda conn: conn.execute(
        text("UPDATE work_lease SET expires_at = now() - interval '1 second' WHERE work_id = :w"), {"w": work_id}))


def hold_run(store: HybridRepository, envelope: Any, worker_id: str) -> int:
    """The fleet's way into a run: take the work lease, then claim the run under its generation."""
    from clue_design import runs as design_runs

    generation = take_lease(store, envelope.work_id, worker_id)
    claimed = store._bridge._run(lambda conn: design_runs.claim_run_for_execution(
        conn, work_id=envelope.work_id, worker_id=worker_id, lease_generation=generation))
    assert claimed is not None and claimed["lease_generation"] == generation
    return generation


def take_over(store: HybridRepository, envelope: Any, worker_id: str) -> int:
    """A second worker takes the run: the first holder's lease lapses, the second acquires it."""
    lapse_lease(store, envelope.work_id)
    return hold_run(store, envelope, worker_id)


def attempt_turn(app: Any, store: HybridRepository, envelope: Any, *, worker_id: str, generation: int) -> Turn:
    """One attempt at a site turn through the REAL executor, as the worker holding ``generation``.
    Not completed: the caller lands (or is refused) the terminal write itself."""
    from lumen_api.main import execute_site_turn_job

    events: list = []
    status, response, event_type, event_data = execute_site_turn_job(
        envelope, store=store, host=turn_host(app), event_sink=lambda kind, data: events.append((kind, data)),
        lease_generation=generation, lease_worker_id=worker_id,
    )
    return Turn(envelope.run_id, status, response, events, {}, (event_type, event_data))


def run_columns(run_id: str) -> dict:
    (row,) = query("SELECT status, leased_by, lease_generation FROM design_agent_run WHERE run_id = :r", {"r": run_id})
    return row


def proof_edit(site: dict, text_: str, n: int) -> list[AIMessage]:
    return [
        AIMessage(content="", tool_calls=[edit_heading_call(site, "/", "proof", text_, n), call("validate_page", {}, n + 1)]),
        AIMessage(content=f"The proof heading now reads {text_!r}."),
    ]


def fresh_site_run(garner: Garner) -> tuple[HybridRepository, str, dict, Any]:
    store = HybridRepository()
    document_id = f"site_fence_{uuid4().hex[:10]}"
    born = store_site(garner.site(document_id))["scene"]
    envelope = envelope_for(document_id, store.workspace_id, REQUEST_1)
    open_run(store, envelope, claim=False)
    return store, document_id, born, envelope


def test_i_a_a_fenced_out_attempt_saves_nothing_and_the_holder_saves_after_it(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """Attempt A holds the run at generation 1. While A's agent works, A's lease lapses and worker B
    acquires it (generation 2) and claims the run. A's agent finishes and A's save is refused: it no
    longer holds the run. Nothing is written, nothing claims a save, A writes no terminal result and
    no history. B's own save then lands, so a refused save never blocks the run's real holder. A
    human save meanwhile meets exactly the lock it met before (the run is active), and lands once
    B's run is done."""
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    held: dict = {}

    def b_takes_over() -> None:
        held["b"] = take_over(store, envelope, "worker-b")

    model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/page.json"}, 1)]),
        *proof_edit(born, PROOF_A, 2),
        hooks={1: b_takes_over},
    )
    a = attempt_turn(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    generation_b = held["b"]
    assert generation_b == generation_a + 1

    assert a.status == "fenced", a.response
    assert a.response["saved_version"] is None and a.response["error"]["code"] == "site_turn.fenced"
    assert saves(a) == []
    stored = store.require_document(document_id)
    assert stored["current_version"] == 0 and stored["scene"] == born
    assert store.list_envelopes(document_id) == []
    # A fenced attempt leaves the session folder alone: no "## 1." entry claims anything.
    history = session_folder(_agent_root, store.workspace_id, document_id) / "workspace" / "history.md"
    assert not history.exists() or "## " not in history.read_text()
    assert run_columns(envelope.run_id) == {"status": "running", "leased_by": "worker-b",
                                            "lease_generation": generation_b}

    # A human save while B's run is active meets the agent-run lock, as before this change.
    refused = put_site(client, document_id, with_heading(born, "/", "proof", "Human edit"), 0)
    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "document.agent_run_active", "run_id": envelope.run_id}

    # B, the holder, saves.
    model.next(*proof_edit(born, PROOF_B, 1))
    b = attempt_turn(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    assert b.status == "succeeded" and b.response["saved_version"] == 1, b.response
    assert saves(b) == [("site_document_saved", {"document_id": document_id, "version": 1})]
    assert store.require_document(document_id)["scene"] == with_heading(born, "/", "proof", PROOF_B)
    assert len(store.list_envelopes(document_id)) == 1
    store.complete_run(envelope.run_id, b.status, b.response, *b.terminal, expected_generation=generation_b)
    assert store.require_run(envelope.run_id)["status"] == "succeeded"

    # The run is done, so the human's save lands on top of B's.
    expect_ok(put_site(client, document_id, with_heading(born, "/", "proof", "Human edit"), 1), 2, document_id)


def test_i_b_a_fenced_attempt_through_the_fleet_handler_writes_no_terminal_result(
        client: TestClient, model: ModelSeam, garner: Garner) -> None:
    """The same takeover through the fleet's own handler (``DesignJobWorkHandler``), which is where
    the attempt's worker id and generation come from in production. A's save is refused, the
    handler reports the attempt fenced, and the run row stays B's: no terminal write landed on it,
    which matters most when only the LEASE has moved and B has not claimed the run yet."""
    import asyncio

    from clue_fleet import WorkContext
    from lumen_api.fleet_handler import DesignJobWorkHandler

    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = take_lease(store, envelope.work_id, "worker-a")

    def b_takes_the_lease_only() -> None:
        lapse_lease(store, envelope.work_id)
        take_lease(store, envelope.work_id, "worker-b")

    model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/page.json"}, 1)]),
        *proof_edit(born, PROOF_A, 2),
        hooks={1: b_takes_the_lease_only},
    )
    handler = DesignJobWorkHandler(host_provider=lambda: turn_host(client.app), named_trace=False)
    context = WorkContext(task_id=uuid4(), work_id=envelope.work_id, worker_id="worker-a",
                          lease_generation=generation_a, payload=envelope.model_dump(mode="json"),
                          stop_requested=asyncio.Event(), lease_lost=asyncio.Event())
    result = asyncio.run(handler.handle(context))

    assert result.outcome == "fenced", result
    stored = store.require_document(document_id)
    assert stored["current_version"] == 0 and stored["scene"] == born
    assert store.list_envelopes(document_id) == []
    # The run row is still A's claim, untouched by any terminal write: B's claim can take it.
    assert run_columns(envelope.run_id) == {"status": "running", "leased_by": "worker-a",
                                            "lease_generation": generation_a}
    assert store.require_run(envelope.run_id)["result"] is None


def test_i_c_a_lapsed_lease_nobody_took_still_lets_its_holder_save(
        client: TestClient, model: ModelSeam, garner: Garner) -> None:
    """A's lease lapses mid-turn but nobody takes it: the lease is still A's (Task 1's reclaim
    rule), so A's save lands and A's terminal write lands after it."""
    store, document_id, born, envelope = fresh_site_run(garner)
    generation = hold_run(store, envelope, "worker-a")
    model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/page.json"}, 1)]),
        *proof_edit(born, PROOF_A, 2),
        hooks={1: lambda: lapse_lease(store, envelope.work_id)},
    )
    a = attempt_turn(client.app, store, envelope, worker_id="worker-a", generation=generation)
    assert a.status == "succeeded" and a.response["saved_version"] == 1, a.response
    assert store.require_document(document_id)["scene"] == with_heading(born, "/", "proof", PROOF_A)
    store.complete_run(envelope.run_id, a.status, a.response, *a.terminal, expected_generation=generation)
    assert store.require_run(envelope.run_id)["status"] == "succeeded"


def test_i_d_a_retried_save_of_the_same_site_is_one_version(
        client: TestClient, model: ModelSeam, garner: Garner, monkeypatch: pytest.MonkeyPatch) -> None:
    """The holder's save is delivered twice (an at-least-once retry of the same call, same attempt,
    same site). The second is a replay of the first: one version, one history step, and the turn
    reports the version the save made."""
    from lumen_api.toolbelt.wiring import DesignToolInvocations

    real_invoke = DesignToolInvocations.invoke
    delivered: list = []

    def invoke_twice(self, name, body, **kwargs):
        if name != "design_write_site":
            return real_invoke(self, name, body, **kwargs)
        delivered.append(real_invoke(self, name, body, **kwargs))
        delivered.append(real_invoke(self, name, body, **kwargs))
        return delivered[-1]

    monkeypatch.setattr(DesignToolInvocations, "invoke", invoke_twice)
    store, document_id, born, envelope = fresh_site_run(garner)
    generation = hold_run(store, envelope, "worker-a")
    model.next(*proof_edit(born, PROOF_A, 1))
    a = attempt_turn(client.app, store, envelope, worker_id="worker-a", generation=generation)

    first, second = delivered
    assert (first.replayed, second.replayed) == (False, True)
    assert first.references["current_version"] == second.references["current_version"] == 1
    assert a.status == "succeeded" and a.response["saved_version"] == 1
    assert store.require_document(document_id)["current_version"] == 1
    assert len(store.list_envelopes(document_id)) == 1
    assert saves(a) == [("site_document_saved", {"document_id": document_id, "version": 1})]


def test_i_e_a_takeover_after_the_save_landed_never_makes_a_second_version(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """A saves (version 1) and dies before its terminal write. B takes the run over and redoes the
    request. If B ends with the site A saved, there is nothing to save; if B ends with a DIFFERENT
    site, its save is refused as a second save by this run. Either way there is still one version,
    and the request IS saved as it: B reports version 1 as saved (the request's result), not a
    turn that saved nothing."""
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    model.next(*proof_edit(born, PROOF_A, 1))
    a = attempt_turn(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    assert a.response["saved_version"] == 1  # ...and A dies here, before complete_run.
    saved_by_a = with_heading(born, "/", "proof", PROOF_A)

    # B redoes the request and ends where A did: nothing new to save, the request saved as version 1.
    generation_b = take_over(store, envelope, "worker-b")
    model.next(AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/page.json"}, 1)]),
               AIMessage(content="The proof heading already reads as asked."))
    same = attempt_turn(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    assert same.status == "succeeded" and same.response["outcome"] == "saved", same.response
    assert same.response["saved_version"] == same.response["current_version"] == 1
    assert saves(same) == [("site_document_saved", {"document_id": document_id, "version": 1})]
    assert store.require_document(document_id)["current_version"] == 1

    # A third attempt redoes it differently: its save is refused, still one version, and the
    # request is reported saved as that version.
    generation_c = take_over(store, envelope, "worker-c")
    model.next(*proof_edit(saved_by_a, PROOF_B, 1))
    different = attempt_turn(client.app, store, envelope, worker_id="worker-c", generation=generation_c)
    assert different.status == "succeeded" and different.response["outcome"] == "saved", different.response
    assert different.response["saved_version"] == different.response["current_version"] == 1
    assert saves(different) == [("site_document_saved", {"document_id": document_id, "version": 1})]
    # C's own words describe an edit that was never saved; it says what was saved instead.
    assert different.response["summary"] == "Saved this request as version 1."
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1 and stored["scene"] == saved_by_a
    assert len(store.list_envelopes(document_id)) == 1
    history = (session_folder(_agent_root, store.workspace_id, document_id) / "workspace" / "history.md").read_text()
    assert "already saved" not in history
    # The request has ONE entry, written by A; the attempts that finished it again did not repeat it.
    lines = history.splitlines()
    assert [line for line in lines if line.startswith("- Saved:")] == ["- Saved: as version 1"]
    assert [line for line in lines if line.startswith("- What changed:")] == ["- What changed: /: changed proof (heading)"]
    finish(store, different, generation_c)


# =================================================================================================
# J. A turn taken over after its worker dies continues from its working copy (site-turn
#    durability, Task 3, 2026-10-16).
#
# Each attempt runs through the REAL executor with the REAL Postgres checkpointer
# (``postgres_design_checkpointer``, the one the fleet composes) and holds the run the way the
# fleet does (section I's real lease + claim). A worker's death is ``WorkerDied``, a BaseException
# no ``except Exception`` in the turn can swallow. The takeover runs on ANOTHER disk: the session
# folder the dead attempt used is deleted first.
# =================================================================================================

CTA_A = "Request SCSD's free analysis, attempt A"


class WorkerDied(BaseException):
    """The worker process died here."""


def die() -> None:
    raise WorkerDied()


def durable_attempt(app: Any, store: HybridRepository, envelope: Any, *, worker_id: str, generation: int) -> Turn:
    """One attempt through the real executor on the real Postgres checkpointer, as the fleet runs it."""
    from lumen_api.fleet_handler import postgres_design_checkpointer
    from lumen_api.main import execute_site_turn_job

    events: list = []
    with postgres_design_checkpointer(envelope.run_id) as saver:
        status, response, event_type, event_data = execute_site_turn_job(
            envelope, store=store, host=turn_host(app), event_sink=lambda kind, data: events.append((kind, data)),
            checkpointer=saver, lease_generation=generation, lease_worker_id=worker_id,
        )
    return Turn(envelope.run_id, status, response, events, {}, (event_type, event_data))


def dies(app: Any, store: HybridRepository, envelope: Any, *, worker_id: str, generation: int) -> None:
    with pytest.raises(WorkerDied):
        durable_attempt(app, store, envelope, worker_id=worker_id, generation=generation)


def another_disk(agent_root: Path, store: HybridRepository, document_id: str) -> None:
    """The takeover's worker has none of the dead worker's local files."""
    shutil.rmtree(session_folder(agent_root, store.workspace_id, document_id), ignore_errors=True)


def checkpoint_rows(run_id: str) -> int:
    (row,) = query("SELECT count(*) AS n FROM checkpoints WHERE thread_id = :r", {"r": run_id})
    return int(row["n"])


def finish(store: HybridRepository, turn: Turn, generation: int) -> None:
    store.complete_run(turn.run_id, turn.status, turn.response, *turn.terminal, expected_generation=generation)


def tool_results_in(messages: list) -> set[str]:
    return {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}


def test_j_a_dies_right_before_the_save_and_the_takeover_saves_what_it_built(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The K4-1 probe. A builds the page and dies at its save. B, on another disk, restores A's
    files and the conversation at A's last step: it makes no model call and saves A's page."""
    from lumen_api.toolbelt.wiring import DesignToolInvocations

    real_invoke = DesignToolInvocations.invoke
    deaths: list = []

    def die_at_the_first_save(self, name, body, **kwargs):
        if name == "design_write_site" and not deaths:
            deaths.append(body["attempt"])
            die()
        return real_invoke(self, name, body, **kwargs)

    monkeypatch.setattr(DesignToolInvocations, "invoke", die_at_the_first_save)
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    a = model.next(*proof_edit(born, PROOF_A, 1))
    dies(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    assert len(a.seen) == 2 and deaths and deaths[0]["lease_generation"] == generation_a
    copy = store.get_site_turn_workspace(envelope.run_id)
    assert copy is not None and PROOF_A in copy["files"]["page.json"] and copy["attempt_generation"] == generation_a
    assert store.require_document(document_id)["current_version"] == 0

    another_disk(_agent_root, store, document_id)
    generation_b = take_over(store, envelope, "worker-b")
    b = model.next()
    turn = durable_attempt(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    assert b.seen == [], "the takeover asked the model again for finished work"
    assert turn.status == "succeeded" and turn.response["saved_version"] == 1, turn.response
    assert turn.response["summary"] == f"The proof heading now reads {PROOF_A!r}."
    assert store.require_document(document_id)["scene"] == with_heading(born, "/", "proof", PROOF_A)
    assert saves(turn) == [("site_document_saved", {"document_id": document_id, "version": 1})]

    finish(store, turn, generation_b)
    assert store.get_site_turn_workspace(envelope.run_id) is None and checkpoint_rows(envelope.run_id) == 0


def test_j_b_dies_mid_turn_and_the_takeover_does_not_rebuild_its_pages(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """A edits two pages (one round each) and dies before its third model call. B continues: its
    first call already holds both edits, it only validates and answers, and the save has both. The
    round and time counters carry over."""
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    a = model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/", "proof", PROOF_A, 1)]),
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/analysis", "cta", CTA_A, 2)]),
        AIMessage(content="", tool_calls=[call("validate_page", {}, 3)]),
        AIMessage(content="never reached"),
        hooks={2: die},
    )
    dies(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    assert len(a.seen) == 3
    copy_a = store.get_site_turn_workspace(envelope.run_id)
    assert copy_a["turn_state"]["rounds"] == 2

    another_disk(_agent_root, store, document_id)
    generation_b = take_over(store, envelope, "worker-b")
    b = model.next(AIMessage(content="", tool_calls=[call("validate_page", {}, 13)]),
                   AIMessage(content="Both headings are updated."))
    turn = durable_attempt(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    assert len(b.seen) == 2
    assert {"call_1", "call_2"} <= tool_results_in(b.seen[0])
    assert b.text_of("call_13") == "VALID."
    assert turn.status == "succeeded" and turn.response["saved_version"] == 1, turn.response
    both = with_heading(with_heading(born, "/", "proof", PROOF_A), "/analysis", "cta", CTA_A)
    assert store.require_document(document_id)["scene"] == both
    # A used rounds 1-2; B's are rounds 3 and 4, not a fresh 1 and 2.
    copy_b = store.get_site_turn_workspace(envelope.run_id)
    assert copy_b["turn_state"]["rounds"] == 4
    assert copy_b["turn_state"]["seconds_used"] >= copy_a["turn_state"]["seconds_used"]
    assert copy_b["attempt_generation"] == generation_b

    finish(store, turn, generation_b)
    assert store.get_site_turn_workspace(envelope.run_id) is None and checkpoint_rows(envelope.run_id) == 0


def test_j_b2_read_only_rounds_are_not_redone_after_a_takeover(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """A edits two pages (rounds 1 and 2), then only reads for three rounds, and dies at its sixth
    model call. Each read-only round re-stamped the copy, so B resumes at round 5's checkpoint: it
    makes exactly one model call for the step that was in flight (already holding all five rounds)
    before answering, and its restored round counter is 5."""
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    a = model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/", "proof", PROOF_A, 1)]),
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/analysis", "cta", CTA_A, 2)]),
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/page.json"}, 3)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 4)]),
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/pages/analysis.json"}, 5)]),
        AIMessage(content="never reached"),
        hooks={5: die},
    )
    dies(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    assert len(a.seen) == 6
    copy_a = store.get_site_turn_workspace(envelope.run_id)
    assert copy_a["turn_state"]["rounds"] == 5
    assert PROOF_A in copy_a["files"]["page.json"] and CTA_A in copy_a["files"]["pages/analysis.json"]

    another_disk(_agent_root, store, document_id)
    generation_b = take_over(store, envelope, "worker-b")
    b = model.next(AIMessage(content="Both headings are updated."))
    turn = durable_attempt(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    assert len(b.seen) == 1, "the takeover redid read-only rounds"
    assert {f"call_{n}" for n in range(1, 6)} <= tool_results_in(b.seen[0])
    assert turn.status == "succeeded" and turn.response["saved_version"] == 1, turn.response
    both = with_heading(with_heading(born, "/", "proof", PROOF_A), "/analysis", "cta", CTA_A)
    assert store.require_document(document_id)["scene"] == both
    assert store.get_site_turn_workspace(envelope.run_id)["turn_state"]["rounds"] == 6

    finish(store, turn, generation_b)
    assert store.get_site_turn_workspace(envelope.run_id) is None and checkpoint_rows(envelope.run_id) == 0


def test_j_c_a_crash_between_a_checkpoint_and_its_copy_redoes_at_most_one_round(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A's round-2 checkpoint is committed but A dies while writing the copy that matches it. B
    resumes from the copy before it: round 1 stands, only round 2 is asked again."""
    real_put = HybridRepository.put_site_turn_workspace
    writes: list = []

    # Copies: the starting one (before call 1), round 1's (before call 2), round 2's (before call 3).
    def die_on_round_twos_copy(self, run_id, **kwargs):
        writes.append(kwargs["checkpoint_id"])
        if len(writes) == 3:
            die()
        return real_put(self, run_id, **kwargs)

    monkeypatch.setattr(HybridRepository, "put_site_turn_workspace", die_on_round_twos_copy)
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    a = model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/", "proof", PROOF_A, 1)]),
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/analysis", "cta", CTA_A, 2)]),
        AIMessage(content="never reached"),
    )
    dies(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    assert len(a.seen) == 2 and len(writes) == 3
    copy = store.get_site_turn_workspace(envelope.run_id)
    assert copy["checkpoint_id"] == writes[1] and CTA_A not in copy["files"]["pages/analysis.json"]
    monkeypatch.setattr(HybridRepository, "put_site_turn_workspace", real_put)

    another_disk(_agent_root, store, document_id)
    generation_b = take_over(store, envelope, "worker-b")
    b = model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/analysis", "cta", CTA_A, 12),
                                          call("validate_page", {}, 13)]),
        AIMessage(content="Both headings are updated."),
    )
    turn = durable_attempt(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    seen = tool_results_in(b.seen[0])
    assert "call_1" in seen and "call_2" not in seen  # round 1 kept, round 2 redone
    assert len(b.seen) == 2 and b.text_of("call_13") == "VALID."
    assert turn.status == "succeeded" and turn.response["saved_version"] == 1, turn.response
    assert store.require_document(document_id)["scene"] == with_heading(
        with_heading(born, "/", "proof", PROOF_A), "/analysis", "cta", CTA_A)


def test_j_d_a_death_in_the_first_round_redoes_only_that_round_and_the_site_is_saved(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A dies in its first round, after its edit landed in its folder. The copy written before its
    first model call (the files as the turn started) is stamped with that call's checkpoint, so B
    resumes there: it redoes only the round in flight, never resuming the later checkpoints over
    a folder that lacks their edit (which would end the turn "unchanged"), and the edit is saved."""
    from lumen_agent.site.tools import SiteTools

    real_validate = SiteTools.validate_page
    died: list = []

    def die_once(self):
        if not died:
            died.append(True)
            die()
        return real_validate(self)

    monkeypatch.setattr(SiteTools, "validate_page", die_once)
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    model.next(*proof_edit(born, PROOF_A, 1))
    dies(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    start = store.get_site_turn_workspace(envelope.run_id)
    assert start is not None and start["turn_state"]["rounds"] == 0
    assert PROOF_A not in json.dumps(start["files"])
    assert checkpoint_rows(envelope.run_id) > 0

    another_disk(_agent_root, store, document_id)
    generation_b = take_over(store, envelope, "worker-b")
    b = model.next(*proof_edit(born, PROOF_A, 11))
    turn = durable_attempt(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    first = b.seen[0]
    assert not tool_results_in(first) and not [m for m in first if isinstance(m, AIMessage)]
    assert sum(isinstance(m, HumanMessage) for m in first) == 1
    assert turn.status == "succeeded" and turn.response["outcome"] == "saved", turn.response
    assert store.require_document(document_id)["scene"] == with_heading(born, "/", "proof", PROOF_A)


@needs_chromium
def test_j_e_a_section_written_and_an_image_generated_before_the_death_survive_it(
        client: TestClient, model: ModelSeam, garner: Garner, workspace_id: str, _agent_root: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The site pins QuoteBand at an older digest. A rewrites QuoteBand (a new digest) and generates
    an image, places the image, and dies. B validates and saves: the image is one of the turn's own
    (validation passes) and the saved site pins the NEW QuoteBand, not the pinned old one."""
    import lumen_api.site_turn_ports as ports

    old_js, old_source, old_css = quote_module(uuid4().hex)
    old_digest = record_section(client, workspace_id, "QuoteBand", old_js, old_source, old_css).references["digest"]
    new_js, new_source, new_css = quote_module(uuid4().hex)
    # The section toolchain's TypeScript/Tailwind half is replaced by its known output; the governed
    # record (the hardened page reading the schema) stays real.
    monkeypatch.setattr(ports, "compile_section_source", lambda **kwargs: {"ok": True, "moduleJs": new_js})
    monkeypatch.setattr(ports, "compile_tailwind_css", lambda *args, **kwargs: new_css)
    fake_image_provider(monkeypatch)

    store = HybridRepository()
    document_id = f"site_fence_{uuid4().hex[:10]}"
    site = garner.site(document_id)
    quote = {"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": "Fewer surprises for SCSD."}}
    site["pages"]["/"]["content"].insert(0, quote)
    site["agent_sections"] = {"QuoteBand": old_digest}
    born = store_site(site)["scene"]
    envelope = envelope_for(document_id, store.workspace_id, "Rework the quote band and give the review a photo.")
    open_run(store, envelope, claim=False)
    generation_a = hold_run(store, envelope, "worker-a")
    after_image = next(item["props"]["image"] for item in born["pages"]["/analysis"]["content"]
                       if item["props"]["id"] == "after")
    holder: dict = {}

    def steps():
        yield AIMessage(content="", tool_calls=[
            call("write_section", {"name": "QuoteBand", "code": new_source}, 1),
            call("generate_image", {"prompt": "An HR team at work", "aspect_ratio": "4:3"}, 2),
        ])
        holder["file"] = generated_file(holder["a"], "call_2")
        yield AIMessage(content="", tool_calls=[call("edit_file", {
            "file_path": "/pages/analysis.json", "old_string": json.dumps(after_image),
            "new_string": json.dumps(holder["file"])}, 3)])
        yield AIMessage(content="never reached")

    holder["a"] = a = Script(messages=steps(), hooks={2: die})
    model.scripts.append(a)
    dies(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    assert a.text_of("call_1").startswith("WRITTEN"), a.text_of("call_1")
    new_digest = store.get_site_turn_workspace(envelope.run_id)["turn_state"]["sections"]["QuoteBand"]["digest"]
    assert new_digest != old_digest

    another_disk(_agent_root, store, document_id)
    generation_b = take_over(store, envelope, "worker-b")
    b = model.next(AIMessage(content="", tool_calls=[call("validate_page", {}, 14)]),
                   AIMessage(content="The quote band is reworked and the review has its photo."))
    turn = durable_attempt(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    assert b.text_of("call_14") == "VALID.", b.text_of("call_14")
    assert turn.status == "succeeded" and turn.response["saved_version"] == 1, turn.response
    stored = store.require_document(document_id)["scene"]
    assert stored["agent_sections"] == {"QuoteBand": new_digest}
    after = next(item for item in stored["pages"]["/analysis"]["content"] if item["props"]["id"] == "after")
    assert after["props"]["image"] == holder["file"]


def test_j_f_a_failed_turn_leaves_no_copy_and_no_checkpoints(
        client: TestClient, model: ModelSeam, garner: Garner) -> None:
    """A turn that ends failed (here: stopped) is terminal like a saved one: its working copy and
    its conversation checkpoints are gone with its terminal write."""
    store, document_id, born, envelope = fresh_site_run(garner)
    generation = hold_run(store, envelope, "worker-a")
    model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/", "proof", PROOF_A, 1)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 2)]),
        AIMessage(content="never reached"),
        hooks={2: lambda: store.request_run_cancellation(envelope.run_id)},
    )
    turn = durable_attempt(client.app, store, envelope, worker_id="worker-a", generation=generation)
    assert turn.status == "failed" and turn.response["stop_reason"] == "cancelled_by_request"
    assert store.get_site_turn_workspace(envelope.run_id) is not None and checkpoint_rows(envelope.run_id) > 0
    finish(store, turn, generation)
    assert store.get_site_turn_workspace(envelope.run_id) is None and checkpoint_rows(envelope.run_id) == 0


def test_j_g_a_zombie_and_its_takeover_never_share_a_folder(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """On ONE disk (production workers share one bind mount): while A is stalled mid-turn, B takes
    the run over and finishes it. Each works in its own attempt folder, so neither sees the other's
    edits; B's work reaches the session folder, and A, fenced at its save, leaves it alone."""
    import threading

    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    folder = session_folder(_agent_root, store.workspace_id, document_id)
    seen: dict = {}

    def b_takes_over_and_finishes() -> None:
        generation_b = take_over(store, envelope, "worker-b")
        seen["a_folder_mid_turn"] = (folder / "attempts" / f"{envelope.run_id}-g{generation_a}" / "workspace" / "page.json").read_text()
        model.next(*proof_edit(born, PROOF_B, 11))
        worker = threading.Thread(target=lambda: seen.__setitem__("b", attempt_turn(
            client.app, store, envelope, worker_id="worker-b", generation=generation_b)))
        worker.start()
        worker.join()
        seen["generation_b"] = generation_b

    model.next(
        AIMessage(content="", tool_calls=[edit_heading_call(born, "/", "proof", PROOF_A, 1)]),
        AIMessage(content="", tool_calls=[call("validate_page", {}, 2)]),
        AIMessage(content="A is done."),
        hooks={1: b_takes_over_and_finishes},
    )
    a = attempt_turn(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    b = seen["b"]
    assert PROOF_A in seen["a_folder_mid_turn"] and PROOF_B not in seen["a_folder_mid_turn"]
    assert b.status == "succeeded" and b.response["saved_version"] == 1, b.response
    assert a.status == "fenced"
    assert store.require_document(document_id)["scene"] == with_heading(born, "/", "proof", PROOF_B)
    # The session folder holds B's request and none of A's edits; both attempt folders are gone.
    assert PROOF_B in (folder / "workspace" / "page.json").read_text()
    assert PROOF_A not in (folder / "workspace" / "page.json").read_text()
    assert "## 1. " in (folder / "workspace" / "history.md").read_text()
    assert list((folder / "attempts").iterdir()) == []


def die_right_after_the_save(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """The next attempt's save lands, then its worker dies (before history, the session copy and
    the terminal write). Returns the call that puts the real save back."""
    from lumen_api.toolbelt.wiring import DesignToolInvocations

    real_invoke = DesignToolInvocations.invoke

    def save_then_die(self, name, body, **kwargs):
        written = real_invoke(self, name, body, **kwargs)
        if name == "design_write_site":
            die()
        return written

    monkeypatch.setattr(DesignToolInvocations, "invoke", save_then_die)
    return lambda: monkeypatch.setattr(DesignToolInvocations, "invoke", real_invoke)


def history_entry(history: str, number: int) -> str:
    """One request's entry in history.md, from its heading to the next one."""
    start = history.index(f"\n## {number}. ")
    end = history.find("\n## ", start + 1)
    return history[start:] if end == -1 else history[start:end]


def test_j_h_saves_then_dies_and_the_takeover_reports_the_request_saved(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A's save lands as version 1, then A's worker dies before its terminal write. B, on another
    disk, resumes at A's final step (no model call) with exactly the site A saved. The request IS
    saved, as version 1, so B reports it that way: applied, saved_version 1, the saved event the
    chat turns into its checkpoint frame, and a history entry saying "as version 1" with the pages
    A changed (between the version before A's save and A's version). Still one version."""
    put_back = die_right_after_the_save(monkeypatch)
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    model.next(*proof_edit(born, PROOF_A, 1))
    dies(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    assert store.require_document(document_id)["current_version"] == 1
    put_back()

    another_disk(_agent_root, store, document_id)
    generation_b = take_over(store, envelope, "worker-b")
    b = model.next()
    turn = durable_attempt(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    assert b.seen == [], "the takeover asked the model again for finished work"
    assert turn.status == "succeeded", turn.response
    assert turn.response["status"] == "applied" and turn.response["outcome"] == "saved", turn.response
    assert turn.response["saved_version"] == 1 and turn.response["current_version"] == 1
    assert turn.response["summary"] == f"The proof heading now reads {PROOF_A!r}."
    assert saves(turn) == [("site_document_saved", {"document_id": document_id, "version": 1})]
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1 and stored["scene"] == with_heading(born, "/", "proof", PROOF_A)
    assert len(store.list_envelopes(document_id)) == 1
    entry = history_entry(history_of(_agent_root, store, document_id), 1)
    assert "- What changed: /: changed proof (heading)\n" in entry, entry
    assert "- Saved: as version 1\n" in entry, entry
    assert turn.response.get("session_manifest_sha256")

    finish(store, turn, generation_b)
    assert store.require_run(envelope.run_id)["status"] == "succeeded"


def test_j_i_saves_then_dies_and_a_takeover_that_ends_differently_still_reports_the_save(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A saves version 1 and dies. B has no conversation to continue (no checkpointer), redoes the
    request and ends with a DIFFERENT site; its save is refused because the run already saved.
    The request is still saved as version 1, and B reports exactly that, as in J h."""
    put_back = die_right_after_the_save(monkeypatch)
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    model.next(*proof_edit(born, PROOF_A, 1))
    dies(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    put_back()

    another_disk(_agent_root, store, document_id)
    generation_b = take_over(store, envelope, "worker-b")
    model.next(*proof_edit(with_heading(born, "/", "proof", PROOF_A), PROOF_B, 11))
    turn = attempt_turn(client.app, store, envelope, worker_id="worker-b", generation=generation_b)
    assert turn.status == "succeeded", turn.response
    assert turn.response["outcome"] == "saved" and turn.response["saved_version"] == 1, turn.response
    assert turn.response["current_version"] == 1
    assert saves(turn) == [("site_document_saved", {"document_id": document_id, "version": 1})]
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1 and stored["scene"] == with_heading(born, "/", "proof", PROOF_A)
    assert len(store.list_envelopes(document_id)) == 1
    entry = history_entry(history_of(_agent_root, store, document_id), 1)
    assert "- What changed: /: changed proof (heading)\n" in entry, entry
    assert "- Saved: as version 1\n" in entry, entry

    finish(store, turn, generation_b)
    assert store.require_run(envelope.run_id)["status"] == "succeeded"


# =================================================================================================
# K. Session files: one versioned copy per site (site-turn durability, K4-5, Task 5, 2026-10-16).
#
# A site's plan.md, history.md and fetched/ are one copy, named by the ``design_site_session``
# pointer. Two workers' disks are modelled by parking a worker's session folder outside the shared
# path while the other worker's folder (or none) takes its place.
# =================================================================================================

PLAN_ONE = "Request one: make the closing call to action free."
PLAN_TWO = "Request two, on worker B: lead with the study."


def disk_path(agent_root: Path, name: str) -> Path:
    return agent_root.parent / "disks" / name


def park_disk(agent_root: Path, store: HybridRepository, document_id: str, name: str) -> None:
    """The worker ``name`` steps away with its local session folder; the shared path is empty."""
    folder, parked = session_folder(agent_root, store.workspace_id, document_id), disk_path(agent_root, name)
    shutil.rmtree(parked, ignore_errors=True)
    parked.parent.mkdir(parents=True, exist_ok=True)
    if folder.exists():
        shutil.move(str(folder), str(parked))


def mount_disk(agent_root: Path, store: HybridRepository, document_id: str, name: str) -> None:
    """The worker ``name`` runs the next request, on the local session folder it kept."""
    folder, parked = session_folder(agent_root, store.workspace_id, document_id), disk_path(agent_root, name)
    shutil.rmtree(folder, ignore_errors=True)
    folder.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(parked), str(folder))


def headings(history: str) -> list[str]:
    """The request headings of a history.md, as a file or as read_file showed it (numbered lines)."""
    import re

    lines = (re.sub(r"^\s*\d+\t", "", line) for line in history.splitlines())
    return [line for line in lines if line.startswith("## ")]


class LogRecorder:
    """Records every event the executor logs (and still logs it)."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.events = inner, []

    def __getattr__(self, level: str) -> Callable[..., Any]:
        method = getattr(self.inner, level)

        def record(event: str, *args: Any, **kwargs: Any) -> Any:
            self.events.append((level, event, kwargs))
            return method(event, *args, **kwargs)

        return record

    def named(self, event: str) -> list[tuple]:
        return [entry for entry in self.events if entry[1] == event]


@pytest.fixture()
def logged(monkeypatch: pytest.MonkeyPatch) -> LogRecorder:
    from lumen_api import main as api_main

    recorder = LogRecorder(api_main.api_logger)
    monkeypatch.setattr(api_main, "api_logger", recorder)
    return recorder


def plan_request(text_: str, n: int = 1) -> list[AIMessage]:
    return [AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/plan.md", "content": f"# Plan\n\n- {text_}\n"}, n)]),
            AIMessage(content="Planned.")]


def replan_request(old: str, new: str) -> list[AIMessage]:
    return [AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/plan.md"}, 1)]),
            AIMessage(content="", tool_calls=[call("edit_file", {"file_path": "/plan.md", "old_string": old, "new_string": new}, 2)]),
            AIMessage(content="Replanned.")]


def test_k_a_a_stale_disk_reloads_the_newer_session_copy_and_overwrites_nothing(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """The K4-5 sequence. Worker A runs request 1; worker B, on another disk, runs request 2; worker
    A runs request 3 on its own, now stale, folder. Request 3 must see request 2's plan and history
    (its folder is rebuilt from the site's current copy, not only when it is missing), and its save
    must keep request 2's work: the history numbers 1, 2, 3 and the pointer moves 1 → 2 → 3."""
    store = HybridRepository()
    document_id = f"site_sess_{uuid4().hex[:10]}"
    store_site(garner.site(document_id))

    model.next(*plan_request(PLAN_ONE))
    first = run_turn(client.app, store, document_id, "Request one.")
    assert store.get_site_session(document_id) == {"version": 1, "manifest_sha256": first.response["session_manifest_sha256"]}
    park_disk(_agent_root, store, document_id, "worker-a")

    model.next(*replan_request(PLAN_ONE, PLAN_TWO))  # worker B: a disk that never ran this session
    second = run_turn(client.app, store, document_id, "Request two.")
    assert second.status == "succeeded", second.response
    assert store.get_site_session(document_id)["version"] == 2
    park_disk(_agent_root, store, document_id, "worker-b")

    mount_disk(_agent_root, store, document_id, "worker-a")  # A's folder still holds request 1's memory
    script = model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/plan.md"}, 1),
                                          call("read_file", {"file_path": "/history.md"}, 2)]),
        AIMessage(content="Nothing to change."),
    )
    third = run_turn(client.app, store, document_id, "Request three.")
    assert PLAN_TWO in script.text_of("call_1") and PLAN_ONE not in script.text_of("call_1")
    assert headings(script.text_of("call_2")) == ["## 1. Request one.", "## 2. Request two."]

    folder = session_folder(_agent_root, store.workspace_id, document_id)
    assert headings((folder / "workspace" / "history.md").read_text()) == [
        "## 1. Request one.", "## 2. Request two.", "## 3. Request three."]
    assert PLAN_TWO in (folder / "workspace" / "plan.md").read_text()
    assert store.get_site_session(document_id) == {"version": 3, "manifest_sha256": third.response["session_manifest_sha256"]}
    assert PLAN_TWO in manifest_text(client, third, "workspace/plan.md")
    assert headings(manifest_text(client, third, "workspace/history.md")) == [
        "## 1. Request one.", "## 2. Request two.", "## 3. Request three."]


def newer_copy_elsewhere(client: TestClient, base: Turn, entry: str) -> str:
    """Another worker's newer session copy: ``base``'s copy with one more history entry. Returns
    its manifest digest (stored the way a turn stores one)."""
    blobs = make_blob_store(client.app)
    history = (manifest_text(client, base, "workspace/history.md") + f"\n## 2. {entry}\n").encode()
    blobs.register(history, media_type="text/markdown", source_key="design-session/workspace/history.md")
    manifest = copy.deepcopy(manifest_of(client, base))
    manifest["files"]["workspace/history.md"] = {"sha256": hashlib.sha256(history).hexdigest(), "size": len(history),
                                                 "media_type": "text/markdown"}
    data = json.dumps(manifest, sort_keys=True).encode()
    blobs.register(data, media_type="application/json", source_key="design-session/manifest")
    return hashlib.sha256(data).hexdigest()


def test_k_b_a_concurrent_stale_save_is_refused_and_the_newer_copy_stands(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path, logged: LogRecorder) -> None:
    """While request 2 runs, another worker saves a newer copy of the site's session (the pointer
    moves 1 → 2). Request 2 started from version 1, so its save is refused: nothing is overwritten,
    a warning is logged, its run names no manifest, and its local folder is not the site's copy. The
    next request on that disk loads the newer copy."""
    store = HybridRepository()
    document_id = f"site_sess_{uuid4().hex[:10]}"
    store_site(garner.site(document_id))
    model.next(*plan_request(PLAN_ONE))
    first = run_turn(client.app, store, document_id, "Request one.")
    newer = newer_copy_elsewhere(client, first, "Saved by another worker.")
    moved: list = []
    model.next(AIMessage(content="Nothing to change."),
               hooks={0: lambda: moved.append(store.save_site_session(document_id, expected_version=1,
                                                                         manifest_sha256=newer))})
    second = run_turn(client.app, store, document_id, "Request two.")
    assert moved == [2]
    assert second.status == "succeeded" and "session_manifest_sha256" not in second.response
    assert "session_manifest_sha256" not in second.row["result"]
    assert store.get_site_session(document_id) == {"version": 2, "manifest_sha256": newer}
    (refusal,) = logged.named("design_session.stale_copy_not_saved")
    assert refusal[0] == "warning" and refusal[2]["started_from_version"] == 1

    script = model.next(AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/history.md"}, 1)]),
                        AIMessage(content="Nothing to change."))
    third = run_turn(client.app, store, document_id, "Request three.")
    assert headings(script.text_of("call_1")) == ["## 1. Request one.", "## 2. Saved by another worker."]
    assert store.get_site_session(document_id)["version"] == 3
    assert headings(manifest_text(client, third, "workspace/history.md")) == [
        "## 1. Request one.", "## 2. Saved by another worker.", "## 3. Request three."]


def test_k_c_a_zombie_attempt_appends_no_history_and_moves_no_pointer(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """Controller ruling S1. Attempt A is taken over mid-turn (B holds the lease and the run at
    generation 2) and ends without a save (it changed nothing), so no save fence stops it. It no
    longer holds the run, so it must not touch the session's memory: no history entry, no local
    copy, no pointer, and it ends ``fenced`` (no terminal result). B then runs the request and its
    history numbers it 1."""
    store, document_id, born, envelope = fresh_site_run(garner)
    generation_a = hold_run(store, envelope, "worker-a")
    generations: list = []
    model.next(
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/history.md"}, 1)]),
        AIMessage(content="Nothing to change."),
        hooks={1: lambda: generations.append(take_over(store, envelope, "worker-b"))},
    )
    a = attempt_turn(client.app, store, envelope, worker_id="worker-a", generation=generation_a)
    folder = session_folder(_agent_root, store.workspace_id, document_id)
    assert a.status == "fenced" and a.response["error"]["code"] == "site_turn.fenced", a.response
    assert "session_manifest_sha256" not in a.response
    assert not (folder / "workspace" / "history.md").exists()
    assert store.get_site_session(document_id) is None
    assert run_columns(envelope.run_id)["lease_generation"] == generations[0]

    model.next(*proof_edit(born, PROOF_B, 11))
    b = attempt_turn(client.app, store, envelope, worker_id="worker-b", generation=generations[0])
    assert b.status == "succeeded" and b.response["saved_version"] == 1, b.response
    assert headings((folder / "workspace" / "history.md").read_text()) == [f"## 1. {REQUEST_1}"]
    assert store.get_site_session(document_id) == {"version": 1, "manifest_sha256": b.response["session_manifest_sha256"]}


def test_k_d_a_site_with_no_pointer_falls_back_to_the_newest_run_and_creates_the_pointer(
        client: TestClient, model: ModelSeam, garner: Garner, _agent_root: Path) -> None:
    """Founder point e. A site from before the pointer table has its memory only on its newest run
    row. A fresh worker restores from that run, and the request's save creates the pointer at
    version 1; old data is never migrated."""
    from sqlalchemy import text

    store = HybridRepository()
    document_id = f"site_sess_{uuid4().hex[:10]}"
    store_site(garner.site(document_id))
    model.next(*plan_request(PLAN_ONE))
    first = run_turn(client.app, store, document_id, "Request one.")
    # The site as it was before the table: no pointer, the memory named only by the run row.
    store._bridge._run(lambda conn: conn.execute(
        text("DELETE FROM design_site_session WHERE workspace_id = :w AND document_id = :d"),
        {"w": store.workspace_id, "d": document_id}))
    assert store.get_site_session(document_id) is None
    assert first.row["result"]["session_manifest_sha256"]
    shutil.rmtree(session_folder(_agent_root, store.workspace_id, document_id))  # a fresh worker

    script = model.next(AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/plan.md"}, 1),
                                                          call("read_file", {"file_path": "/history.md"}, 2)]),
                        AIMessage(content="Nothing to change."))
    second = run_turn(client.app, store, document_id, "Request two.")
    assert PLAN_ONE in script.text_of("call_1")
    assert headings(script.text_of("call_2")) == ["## 1. Request one."]
    assert store.get_site_session(document_id) == {"version": 1, "manifest_sha256": second.response["session_manifest_sha256"]}
    assert headings(manifest_text(client, second, "workspace/history.md")) == ["## 1. Request one.", "## 2. Request two."]
