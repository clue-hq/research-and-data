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
    # fetch_page saves a page, before the agent's second step.
    folder = session_folder(agent_root, store.workspace_id, document_id) / "workspace" / "fetched"
    script.hooks[1] = lambda: (folder.mkdir(parents=True, exist_ok=True),
                               (folder / "garner-aon-study.md").write_text("Source: https://garnerhealth.com/aon\n\n7.4% lower spend.\n"))
    turn = run_turn(client.app, store, document_id, REQUEST_1)
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
    assert "| brand | Brand | surface.brand | #047464 |" in (workspace / "brand" / "brand.md").read_text()

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
    on, and its save must lose to the version it never saw. Its terminal write is then fenced."""
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
    # The zombie's save lost: conflicted, nothing announced; the takeover's version stands alone.
    assert turn.status == "failed" and turn.response["error"]["code"] == "site_turn.version_conflict"
    assert saves(turn) == []
    stored = store.require_document(document_id)
    assert stored["current_version"] == 1 and stored["scene"] == human
    assert len(store.list_envelopes(document_id)) == 1
    # Its terminal write is refused: the row belongs to generation 2 now.
    with pytest.raises(DesignRunFencedError):
        complete_turn(store, turn)
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
