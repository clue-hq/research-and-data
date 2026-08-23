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

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"


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

    Asserted on BOTH prose slots, because two different surfaces read two different keys:
    `summary` is what the design editor's own run panel shows, and `stop_reason` is the only
    key the platform's scene summarizer (`_assistant_summary`, design_leg_wiring) renders into
    the project chat thread. `failed_agent_turn_response` leaves `stop_reason` None, so a
    conflict built naively from it is contentless on the platform side by construction.
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
    assert response == proposing_runner(operations)(None, None)
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
