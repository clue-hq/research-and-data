"""genad Task 5 — a LEG scene turn persists its applied proposal under CAS.

The genweb ruling ("the executor owns the persist", `execute_web_turn_job`) extended to the
scene path. Until this landed, a chat-born ad turn returned a proposal nobody committed: the
editor's own route committed it when a human was watching, and a leg turn's proposal simply
evaporated, so the gallery never moved.

The rule is LEG-ONLY and gated at every step. A direct editor turn (`POST /agent/turns`,
`POST /agent/turn-preview`) carries no `leg` block, keeps proposing, and its result envelope
stays byte-identical — the editor still owns that commit through `/documents/{id}/operations`
(P3.7's layering rule).

These drive the REAL `execute_agent_turn_job` through the `app.state.agent_turn_runner` test
seam, exactly as `test_web_turns.py`'s leg section drives the web executor.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_blob_store, make_client

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"
GENERATED_RASTER_ASSET_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/assets/generated_raster_asset.json"
)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def create_document(client: TestClient) -> dict:
    response = client.post(
        "/documents", json={"title": "Hospital Letter", "scene": minimal_scene()}
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


def title_operation(title: str) -> dict:
    return {
        "kind": "update_document",
        "patch": {
            "title": {"kind": "set", "value": title},
            "artifact_type": {"kind": "unchanged"},
            "medium": {"kind": "unchanged"},
            "brand_kit": {"kind": "unchanged"},
        },
    }


def unreplayable_operation() -> dict:
    """An insert under a page that does not exist — the engine refuses it, so the executor
    must refuse to commit rather than trust the agent's own history."""
    return {
        "kind": "insert_node",
        "parent": {"kind": "page", "id": "missing_page"},
        "index": 0,
        "node": {
            "id": "node_orphan",
            "name": None,
            "kind": {"kind": "rect"},
            "transform": {
                "x": 0.0,
                "y": 0.0,
                "rotation": 0.0,
                "skew_x": 0.0,
                "skew_y": 0.0,
                "flip_x": False,
                "flip_y": False,
            },
            "size": {
                "width": {"kind": "fixed", "value": 10.0},
                "height": {"kind": "fixed", "value": 10.0},
            },
            "children": [],
            "fills": [],
            "strokes": [],
            "corner": {
                "top_left": 0.0,
                "top_right": 0.0,
                "bottom_right": 0.0,
                "bottom_left": 0.0,
            },
            "opacity": 1.0,
            "visible": True,
            "locked": False,
            "constraints": None,
            "layout": None,
            "text": None,
            "image": None,
            "effects": [],
            "slot_id": None,
            "metadata": {},
        },
    }


def _turn_host(client: TestClient, stub):
    """The embedded worker's turn host, built from `app.state` the way `create_app` does."""
    from lumen_api.fleet_handler import DesignTurnHost

    state = client.app.state
    return DesignTurnHost(
        agent_turn_runner=stub,
        core=state.core,
        storage=state.storage,
        engine_cache_root=state.engine_cache_root,
    )


def _scene_envelope(document_id: str, workspace_id: str, config: dict):
    from clue_design.envelopes import DesignTurnEnvelope

    run_id = f"run_{uuid4().hex[:12]}"
    return DesignTurnEnvelope(
        kind="agent_turn",
        work_id=uuid4(),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=document_id,
        config=config,
    )


def proposing_runner(operations: list, received: dict | None = None):
    """A stub trio: proposes `operations` and applies nothing itself."""

    def stub(payload, root):
        if received is not None:
            received["payload"] = payload
        return {
            "schema_version": 1,
            "status": "proposed",
            "summary": "Agent proposed a document title update.",
            "run_id": "run_stub_scene",
            "trace_dir": ".lumen-runs/run_stub_scene",
            "preview_paths": [],
            "dsl_blocks": ["# doc title"],
            "operations": operations,
            "diagnostics": [],
            "artifacts": [],
        }

    return stub


LEG_BRIEF = "Build the Harbor & Sage launch ad: bold headline, product shot, booking CTA."


def _assert_conflict_is_legible(response: dict, *, moved_from: int, moved_to: int) -> None:
    """A conflict a human can act on: both versions named, and the reassurance that their own
    edit survived.

    Asserted on BOTH prose slots, because the two candidate reader keys differ: `summary` is
    the design editor's run-panel key, `stop_reason` the platform scene summarizer's
    (`_assistant_summary`, design_leg_wiring). NEITHER renders a conflict today — the builder
    is leg-only and a conflicted turn is a `failed` run that `_fail_turn` short-circuits with
    no assistant message — so this pins the durable result payload, ready for whichever surface
    the genad founder item on conflict routing hands it to. `failed_agent_turn_response` leaves
    `stop_reason` None, so a conflict built naively from it is contentless by construction.
    """

    for field in ("summary", "stop_reason"):
        text = response[field]
        assert isinstance(text, str) and text.strip(), f"{field} is empty"
        assert f"version {moved_from}" in text, f"{field} does not name the base version"
        assert f"version {moved_to}" in text, f"{field} does not name the current version"
        assert "preserved" in text, f"{field} does not say the human's edit survived"


def _leg_config(document: dict, base_version: int, prompt: str = "Go ahead.") -> dict:
    return {
        "request": {
            "prompt": prompt,
            "scene": document.get("scene") or minimal_scene(),
            "document_id": document["id"],
        },
        "delegation_bundle": {"brief": LEG_BRIEF},
        "history": [{"role": "user", "text": "Warmer."}],
        "leg": {"leg_id": "leg-1", "document_base_version": base_version},
    }


# --- (a) the happy path ------------------------------------------------------


def test_a_leg_scene_turn_commits_its_proposal_and_reports_the_new_version(
    client: TestClient,
) -> None:
    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    assert document["current_version"] == 0
    received: dict = {}

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")], received)),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert response["status"] == "proposed"
    # The document ADVANCED: one version, the op's effect in the stored scene.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1
    assert stored["scene"]["meta"]["title"] == "Agent Title"
    # ...and the result carries it, so the platform's projection can pin the new version.
    assert response["current_version"] == 1
    # The runtime still ran on the composed leg prompt (P3.7/G9 unchanged).
    assert LEG_BRIEF in received["payload"].prompt


def test_platform_leg_envelope_resolves_reference_ids_when_manifest_key_is_absent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Platform envelopes freeze ids in request; a missing by-value manifest is unresolved.

    Regression for the silent-inert bridge: ``dict.get`` previously turned a missing
    ``config.reference_assets`` into explicit ``None``, which told the runner this turn had no
    references and skipped the existing resolver completely.
    """

    import lumen_api.main as main

    document = create_document(client)
    store = HybridRepository()
    config = _leg_config(document, 0)
    config["request"]["reference_asset_ids"] = ["asset_reference_one"]
    received: dict[str, object] = {}

    def run_preview(payload, _root, **kwargs):
        received["ids"] = list(payload.reference_asset_ids)
        received["unresolved"] = (
            kwargs["resolved_reference_assets"] is main._REFERENCES_UNRESOLVED
        )
        return proposing_runner([title_operation("Referenced")])(payload, _root)

    monkeypatch.setattr(main, "run_agent_turn_preview", run_preview)
    status, response, _, _ = main.execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, config),
        store=store,
        host=_turn_host(client, None),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert received == {"ids": ["asset_reference_one"], "unresolved": True}


def test_a_leg_scene_turns_commit_is_labelled_with_the_users_message(
    client: TestClient,
) -> None:
    """The composed prompt is for the RUNTIME. The durable edit envelope's `intent` is a
    human-facing label, so it stays the user's own words — never the rendered brief block
    (the G9 rule, web twin at `test_web_turns.py`)."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            _leg_config(document, 0, prompt="Make the headline two lines."),
        ),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Two Lines")])),
        event_sink=None,
    )
    assert status == "succeeded", response

    envelopes = store.list_envelopes(document["id"])
    assert len(envelopes) == 1
    assert envelopes[0]["intent"] == "Make the headline two lines."


# --- (b) the CAS loss --------------------------------------------------------


def test_a_leg_scene_turn_on_a_moved_document_conflicts_before_the_runner(
    client: TestClient,
) -> None:
    """A human edit landed while the turn was queued. The turn comes back conflicted, the
    document is untouched, and the trio never ran at all."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    # The human edit: the document is now at version 1, the envelope still pins 0.
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Human Title")]},
    )
    assert applied.status_code == 200, applied.text

    store = HybridRepository()
    received: dict = {}

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")], received)),
        event_sink=None,
    )

    assert status == "failed"
    assert response["status"] == "conflicted"
    assert response["diagnostics"][0]["code"] == "agent_turn.version_conflict"
    assert response["base_version"] == 0
    assert response["current_version"] == 1
    # The platform's scene summarizer renders `stop_reason` into the chat thread and nothing
    # else, so a conflict that leaves it None reaches the marketer as a contentless "Design
    # turn conflicted." Both user-facing strings must name BOTH versions and say the edit
    # survived — the two facts a human needs to know what just happened.
    _assert_conflict_is_legible(response, moved_from=0, moved_to=1)
    # The human's edit survived, and the trio was never asked to spend a token.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1
    assert stored["scene"]["meta"]["title"] == "Human Title"
    assert received == {}


def test_a_leg_scene_turn_that_loses_the_race_mid_run_conflicts_at_the_write(
    client: TestClient,
) -> None:
    """The window the early check CANNOT close: the human edit lands WHILE the trio runs.

    Simulated deterministically by editing from inside the stub runner — which executes at
    exactly that point — so the governed write's `expected_base_version` is the only thing left
    standing between the agent and a clobber. It holds, and the loss is terminal-honest."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    def racing_stub(payload, root):
        edit = client.post(
            f"/documents/{document['id']}/operations",
            json={"operations": [title_operation("Human Title")]},
        )
        assert edit.status_code == 200, edit.text
        return proposing_runner([title_operation("Agent Title")])(payload, root)

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, racing_stub),
        event_sink=None,
    )

    assert status == "failed"
    assert response["status"] == "conflicted"
    assert (response["base_version"], response["current_version"]) == (0, 1)
    # The late (CAS-race) conflict is exactly as legible as the early one — same builder, so a
    # marketer cannot tell which of the two windows they lost, and does not need to.
    _assert_conflict_is_legible(response, moved_from=0, moved_to=1)
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1
    assert stored["scene"]["meta"]["title"] == "Human Title"


# --- (c) the non-leg layering guarantee --------------------------------------


def test_a_non_leg_scene_turn_persists_nothing_and_stays_byte_identical(
    client: TestClient,
) -> None:
    """P3.7's layering rule, proven by equality: a direct editor turn has no `leg` block, so
    its result envelope is EXACTLY the runner's — every new behaviour gates on that block."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    operations = [title_operation("Agent Title")]
    # The expected envelope is snapshotted from a DEEP COPY, before the run. The stub hands the
    # executor the very list object this test holds, so an expected envelope built from that
    # same list afterwards would AGREE with an in-place mutation instead of catching it — and
    # "byte-identical" is exactly the claim being made here.
    expected = proposing_runner(deepcopy(operations))(None, None)

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            {
                "request": {
                    "prompt": "Repair the headline",
                    "scene": minimal_scene(),
                    "document_id": document["id"],
                }
            },
        ),
        store=store,
        host=_turn_host(client, proposing_runner(operations)),
        event_sink=None,
    )

    assert (status, kind, marker) == ("succeeded", "result", {"status": "proposed"})
    # Byte-identical: the runner's own envelope, no `current_version` grafted on.
    assert response == expected
    assert "current_version" not in response
    # Nothing was committed — the editor still owns that commit.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["meta"]["title"] == "Hospital Letter"
    assert store.list_envelopes(document["id"]) == []


def test_a_leg_turn_without_a_pinned_document_persists_nothing(
    client: TestClient,
) -> None:
    """A legacy (AD4.R-era) leg pins no document, so its envelope carries no
    `document_base_version`. That reads as preview-only — never a fabricated version zero,
    which would clobber whatever sits at the head."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    config = _leg_config(document, 0)
    del config["leg"]["document_base_version"]

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, config),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")])),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert "current_version" not in response
    assert store.require_document(document["id"])["current_version"] == 0


# --- (d) the empty proposal --------------------------------------------------


def test_a_leg_scene_turn_with_no_operations_persists_nothing_and_still_succeeds(
    client: TestClient,
) -> None:
    """A pure clarification is a real, successful outcome with nothing to commit."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([])),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert response["status"] == "proposed"
    assert "current_version" not in response
    assert store.require_document(document["id"])["current_version"] == 0
    assert store.list_envelopes(document["id"]) == []


# --- (d2) the post-persist re-read ------------------------------------------


class _StoreThatBreaksAfterTheWrite(HybridRepository):
    """A store whose reads work until the governed write has already committed.

    The re-read that stamps `current_version` onto the result runs AFTER the durable write.
    Anything that fails there is reporting on a turn that already happened, so it must not be
    allowed to turn a committed turn into `agent_runtime.failed` — the marketer would be told
    nothing was saved while their ad sits changed in the gallery.
    """

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def require_document(self, document_id):  # type: ignore[override]
        self.reads += 1
        # 1 = the executor's early CAS check, 2 = the post-persist re-read.
        if self.reads >= 2:
            raise RuntimeError("transient read failure after the commit")
        return super().require_document(document_id)


def test_a_committed_leg_scene_turn_survives_a_failing_post_persist_re_read(
    client: TestClient,
) -> None:
    """The write landed; only the version lookup after it failed. The turn stays a success."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = _StoreThatBreaksAfterTheWrite()

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")])),
        event_sink=None,
    )

    # NOT `agent_runtime.failed`: the proposal is still the proposal it was.
    assert (status, kind) == ("succeeded", "result"), response
    assert response["status"] == "proposed"
    assert marker == {"status": "proposed"}
    assert response.get("diagnostics") == []
    # The version could not be read, so it is honestly absent rather than guessed at.
    assert "current_version" not in response
    # ...and the write really did land: the document advanced, once.
    verified = HybridRepository().require_document(document["id"])
    assert verified["current_version"] == 1
    assert verified["scene"]["meta"]["title"] == "Agent Title"
    assert store.reads == 2


# --- (e) the replay refusal --------------------------------------------------


def test_a_leg_scene_turn_whose_operations_do_not_replay_fails_honestly(
    client: TestClient,
) -> None:
    """The agent's operation history is a CLAIM until the engine reproduces it here. An op
    naming a node/page that does not exist is a refusal, not a write."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([unreplayable_operation()])),
        event_sink=None,
    )

    assert status == "failed"
    assert response["status"] == "failed"
    assert response["diagnostics"][0]["code"] == "agent_turn.operations_replay_failed"
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["meta"]["title"] == "Hospital Letter"
    assert store.list_envelopes(document["id"]) == []


# --- (f) genad walk F1: the empty-artboard steering block --------------------
#
# A chat-born ad document is BORN with one empty artboard page (the leg-open birth mints
# `new_scene` + one `add_page` at the resolved format). The author model's from-scratch habit
# is to open a turn with a top-level `page ...` block — which cannot work here: the page id
# already exists, so a page line that parses is refused by the engine (`page <id> already
# exists`) and one that does not parse leaves its indented elements parentless (LUMD0402).
# Five live runs thrashed the repair loop that way and died upstream. A LEG turn on an
# all-empty-paged scene therefore carries a deterministic document-state block naming the real
# page and quoting the `#page:<page_id>` fill form the engine genuinely accepts.

AD_PAGE_ID = "page_acbaa276202a57e4"


def empty_ad_scene(
    page_id: str = AD_PAGE_ID, width: float = 1200.0, height: float = 1200.0
) -> dict:
    """The newborn ad's scene: ONE artboard page at the ad format, zero children."""

    scene = minimal_scene()
    scene["pages"] = {
        page_id: {
            "id": page_id,
            "name": "Square",
            "size": {
                "width": width,
                "height": height,
                "unit": "pt",
                "preset": "custom",
                "orientation": "landscape" if width > height else "portrait",
                "source": {"width": width, "height": height, "unit": "px"},
                "output": {"raster": {"width_px": int(width), "height_px": int(height)}},
            },
            "children": [],
            "bleed": None,
            "safe_area": None,
            "background": [],
        }
    }
    scene["nodes"] = {}
    scene["slots"] = {}
    return scene


def _prompt_seen_by_the_runner(client: TestClient, config: dict) -> str:
    """Drive the REAL executor and return the prompt the trio was actually handed."""

    from lumen_api.main import execute_agent_turn_job

    store = HybridRepository()
    received: dict = {}
    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(config["request"]["document_id"], store.workspace_id, config),
        store=store,
        host=_turn_host(client, proposing_runner([], received)),
        event_sink=None,
    )
    assert status == "succeeded", response
    return received["payload"].prompt


def test_a_leg_turn_on_an_all_empty_scene_is_steered_to_fill_the_birth_page(
    client: TestClient,
) -> None:
    from lumen_api.main import execute_agent_turn_job  # noqa: F401  (import parity)

    document = create_document(client)
    config = _leg_config(document, 0, prompt="Go ahead.")
    config["request"]["scene"] = empty_ad_scene()

    prompt = _prompt_seen_by_the_runner(client, config)

    # The block is there, and it names the REAL page and the REAL dimensions — read off the
    # scene, never hardcoded (a wrong id would send the author at a page that does not exist).
    assert "DOCUMENT STATE" in prompt
    assert AD_PAGE_ID in prompt
    assert "1200×1200" in prompt
    # ...and it quotes the fill form the engine accepts, on the page that exists.
    assert f"#page:{AD_PAGE_ID}" in prompt
    # The leg's own context still rides the same prompt (P3.7/G9 unchanged).
    assert LEG_BRIEF in prompt
    assert "Go ahead." in prompt


def test_the_steering_block_reads_the_page_id_and_size_off_the_scene(
    client: TestClient,
) -> None:
    """A second document, a different id and format: the block moves with the scene."""

    document = create_document(client)
    config = _leg_config(document, 0)
    config["request"]["scene"] = empty_ad_scene("page_deadbeefdeadbeef", 1080.0, 1920.0)

    prompt = _prompt_seen_by_the_runner(client, config)

    assert "#page:page_deadbeefdeadbeef" in prompt
    assert "1080×1920" in prompt
    assert AD_PAGE_ID not in prompt
    assert "1200×1200" not in prompt


def test_a_leg_turn_on_a_content_bearing_scene_gets_no_steering_block(
    client: TestClient,
) -> None:
    """The pre-genad shape — every scene leg until now pinned a document with content. Its
    prompt must stay byte-identical to what P3.7 composes."""

    from clue_design.leg_context import render_leg_turn_prompt

    document = create_document(client)
    config = _leg_config(document, 0, prompt="Warmer, please.")
    # `minimal_scene()` has a page WITH a child.
    assert config["request"]["scene"]["pages"]["page_a4"]["children"]

    prompt = _prompt_seen_by_the_runner(client, config)

    assert prompt == render_leg_turn_prompt(
        bundle=config["delegation_bundle"],
        history=config["history"],
        prompt="Warmer, please.",
    )
    assert "DOCUMENT STATE" not in prompt


def test_a_leg_turn_on_a_scene_with_no_pages_gets_no_steering_block(
    client: TestClient,
) -> None:
    """A page-less scene is the genuine from-scratch case: `page ...` is the CORRECT move
    there, so the block must not appear and talk the author out of it."""

    from clue_design.leg_context import render_leg_turn_prompt

    document = create_document(client)
    config = _leg_config(document, 0)
    scene = empty_ad_scene()
    scene["pages"] = {}
    config["request"]["scene"] = scene

    prompt = _prompt_seen_by_the_runner(client, config)

    assert prompt == render_leg_turn_prompt(
        bundle=config["delegation_bundle"],
        history=config["history"],
        prompt="Go ahead.",
    )
    assert "DOCUMENT STATE" not in prompt


def test_a_direct_editor_turn_is_untouched_even_on_an_empty_scene(
    client: TestClient,
) -> None:
    """The MVP editor's direct-turn contract (P3.7 layering): no leg block, no composition —
    the prompt reaching the trio is the human's own words, byte for byte."""

    document = create_document(client)
    config = {
        "request": {
            "prompt": "Fill this page with a launch ad.",
            "scene": empty_ad_scene(),
            "document_id": document["id"],
        }
    }

    prompt = _prompt_seen_by_the_runner(client, config)

    assert prompt == "Fill this page with a launch ad."


def _quoted_dsl_example(prompt: str) -> str:
    """The DSL block the steering note quotes, dedented back to column 0."""

    lines = prompt.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("    #page:"))
    block: list[str] = []
    for line in lines[start:]:
        if not line.strip():
            break
        assert line.startswith("    "), line
        block.append(line[4:])
    return "\n".join(block) + "\n"


def test_the_dsl_the_steering_block_quotes_actually_compiles_against_the_empty_page(
    client: TestClient,
) -> None:
    """The whole point of the block is that its DSL is a form the ENGINE accepts. A wrong form
    here would make the defect worse, so the quoted example is compiled against the same
    newborn scene the note was built from: it must apply cleanly, attach its subtree to the
    EXISTING page, and leave the page's stored size untouched.

    (The bare `#page:<page_id>` form the engine's own LUMD0402 hint suggests does NOT do this —
    `is_modification_line` needs two tokens, so a lone `#…` line is a comment and its children
    are orphaned. That is why the quoted line restates the page's name.)
    """

    document = create_document(client)
    scene = empty_ad_scene()
    config = _leg_config(document, 0)
    config["request"]["scene"] = scene

    prompt = _prompt_seen_by_the_runner(client, config)
    source = _quoted_dsl_example(prompt)
    assert source.startswith(f'#page:{AD_PAGE_ID} name("Square")')

    result = client.app.state.core.compile_dsl_into_scene(scene, source)
    compile_output = result["dsl"]["compile_output"]
    assert compile_output["halted_at"] is None, compile_output["diagnostics"]
    assert [
        diagnostic
        for diagnostic in compile_output["diagnostics"]
        if diagnostic["diagnostic"]["severity"] == "error"
    ] == []
    assert result["dsl"]["operation_error"] is None
    compiled_page = result["scene"]["pages"][AD_PAGE_ID]
    assert compiled_page["children"] == ["ad_root"], "the subtree must attach to the EXISTING page"
    assert compiled_page["size"] == scene["pages"][AD_PAGE_ID]["size"], "the page must not move"


# --- (g) genad2 Task 3: the >=1-page success gate ----------------------------
#
# The zero-page birth (genad2 ruling 1) moved page authorship to the design agent:
# `open_design_leg@4` mints a scene document with NO pages at all, and the trio authors the page
# in a later turn at the size the user's own words imply. That makes "the turn produced nothing"
# newly indistinguishable from "the turn produced a design" at the persist seam — an empty or
# meta-only proposal on a page-less newborn used to come back a cheerful success while the
# gallery had nothing to open. A LEG turn whose APPLIED result still has zero pages is therefore
# refused honestly: no write, a typed `agent_turn.pageless_result` failure, the document exactly
# as it was.

PAGELESS_SUMMARY = (
    "Design finished without creating a page — nothing was saved; "
    "send another message to try again."
)


def create_pageless_document(client: TestClient) -> dict:
    """A document born the way `open_design_leg@4` births one: the engine's own `new_scene`,
    no page minted by anybody.

    Returned as the STORED row (not the creation DTO, which carries no scene) so `_leg_config`
    hands the turn the page-less scene the document really has.
    """

    response = client.post("/documents", json={"title": "Harbor & Sage Launch Ad"})
    assert response.status_code == 200, response.text
    document = HybridRepository().require_document(response.json()["document"]["id"])
    assert document["scene"]["pages"] == {}, "the birth scene must be page-less"
    assert document["current_version"] == 0
    return document


def add_page_operation(page_id: str = AD_PAGE_ID) -> dict:
    """The page the design agent is now the one to author."""

    return {"kind": "add_page", "page": empty_ad_scene(page_id)["pages"][page_id]}


def remove_page_operation(page_id: str) -> dict:
    """The other way a turn can end page-less: it deletes the page that was there."""

    return {"kind": "remove_page", "page_id": page_id}


def _assert_pageless_refusal(response: dict) -> None:
    assert response["status"] == "failed"
    assert response["operations"] == []
    assert response["diagnostics"][0]["code"] == "agent_turn.pageless_result"
    # The sentence a marketer reads names the fact — no page was made, nothing was saved, and
    # what to do next. "Design turn failed." would be true and useless. Asserted on BOTH prose
    # slots for the reason `_assert_conflict_is_legible` gives: `summary` is the design editor's
    # run-panel key, `stop_reason` the platform scene summarizer's, and the failure builder
    # leaves the latter None unless it is set deliberately.
    assert response["summary"] == PAGELESS_SUMMARY
    assert response["stop_reason"] == PAGELESS_SUMMARY


def test_a_leg_scene_turn_that_authors_the_first_page_commits_it(
    client: TestClient,
) -> None:
    """(a) The happy zero-page path: the agent authors the page, so the gate lets it through and
    the newborn advances to a document with something in it."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([add_page_operation()])),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert response["status"] == "proposed"
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1
    assert list(stored["scene"]["pages"]) == [AD_PAGE_ID]
    assert response["current_version"] == 1
    assert len(store.list_envelopes(document["id"])) == 1


def test_a_leg_scene_turn_that_makes_no_page_is_refused_instead_of_committed(
    client: TestClient,
) -> None:
    """(b) The operations replay cleanly — they just do not amount to a design. Committing them
    would advance the version and report success over a document with nothing to open."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")])),
        event_sink=None,
    )

    assert (status, kind) == ("failed", "result")
    assert marker == {"status": "failed"}
    _assert_pageless_refusal(response)
    # No write at all: not the version, not the title the meta-only op carried, not an envelope.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["pages"] == {}
    assert stored["scene"]["meta"]["title"] == "Harbor & Sage Launch Ad"
    assert store.list_envelopes(document["id"]) == []


def test_a_leg_scene_turn_proposing_nothing_on_a_pageless_document_is_refused(
    client: TestClient,
) -> None:
    """(c) The empty-proposal shape never reaches the replay, so the gate has to be repeated over
    the STORED scene. On a page-less newborn a contentless proposal is not a clarification — it
    is a generation that produced nothing, and saying "proposed" would be a fake success."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([])),
        event_sink=None,
    )

    assert (status, kind) == ("failed", "result")
    assert marker == {"status": "failed"}
    _assert_pageless_refusal(response)
    assert "current_version" not in response
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["pages"] == {}
    assert store.list_envelopes(document["id"]) == []


def test_a_leg_scene_turn_proposing_nothing_on_a_content_bearing_document_still_succeeds(
    client: TestClient,
) -> None:
    """(d) The regression pin. A pure clarification on a document that HAS a page is the same
    real, successful outcome it always was — byte-identical to the runner's own envelope. The
    gate reads the pages, never "did this turn commit anything"."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    # `minimal_scene()` — the scene this document was created from, and the one `_leg_config`
    # hands the turn — has a page WITH a child.
    assert store.require_document(document["id"])["scene"]["pages"]["page_a4"]["children"]

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([])),
        event_sink=None,
    )

    assert (status, kind, marker) == ("succeeded", "result", {"status": "proposed"})
    assert response == proposing_runner([])(None, None)
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert store.list_envelopes(document["id"]) == []


def test_a_leg_turn_that_deletes_the_only_page_is_refused_and_the_document_survives(
    client: TestClient,
) -> None:
    """(f) The other way into the refusal, and the one the prose does NOT describe.

    Every case above starts page-less and never gets a page. This one starts with REAL content
    and the turn deletes it: `remove_page` on the only page leaves an empty scene, which the
    engine refuses exactly as it refuses a newborn that authored nothing. The behaviour is the
    right one — a "successful" turn that erased the artifact would be the worst possible commit,
    and the document is left byte-untouched — but it is worth pinning precisely BECAUSE the
    refusal's own sentence ("Design finished without creating a page") misdescribes it. If a
    later lane wants deletion to read differently, this test is where that decision has to be
    made deliberately rather than discovered in production.
    """

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    before = store.require_document(document["id"])
    assert list(before["scene"]["pages"]) == ["page_a4"], "the fixture must have exactly one page"

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([remove_page_operation("page_a4")])),
        event_sink=None,
    )

    assert (status, kind) == ("failed", "result")
    assert marker == {"status": "failed"}
    _assert_pageless_refusal(response)
    # The engine's own text rides the detail (Task-7 sweep) instead of being dropped, the way
    # the replay refusal beside it has always forwarded `error.message`.
    assert response["diagnostics"][0]["hint"] == (
        "The turn's result contains no page, so there would be nothing to show; "
        "the design was not saved and the document is unchanged. "
        "The engine reported: operation batch produced an invalid scene"
    )
    # Nothing was written — the page, its children, and the version are all exactly as they were.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"] == before["scene"]
    assert store.list_envelopes(document["id"]) == []


def test_an_unreplayable_turn_on_a_pageless_document_still_reports_the_replay_failure(
    client: TestClient,
) -> None:
    """The gate must not swallow its neighbour's code. A page-less document is exactly where the
    two refusals could be confused, so the engine's own precedence is pinned: an operation that
    cannot apply at all fails BEFORE the scene is validated, so it is still an unreplayable
    history — `agent_turn.pageless_result` is reserved for operations that applied and simply did
    not amount to a page."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([unreplayable_operation()])),
        event_sink=None,
    )

    assert status == "failed"
    assert response["diagnostics"][0]["code"] == "agent_turn.operations_replay_failed"
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert store.list_envelopes(document["id"]) == []


class _AcceptingPagelessCore:
    """An engine that ACCEPTS the replay and hands back a page-less scene.

    The real engine refuses that scene itself (`LUMV0100`, `validate_scene`), so on the operations
    half of the gate its `CoreError` is what fires today and the post-replay page check never runs
    against it. That is exactly why the check is worth pinning separately: the contract is "what
    would be WRITTEN must have a page", read off the applied scene — not "the engine happened to
    complain". This stub is the only way to reach it, and it is what holds the line if the engine
    ever admits a page-less scene.
    """

    def __init__(self) -> None:
        self.calls = 0

    def apply_operations(self, scene: dict, operations: list) -> dict:
        self.calls += 1
        return {
            "scene": {**scene, "pages": {}},
            "diagnostics": [],
            "edit": {"inverse_operations": []},
        }


def test_a_leg_turn_whose_applied_scene_has_no_page_is_refused_even_if_the_engine_allows_it(
    client: TestClient,
) -> None:
    """(b, the gate itself) The operations replayed clean — no exception, no error diagnostic —
    and still produced nothing to look at. The refusal is the same one, and nothing is written."""

    from lumen_api.fleet_handler import DesignTurnHost
    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()
    core = _AcceptingPagelessCore()
    state = client.app.state

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=DesignTurnHost(
            agent_turn_runner=proposing_runner([add_page_operation()]),
            core=core,
            storage=state.storage,
            engine_cache_root=state.engine_cache_root,
        ),
        event_sink=None,
    )

    # The proposal DID carry a page-adding operation, so a gate reading the stored scene or the
    # operation list would have let this through: only the applied scene tells the truth.
    assert core.calls == 1
    assert (status, kind) == ("failed", "result")
    assert marker == {"status": "failed"}
    _assert_pageless_refusal(response)
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["pages"] == {}
    assert store.list_envelopes(document["id"]) == []


def test_a_non_leg_turn_on_a_pageless_document_stays_byte_identical(
    client: TestClient,
) -> None:
    """(e) P3.7's layering rule against the new gate: the editor's own direct turn carries no
    `leg` block, so it proposes exactly what the runner returned — the SAME operations that are
    refused one test above — and the editor's route still owns the commit."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()
    operations = [title_operation("Agent Title")]
    # Snapshotted from a deep copy BEFORE the run, for the reason the (a) byte-identity pin
    # gives: the stub and this test share one list object, so a post-run expectation built from
    # it cannot tell "unchanged" from "mutated in place".
    expected = proposing_runner(deepcopy(operations))(None, None)

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            {
                "request": {
                    "prompt": "Fill this document with a launch ad.",
                    "scene": document["scene"],
                    "document_id": document["id"],
                }
            },
        ),
        store=store,
        host=_turn_host(client, proposing_runner(operations)),
        event_sink=None,
    )

    assert (status, kind, marker) == ("succeeded", "result", {"status": "proposed"})
    assert response == expected
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["pages"] == {}
    assert store.list_envelopes(document["id"]) == []


# --- (h) genad2 walk: generated-asset custody at the leg persist seam ---------
#
# The live defect this section pins (walk of 2026-08-23, doc `doc_9e93c1e0…` v101): a chat-born
# ad's GENERATED hero image rendered in every server-side export (which bakes straight out of the
# engine cache) and 404'd on the editor canvas, which resolves pixels through
# `GET /asset-store/{digest}` — i.e. through DURABLE custody. The persist path's D4 backstop is
# what is supposed to make those two agree.
#
# What the walk's forensics actually showed, because it is not what anyone guessed: the backstop
# RAN and SUCCEEDED. Both of that scene's generated digests got live `artifact` rows, stamped
# `design_asset`, in the same second the leg run finished. The 404 came from the OTHER half of
# custody — the bytes those rows point at were not in the tree the serving process reads. The
# unhealable part, which is the defect these tests own, is that the backstop's skip probe was
# `exists`: a ROW probe ("no blob I/O"). Once a row exists no later persist re-puts the bytes,
# so a divergence that the engine cache could have repaired on the very next turn instead
# survives every turn, forever.


@pytest.fixture()
def custody_client(tmp_path: Path, design_storage) -> TestClient:
    """A leg-persist client whose blob backend is a tmp `FsStorage` this test can reach into.

    Reaching into it is the point: the live failure was bytes that were durably registered
    against ONE backend tree and read back from ANOTHER, and the only way to reproduce
    "the artifact row says custody, the backend has no bytes" is to delete a blob behind the
    store's back.
    """
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


def _workspace_cache_dir(client: TestClient) -> Path:
    return Path(client.app.state.engine_cache_root) / os.environ["LUMEN_DEV_WORKSPACE_ID"]


#: A 1x1 PNG (the spec's smallest valid one) standing in for a trio-generated hero image.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def unique_png() -> bytes:
    """A PNG whose digest no other row in the shared dev database can hold.

    Deliberate, and it cost an hour to learn: `/asset-store/{digest}` is workspace-UNSCOPED and
    scans a BOUNDED candidate list of live `artifact` rows for the content hash, skipping any
    whose bytes the backend cannot produce. `TINY_PNG` is a suite-wide fixture, so on a shared
    dev database its hash already has hundreds of rows from long-deleted tmp workspaces — the
    scan exhausts its budget on those corpses and 404s even when THIS test's custody is perfect.
    Bytes after IEND are legal trailing data, so the file stays a valid PNG.
    """
    return TINY_PNG + uuid4().bytes


def generated_asset_record(client: TestClient, asset_id: str, data: bytes) -> dict:
    """The record shape a trio image-generation tool leaves in the proposed scene.

    Copied from the live walk's `asset_img_run_6fa7_1`: bytes ONLY in the engine's per-workspace
    materialization cache, and a `local-store` location whose `opaque_ref` is the engine's own
    `sha256/{ab}/{digest}` relative path — never a `clue-storage` key, because nothing on the
    runtime tool's path re-points it.
    """
    digest = hashlib.sha256(data).hexdigest()
    from lumen_api.asset_custody import write_cache_blob

    write_cache_blob(_workspace_cache_dir(client), digest, data)
    record = json.loads(GENERATED_RASTER_ASSET_PATH.read_text())
    record["id"] = asset_id
    record["label"] = "hero_wave_ribbons"
    record["media"]["digest"] = {"algorithm": "sha256", "value": digest}
    record["media"]["location"] = {
        "provider": "local-store",
        "opaque_ref": f"sha256/{digest[:2]}/{digest}",
        "url": None,
    }
    record["media"]["mime_type"] = "image/png"
    record["media"]["byte_length"] = len(data)
    return record


def upsert_asset_operation(record: dict) -> dict:
    return {"kind": "upsert_asset", "asset": record}


def _durable_blob_path(client: TestClient, digest: str) -> Path:
    """Where this test's `FsStorage` physically holds one design blob."""
    from clue_design.storage import design_storage_key

    root = Path(client.app.state.storage._root)  # the tmp tree the fixture built
    return root.joinpath(
        *design_storage_key(os.environ["LUMEN_DEV_WORKSPACE_ID"], digest).split("/")
    )


def _artifact_row_count(digest: str) -> int:
    """How many live `artifact` rows THIS workspace holds for the digest — the idempotency
    assertion (scoped to the workspace, because the dev database is shared)."""
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]

    async def _count(conn):
        result = await conn.execute(
            text(
                "SELECT count(*) FROM artifact "
                "WHERE content_sha256 = :sha AND workspace_id = :ws "
                "AND erased_at IS NULL AND purged_at IS NULL"
            ),
            {"sha": digest, "ws": workspace_id},
        )
        return int(result.scalar_one())

    return DesignStoreBridge(workspace_id)._run(_count)


def _run_leg_turn(client: TestClient, document: dict, operations: list) -> dict:
    from lumen_api.main import execute_agent_turn_job

    store = HybridRepository()
    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            _leg_config(document, document["current_version"]),
        ),
        store=store,
        host=_turn_host(client, proposing_runner(operations)),
        event_sink=None,
    )
    assert status == "succeeded", response
    assert response["status"] == "proposed", response
    return response


def test_fresh_generation_bytes_are_durable_before_the_canvas_can_first_load_it(
    custody_client: TestClient,
) -> None:
    """(h1) Fresh-generation ordering: the canvas must see what the exporter sees.

    A leg turn generates imagery mid-run; those bytes live only in the engine's wipeable cache
    until the persist seam claims them. The completed run is the earliest point at which the
    browser can fetch the committed document and schedule its first canvas paint. At that point
    `/asset-store/{digest}` — the exact route its image cache will resolve — must already serve
    the bytes, with the engine cache gone.
    """
    from lumen_api.asset_custody import cache_blob_path

    pixels = unique_png()
    document = create_document(custody_client)
    record = generated_asset_record(custody_client, "asset_img_run_test_1", pixels)
    digest = record["media"]["digest"]["value"]
    assert not make_blob_store(custody_client.app).exists(digest), "precondition: cache-only"

    _run_leg_turn(custody_client, document, [upsert_asset_operation(record)])

    # Custody is BYTES, not a row: destroy the cache before simulating the
    # canvas's first document fetch. The scene may not become observable while
    # its image is still cache-only.
    cache_blob_path(_workspace_cache_dir(custody_client), digest).unlink()
    first_load = custody_client.get(f"/documents/{document['id']}")
    assert first_load.status_code == 200, first_load.text
    first_scene_asset = first_load.json()["scene"]["assets"][record["id"]]
    assert first_scene_asset["media"]["digest"]["value"] == digest

    served = custody_client.get(f"/asset-store/{digest}")
    assert served.status_code == 200, served.text
    assert served.content == pixels


def test_a_leg_persist_heals_a_scene_asset_whose_durable_bytes_are_gone(
    custody_client: TestClient,
) -> None:
    """(h2) THE live defect, and the healing contract.

    The walk's broken banner is exactly this state: a LIVE `artifact` row for the digest (the
    fleet worker's persist wrote one) and NO readable bytes in the backend the design API holds
    — because the two processes resolved the relative `CLUE_STORAGE_FS_ROOT` default against
    different working directories, so the row and the blob landed in different trees.

    The backstop's skip probe was row-only (`design_bytes_exist`, "no blob I/O"), so once a row
    existed no later persist could ever restore the bytes: the banner stayed broken forever.
    Custody is a claim about BYTES, so the probe must be about bytes — and then the next chat
    iteration on the broken ad heals it.
    """
    pixels = unique_png()
    document = create_document(custody_client)
    record = generated_asset_record(custody_client, "asset_img_run_test_2", pixels)
    digest = record["media"]["digest"]["value"]

    _run_leg_turn(custody_client, document, [upsert_asset_operation(record)])
    blob = _durable_blob_path(custody_client, digest)
    assert blob.is_file(), "precondition: the first persist gave custody"

    # The split-root shape: the row survives (it is in the shared database), the bytes do not
    # (they went to another process's tree).
    blob.unlink()
    assert make_blob_store(custody_client.app).exists(digest), "the row still claims custody"
    assert custody_client.get(f"/asset-store/{digest}").status_code == 404
    # ...and the cache still holds them, which is why healing is possible at all: the engine
    # cache root is anchored to the design tree, so BOTH processes always agreed on it.

    # The next iteration turn on the same document — the marketer asking for one more change.
    document = HybridRepository().require_document(document["id"])
    _run_leg_turn(custody_client, document, [title_operation("Warmer headline")])

    served = custody_client.get(f"/asset-store/{digest}")
    assert served.status_code == 200, served.text
    assert served.content == pixels


def test_a_leg_persist_over_complete_custody_does_not_duplicate_it(
    custody_client: TestClient,
) -> None:
    """(h3) Idempotent: re-persisting a scene whose assets are already durable is a no-op."""
    pixels = unique_png()
    document = create_document(custody_client)
    record = generated_asset_record(custody_client, "asset_img_run_test_3", pixels)
    digest = record["media"]["digest"]["value"]

    _run_leg_turn(custody_client, document, [upsert_asset_operation(record)])
    assert _artifact_row_count(digest) == 1
    blob = _durable_blob_path(custody_client, digest)
    stat_before = blob.stat().st_mtime_ns

    document = HybridRepository().require_document(document["id"])
    _run_leg_turn(custody_client, document, [title_operation("Second pass")])

    assert _artifact_row_count(digest) == 1, "custody must not be re-minted"
    assert blob.stat().st_mtime_ns == stat_before, "the blob must not be re-put"
    assert custody_client.get(f"/asset-store/{digest}").content == pixels
