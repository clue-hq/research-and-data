"""The site executor (Lane B Task 12, Contract 7): persist under CAS, announce, remember."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from py_lumen_config import settings

from lumen_agent.site.harness import CANCELLED_SUMMARY, SiteTurnResult
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


@pytest.fixture(autouse=True)
def _agent_workspace_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "agent-workspace"
    monkeypatch.setattr(settings, "lumen_agent_trace_dir", None)
    monkeypatch.setattr(settings, "lumen_agent_workspace_root", root)
    return root


@pytest.fixture(autouse=True)
def _site_kit_built() -> None:
    # The persist runs Lane A's real write validation (the site-kit validator bundle).
    from site_kit_support import ensure_site_kit_dist

    ensure_site_kit_dist()


#: A site site-kit's validator passes with an empty brand (no clones, no images), so A2's write
#: validation accepts it: a shell, and one CtaBand whose button goes to the shell's destination.
SHELL = {"header": {"id": "header", "preparedFor": "Acme", "ctaLabel": "Book a demo",
                    "ctaHref": "https://seller.example/demo"},
         "footer": {"id": "footer", "legal": "© Seller"}}


def _site(doc_id: str, heading: str = "Hello") -> dict:
    return {"id": doc_id, "title": "S", "theme": {}, "shell": SHELL, "agent_sections": {},
            "pages": {"/": {"root": {"props": {"title": "S"}}, "content": [{"type": "CtaBand", "props": {
                "id": "c", "surface": "brand", "heading": heading, "buttonLabel": "Book a demo",
                "buttonHref": "https://seller.example/demo"}}]}}}


def _host(app, runner):
    from lumen_api.fleet_handler import DesignTurnHost

    return DesignTurnHost(site_turn_runner=runner, core=app.state.core, storage=app.state.storage,
                          engine_cache_root=app.state.engine_cache_root)


def _envelope(document_id: str, workspace_id: str, *, prompt: str = "Make the hero warmer.",
              bundle: dict | None = None, targets: list | None = None):
    from clue_design.envelopes import DesignTurnEnvelope

    run_id = f"run_{uuid4().hex[:12]}"
    request = {"prompt": prompt, "base_version": 0, **({"targets": targets} if targets else {})}
    return DesignTurnEnvelope(kind="site_turn", work_id=uuid4(), workspace_id=workspace_id, run_id=run_id,
                              checkpoint_thread_id=run_id, document_id=document_id,
                              config={"request": request,
                                      "delegation_bundle": bundle or {"brief": "B"}, "leg": {"leg_id": "leg-1"}})


def _simulate_model_call(callbacks) -> None:
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    collector = callbacks.handlers[0]
    run = uuid4()
    collector.on_chat_model_start({}, [[]], run_id=run, invocation_params={"model": "openai:test/model"})
    collector.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="ok"))]]), run_id=run)


def _run(app, store, document, runner, events, **envelope_kwargs):
    """One site turn through the REAL executor, RECORDED on a run row the way the fleet worker
    records it (create → execute → complete). The recording is load-bearing for session memory:
    the next request restores the folder from the newest succeeded run's stamped manifest."""

    from lumen_api.main import execute_site_turn_job

    envelope = _envelope(document["id"], store.workspace_id, **envelope_kwargs)
    store.create_run(envelope.run_id, document["id"], kind="site_turn", payload={})
    outcome = execute_site_turn_job(envelope, store=store, host=_host(app, runner),
                                    event_sink=lambda event_type, data: events.append((event_type, data)))
    store.complete_run(envelope.run_id, *outcome)
    return outcome, envelope


def _workspace(agent_root: Path, store, document_id: str) -> Path:
    from clue_design.sessions import design_session_id

    return agent_root / "sessions" / design_session_id(store.workspace_id, document_id) / "workspace"


def test_an_applied_site_turn_saves_one_version_and_announces_it(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")
    seen: dict = {}

    def runner(prompt, *, document, workspace, run_id, callbacks):
        seen["prompt"] = prompt
        _simulate_model_call(callbacks)
        return SiteTurnResult("applied", "Warmed the hero.", _site(document["id"], "Warm hello"), None, [], [])

    events: list = []
    (status, response, event_type, _), _ = _run(app, store, document, runner, events)
    assert status == "succeeded" and event_type == "result"
    assert response["status"] == "applied" and response["doc_kind"] == "site"
    assert response["current_version"] == 1 and response["saved_version"] == 1
    assert len(response["model_calls"]) == 1 and response["session_manifest_sha256"]
    assert seen["prompt"] == "Make the hero warmer."  # the brief is brief.md, not a prompt block
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1 and stored["scene"]["pages"]["/"]["content"][0]["props"]["heading"] == "Warm hello"
    assert events == [("site_document_saved", {"document_id": document["id"], "version": 1})]
    assert all("operations" not in data for _, data in events)
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "## 1. Make the hero warmer.\n" in history and "- Saved: as version 1\n" in history


def test_a_site_turn_that_loses_the_version_race_saves_nothing(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    """Review focus 1: a human saved while the request ran; the human's version stands."""

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        human = _site(document["id"], "Human edit")
        store.update_site_document(document["id"], human, intent="manual", checkpoint_label=None,
                                   operations=[{"kind": "replace_site", "site": human}],
                                   inverse_operations=[{"kind": "replace_site", "site": document["scene"]}],
                                   actor_kind="human", source="editor")
        return SiteTurnResult("applied", "Warmed the hero.", _site(document["id"], "Agent edit"), None, [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "failed" and response["status"] == "conflicted"
    assert response["error"]["code"] == "site_turn.version_conflict" and response["saved_version"] is None
    assert store.require_document(document["id"])["scene"]["pages"]["/"]["content"][0]["props"]["heading"] == "Human edit"
    assert events == []
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "- Saved: no, the site changed while this request ran\n" in history


def test_a_cancelled_site_turn_saves_nothing_and_says_so(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    """Review focus 4."""

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        return SiteTurnResult("failed", CANCELLED_SUMMARY, document["scene"], "cancelled_by_request", [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "failed" and response["summary"] == CANCELLED_SUMMARY
    assert response["stop_reason"] == "cancelled_by_request" and response["error"]["code"] == "site_turn.cancelled_by_request"
    assert store.require_document(document["id"])["current_version"] == 0 and events == []
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "- Saved: no, it was stopped\n" in history


def test_an_unchanged_site_writes_no_version(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        return SiteTurnResult("applied", "Nothing needed changing.", document["scene"], None, [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "succeeded" and response["outcome"] == "unchanged" and response["saved_version"] is None
    assert store.require_document(document["id"])["current_version"] == 0 and events == []


def test_the_session_snapshot_keeps_memory_and_leaves_out_regenerated_inputs(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    """Review focus 5: a fresh worker gets plan.md, history.md and fetched/ back — never stale
    research, catalog or page files."""

    import shutil

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def first(prompt, *, document, workspace, run_id, callbacks):
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "plan.md").write_text("the plan")
        (workspace / "fetched").mkdir(exist_ok=True)
        (workspace / "fetched" / "story.md").write_text("evidence")
        (workspace / "research").mkdir(exist_ok=True)
        (workspace / "research" / "overview.md").write_text("research as of request 1")
        (workspace / "page.json").write_text("{}")
        (workspace / "work").mkdir(exist_ok=True)
        (workspace / "work" / "offload.md").write_text("compaction offload")
        return SiteTurnResult("applied", "Planned.", _site(document["id"], "One"), None, [], [])

    (status, response, _, _), _ = _run(app, store, document, first, [])
    assert status == "succeeded"
    manifest = json.loads(_blobs(app).read(response["session_manifest_sha256"]))
    assert {"workspace/plan.md", "workspace/history.md", "workspace/fetched/story.md"} <= set(manifest["files"])
    assert not any(key.startswith(("workspace/research/", "workspace/work/")) or key == "workspace/page.json"
                   for key in manifest["files"])

    shutil.rmtree(_workspace(_agent_workspace_in_tmp, store, document["id"]).parent)  # a fresh worker
    restored: dict = {}

    def second(prompt, *, document, workspace, run_id, callbacks):
        restored["plan"] = (workspace / "plan.md").read_text()
        restored["research"] = (workspace / "research" / "overview.md").exists()
        return SiteTurnResult("applied", "Done.", document["scene"], None, [], [])

    _run(app, store, store.require_document(document["id"]), second, [])
    assert restored == {"plan": "the plan", "research": False}


def _blobs(app):
    from conftest import make_blob_store

    return make_blob_store(app)


def test_a_site_the_write_refuses_saves_nothing_and_says_why(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        broken = _site(document["id"], "Warm hello")
        broken["pages"]["/"]["content"][0]["props"]["surface"] = "green"
        return SiteTurnResult("applied", "Warmed the hero.", broken, None, [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "failed" and response["status"] == "failed"
    assert response["summary"].startswith("The website could not be saved: ") and "surface" in response["summary"]
    assert store.require_document(document["id"])["current_version"] == 0 and events == []
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "- Saved: no, the save was refused\n" in history


def test_a_non_site_document_is_refused(tmp_path, design_storage) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    web = store.create_document({"id": f"doc_web_{uuid4().hex[:8]}", "title": "W", "theme": {}, "pages": [], "assets": {}},
                                doc_kind="web")
    (status, response, _, _), _ = _run(app, store, web, lambda *a, **k: pytest.fail("must not run"), [])
    assert status == "failed" and response["diagnostics"][0]["code"] == "site_turn.not_a_site"


def test_the_prompt_carries_the_drift_note_and_the_assignment_never_the_brief(tmp_path, design_storage) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")
    seen: dict = {}

    def runner(prompt, *, document, workspace, run_id, callbacks):
        seen["prompt"] = prompt
        return SiteTurnResult("applied", "ok", document["scene"], None, [], [])

    bundle = {"brief": "THE STANDING BRIEF", "artifact": {"position": 1, "count": 2, "title": "Morgan site", "note": ""}}
    _run(app, store, document, runner, [], prompt="Add a pricing page.", bundle=bundle)
    assert "CURRENT DOCUMENT ASSIGNMENT" in seen["prompt"] and seen["prompt"].endswith("Add a pricing page.")
    assert "THE STANDING BRIEF" not in seen["prompt"]


def test_a_save_the_validator_cannot_check_is_refused_and_still_remembered(
    tmp_path, design_storage, _agent_workspace_in_tmp, monkeypatch
) -> None:
    """Fix round 1 (a): a typed "cannot check now" error is a refused save, like Lane A's routes
    treat it — history and the session's memory are still written."""

    import lumen_api.site_doc_validate as site_doc_validate
    from lumen_api.site_kit_cli import SiteKitCliError

    def bundle_missing(*args, **kwargs):
        raise SiteKitCliError("site_kit.unavailable", "site-kit validator bundle missing")

    # The narrowest real seam: the validator's node bundle call, which the write's check turns into
    # SiteValidatorUnavailable.
    monkeypatch.setattr(site_doc_validate, "run_site_kit_bundle", bundle_missing)
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        return SiteTurnResult("applied", "Warmed the hero.", _site(document["id"], "Warm hello"), None, [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "failed" and response["status"] == "failed"
    assert response["summary"] == "The website could not be saved: site-kit validator bundle missing"
    assert store.require_document(document["id"])["current_version"] == 0 and events == []
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "- Saved: no, the save was refused\n" in history
    assert response["session_manifest_sha256"]


def test_the_announced_version_is_the_writes_own_not_a_later_human_save(
    tmp_path, design_storage, _agent_workspace_in_tmp, monkeypatch
) -> None:
    """Fix round 1 (b): a human save landing right after the agent's write must not be announced
    as the agent's version."""

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")
    original = HybridRepository.update_site_document

    def agent_write_then_a_human_save(self, document_id, site, **kwargs):
        written = original(self, document_id, site, **kwargs)
        if kwargs.get("actor_kind") == "agent":
            human = _site(document_id, "Human edit")
            original(self, document_id, human, intent="manual", checkpoint_label=None,
                     operations=[{"kind": "replace_site", "site": human}],
                     inverse_operations=[{"kind": "replace_site", "site": site}],
                     actor_kind="human", source="editor",
                     expected_base_version=int(written["current_version"]))
        return written

    monkeypatch.setattr(HybridRepository, "update_site_document", agent_write_then_a_human_save)

    def runner(prompt, *, document, workspace, run_id, callbacks):
        return SiteTurnResult("applied", "Warmed the hero.", _site(document["id"], "Warm hello"), None, [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "succeeded" and response["saved_version"] == 1 and response["current_version"] == 1
    assert events == [("site_document_saved", {"document_id": document["id"], "version": 1})]
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "- Saved: as version 1\n" in history
    assert store.require_document(document["id"])["current_version"] == 2


def test_the_selection_block_follows_the_persons_words(tmp_path, design_storage) -> None:
    from lumen_agent.site.workspace import targets_block

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")
    seen: dict = {}

    def runner(prompt, *, document, workspace, run_id, callbacks):
        seen["prompt"] = prompt
        return SiteTurnResult("applied", "ok", document["scene"], None, [], [])

    targets = [{"object_id": "site:/#c.heading", "note": "1. Shorter"}]
    _run(app, store, document, runner, [], prompt="Fix this.", targets=targets)
    assert seen["prompt"].endswith("Fix this.\n\n" + targets_block(targets))

    _run(app, store, document, runner, [], prompt="No selection.")
    assert seen["prompt"].endswith("No selection.")
