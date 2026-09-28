"""The web lane's review gate, its shared rubric, and its fast-loop flag (F3.3, D-F6 / D-F7).

Three things are pinned here, and they are the three the founder ruling is actually about:

* **One rubric, two readers.** The reviewer subagent's prompt and the orchestrator's self-review
  prompt render the SAME bytes, out of one file. Editing the file moves both — proved by pointing
  the loader at a different file and watching both compositions follow.
* **The flag changes WHO checks.** Default OFF → the reviewer subagent is registered exactly as
  before. ON → it is genuinely absent from the subagent list, the orchestrator carries the rubric
  instead, and nothing about what is measured moves.
* **The gate reports, it never refuses.** The tool's durable writes come from measurements and
  from nothing the model said; a walk with no browser refuses typed rather than reporting a clean
  page; and a critique that cannot be composed degrades to advice-absent.

The BROWSER is stubbed at the seam (`capture_behavioural_walk`), honestly and deliberately: what
is asserted is the walk's input and the tool's handling of its result. See
``apps/api/tests/test_clone_review_gate.py`` for the same discipline on the measurement half.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from lumen_agent import harness_web
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.harness_web import (
    WEB_AUTHOR_DELEGATION_CAP,
    WEB_REVIEW_DELEGATION_CAP,
)
from lumen_agent.prompts_web import (
    build_web_orchestrator_prompt,
    build_web_reviewer_prompt,
)
from lumen_agent.rubrics import (
    CLONE_REVIEW_RUBRIC_PATH,
    RubricMissing,
    clone_review_rubric_version,
    load_clone_review_rubric,
)
from lumen_agent.tools.web_substrate import LumenWebTools

from lumen_api.clone_review import (
    BehaviouralWalk,
    CaptureShot,
    CloneReviewRefused,
    ConsoleEntry,
    SectionMeasurement,
    WalkObservation,
    abstained,
)
from lumen_api.clone_review.walk import (
    MOBILE_VIEWPORT,
    WALK_CLASS_CONSOLE,
    WALK_CLASS_FULL_PAGE,
    WALK_CLASS_HEIGHT_COLLAPSE,
    WALK_CLASS_MOBILE,
    WALK_CLASS_REDUCED_MOTION,
    WALK_CLASS_SCROLL_THROUGH,
)
from lumen_api.fragments.degraded import (
    DEGRADED_REASON_MOBILE_UNUSABLE,
    DEGRADED_REASON_RUNTIME_DEAD_HEIGHT,
    GATE_REASONS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REVIEWER = "lumen-web-reviewer"
AUTHOR = "lumen-web-author"


# =================================================================================================
# 1. The shared rubric artifact — one source, two readers
# =================================================================================================


def _orchestrator(web_reviewer: bool) -> str:
    return build_web_orchestrator_prompt(
        doc_title="Harbor & Sage",
        has_existing_content=False,
        brand_card="warm, coastal",
        review_cap=WEB_REVIEW_DELEGATION_CAP,
        author_cap=WEB_AUTHOR_DELEGATION_CAP,
        web_reviewer=web_reviewer,
    )


def test_the_rubric_is_a_versioned_artifact_on_disk_not_a_prompt_constant() -> None:
    assert CLONE_REVIEW_RUBRIC_PATH.exists()
    assert clone_review_rubric_version() >= 1
    rubric = load_clone_review_rubric()
    # The maintainers' header is NOT shipped into anybody's context.
    assert "founder review pending" not in rubric
    assert rubric.startswith("CLONE-REVIEW RUBRIC")
    # D-F7's three halves are all present, in the ruling's own terms.
    for phrase in (
        "SOFT",
        "animation timing",
        "STRICT",
        "blank space",
        "broken controls",
        "unusable height",
        "invisible elements",
        "failed mobile behaviour",
        "spacing and section rhythm",
        "typography",
        "colors",
    ):
        assert phrase in rubric, phrase


def test_the_reviewer_and_the_self_review_render_the_same_rubric_bytes() -> None:
    rubric = load_clone_review_rubric()
    reviewer_prompt = build_web_reviewer_prompt()
    self_review_prompt = _orchestrator(web_reviewer=False)

    assert rubric in reviewer_prompt
    assert rubric in self_review_prompt
    # Not merely "both contain a rubric" — the SAME one, byte for byte.
    assert reviewer_prompt.count(rubric) == 1
    assert self_review_prompt.count(rubric) == 1


def test_editing_the_artifact_moves_BOTH_compositions(tmp_path, monkeypatch) -> None:
    """The no-private-copy guarantee, checked rather than asserted in a comment."""
    edited = tmp_path / "rubric.md"
    edited.write_text(
        "<!--\nversion: 99\n-->\n--- rubric ---\nSTRICT: a rubric nobody has seen before.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "lumen_agent.rubrics.CLONE_REVIEW_RUBRIC_PATH", edited, raising=True
    )

    reviewer_prompt = build_web_reviewer_prompt()
    self_review_prompt = _orchestrator(web_reviewer=False)

    assert "a rubric nobody has seen before" in reviewer_prompt
    assert "a rubric nobody has seen before" in self_review_prompt
    assert "animation timing" not in reviewer_prompt
    assert "animation timing" not in self_review_prompt


def test_a_missing_rubric_is_loud_rather_than_an_empty_block(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "lumen_agent.rubrics.CLONE_REVIEW_RUBRIC_PATH",
        tmp_path / "not-here.md",
        raising=True,
    )
    with pytest.raises(RubricMissing) as excinfo:
        load_clone_review_rubric()
    assert "shared clone-review rubric" in str(excinfo.value)


# =================================================================================================
# 2. The fast-loop flag — who checks, never what is checked
# =================================================================================================


def test_the_web_fast_loop_is_off_by_default_and_the_reviewer_is_enabled() -> None:
    config = AgentRuntimeConfig.from_env(REPO_ROOT)
    assert config.web_fast_loop is False
    assert config.web_reviewer_enabled is True


def test_the_flag_quarantines_the_reviewer_and_the_kill_switch_puts_it_back() -> None:
    base = AgentRuntimeConfig.from_env(REPO_ROOT)
    assert replace(base, web_fast_loop=True).web_reviewer_enabled is False
    assert (
        replace(base, web_fast_loop=True, web_reviewer=True).web_reviewer_enabled is True
    )
    # The scene lane's flag is a different flag and does not reach across.
    assert replace(base, fast_loop=True).web_reviewer_enabled is True


def test_the_default_prompt_keeps_the_delegated_review_shape_and_no_rubric() -> None:
    """Renamed in the fix round (review finding M7): this asserts three properties, not byte
    identity — there is no golden of the pre-F3.3 prompt to be identical to."""
    prompt = _orchestrator(web_reviewer=True)
    assert "Delegate `lumen-web-reviewer` for the structured pass" in prompt
    assert str(WEB_REVIEW_DELEGATION_CAP) in prompt
    # Flag OFF, the orchestrator is NOT the reviewer, so it does not carry the reviewer's rubric.
    assert load_clone_review_rubric() not in prompt


def test_the_quarantined_prompt_never_promises_a_delegation_the_runtime_would_reject() -> None:
    prompt = _orchestrator(web_reviewer=False)
    assert "lumen-web-reviewer" not in prompt
    assert "REVIEW THE PAGE YOURSELF" in prompt
    # The author budget is still promised, because the author is still there.
    assert str(WEB_AUTHOR_DELEGATION_CAP) in prompt


def _create_web_agent(tmp_path, monkeypatch, config) -> dict:
    import deepagents

    import lumen_agent.llm as llm
    from lumen_api.core import CoreClient

    captured: dict = {}
    monkeypatch.setattr(deepagents, "create_deep_agent", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(harness_web, "materialize_agent_workspace", lambda _config: None)
    monkeypatch.setattr(
        harness_web, "_instrument", lambda _config, _tools, _model, role: f"{role}-model"
    )
    monkeypatch.setattr(llm, "assert_all_role_models_support_image_input", lambda _config: None)
    web_doc = CoreClient(repo_root=REPO_ROOT).web_new_doc("doc_alpha", "Alpha", None)["web_doc"]
    harness_web.create_web_deepagent("Build a page.", config, web_doc)
    return captured


def test_flag_off_composes_the_reviewer_subagent(tmp_path, monkeypatch) -> None:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "ws", web_fast_loop=False
    )
    captured = _create_web_agent(tmp_path, monkeypatch, config)
    names = [sa["name"] for sa in captured["subagents"]]
    assert names == [AUTHOR, REVIEWER]


def test_flag_on_leaves_the_reviewer_genuinely_absent(tmp_path, monkeypatch) -> None:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "ws", web_fast_loop=True
    )
    captured = _create_web_agent(tmp_path, monkeypatch, config)
    names = [sa["name"] for sa in captured["subagents"]]
    assert names == [AUTHOR]
    assert REVIEWER not in names
    # The orchestrator now carries the rubric it would otherwise have delegated.
    assert load_clone_review_rubric() in captured["system_prompt"]


def test_the_review_gate_is_an_orchestrator_tool_in_both_flag_states(
    tmp_path, monkeypatch
) -> None:
    for fast_loop in (False, True):
        config = replace(
            AgentRuntimeConfig.from_env(REPO_ROOT),
            trace_dir=tmp_path / f"ws_{fast_loop}",
            web_fast_loop=fast_loop,
        )
        captured = _create_web_agent(tmp_path, monkeypatch, config)
        names = {
            getattr(tool, "name", None) or getattr(tool, "__name__", None)
            for tool in captured["tools"]
        }
        assert "review_cloned_page" in names, fast_loop


def test_the_gates_mobile_width_is_the_platforms_own_preview_width() -> None:
    """Drift guard: the gate's phone verdict and the reviewer's phone screenshot are one page."""
    from lumen_agent.tools.web_substrate import _PREVIEW_WIDTHS

    assert MOBILE_VIEWPORT.width == min(_PREVIEW_WIDTHS)


# =================================================================================================
# 3. The tool — the walk, the verdicts, the advice
# =================================================================================================

FRAGMENT_ID = "frag_0123456789abcdef"
WRAPPER = "lumen-frag-0123456789abcdef"

FRAGMENT_HTML = '<section class="clone-hero"><h1>Care, on your terms</h1></section>'


class FakeRegistry:
    """The two gate methods the real capability exposes, and nothing else."""

    def __init__(self, *, reference: dict | None = None, refuse: bool = False) -> None:
        self.marked: list[tuple[str, str]] = []
        self.reference = reference
        self.refuse = refuse

    def mark_degraded(self, fragment_id: str, *, reason: str) -> dict:
        if reason not in GATE_REASONS:
            raise ValueError("not one of the gate's reasons")
        if self.refuse:
            raise RuntimeError("the library is unreachable")
        self.marked.append((fragment_id, reason))
        return {"fragment_id": fragment_id, "degraded": True, "degraded_reason": reason}

    def reference_review(self, fragment_ids, **kwargs) -> dict:
        if self.reference is None:
            return {"status": "unavailable", "because": "no_snapshot_provenance"}
        return self.reference

    # Present so composing the substrate does not trip over an absent capability.
    def list_sections(self, section_role=None) -> dict:
        return {"schema_version": 1, "sections": [], "total": 0}


def _seed_doc() -> dict:
    """A document with one cloned section actually pinned on it.

    The wrapper-section + fragment-leaf pair is the shape `insert_cloned_section` builds and the
    only shape the page root accepts (LUMW0011). Written directly rather than through the insert
    tool so this file's subject stays the review gate; the pair's own shape is pinned in
    ``test_web_cloned_sections.py``.
    """
    from lumen_api.core import CoreClient

    doc = CoreClient(repo_root=REPO_ROOT).web_new_doc("doc_gate", "Gate", None)["web_doc"]
    page = doc["pages"][0]
    page["nodes"]["sec_clone"] = {
        "id": "sec_clone",
        "kind": "section",
        "tag": "section",
        "classes": "w-full",
        "children": ["frg_clone"],
    }
    page["nodes"]["frg_clone"] = {
        "id": "frg_clone",
        "kind": "fragment",
        "classes": "",
        "fragment_id": FRAGMENT_ID,
    }
    page["nodes"]["root"]["children"] = ["sec_clone"]
    return doc


def _tools(tmp_path: Path, registry: FakeRegistry | None) -> LumenWebTools:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        cloned_section_registry=registry,
    )
    return LumenWebTools(config, "Build a page", initial_web_doc=_seed_doc())


def _measurement(**overrides) -> SectionMeasurement:
    base = {
        "fragment_id": FRAGMENT_ID,
        "selector": f".{WRAPPER}",
        "viewport": "desktop",
        "present": True,
        "visible": True,
        "top_px": 120.0,
        "width_px": 1440.0,
        "height_px": 800.0,
        "content_extent_px": 640.0,
        "ink_nodes": 9,
        "scroll_width_px": 1440.0,
    }
    base.update(overrides)
    return SectionMeasurement(**base)


def _fake_walk(
    tmp_path: Path,
    *,
    desktop=(),
    mobile=(),
    console=(),
    mobile_made: bool = True,
    styles_ready: object = True,
    media_ready: object = True,
) -> BehaviouralWalk:
    shot = tmp_path / "walk_full_page.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")
    return BehaviouralWalk(
        observations=(
            WalkObservation(
                walk_class=WALK_CLASS_FULL_PAGE,
                made=True,
                shots=(
                    CaptureShot(
                        walk_class=WALK_CLASS_FULL_PAGE,
                        label="full page",
                        path=str(shot),
                        viewport_width=1440,
                    ),
                ),
            ),
            WalkObservation(walk_class=WALK_CLASS_SCROLL_THROUGH, made=True),
            (
                WalkObservation(
                    walk_class=WALK_CLASS_MOBILE,
                    made=True,
                    measurements=mobile,
                    notes={
                        "styles_ready": styles_ready,
                        "media_readiness": {"settled": media_ready},
                    },
                )
                if mobile_made
                else abstained(WALK_CLASS_MOBILE, "timed_out")
            ),
            WalkObservation(walk_class=WALK_CLASS_CONSOLE, made=True, console=console),
            WalkObservation(
                walk_class=WALK_CLASS_HEIGHT_COLLAPSE,
                made=True,
                measurements=desktop,
                notes={"styles_ready": styles_ready, "media_readiness": {"settled": media_ready}},
            ),
            WalkObservation(walk_class=WALK_CLASS_REDUCED_MOTION, made=True, notes={}),
        )
    )


def _patch_walk(monkeypatch, result) -> dict:
    captured: dict = {}

    def _fake(page_html, plan, *, output_dir):
        captured["html"] = page_html
        captured["plan"] = plan
        captured["output_dir"] = output_dir
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "lumen_agent.tools.web_substrate.capture_behavioural_walk", _fake, raising=True
    )
    return captured


def test_the_gate_walks_the_same_pixels_the_preview_renders(tmp_path, monkeypatch) -> None:
    registry = FakeRegistry()
    tools = _tools(tmp_path, registry)
    captured = _patch_walk(monkeypatch, _fake_walk(tmp_path))

    result = json.loads(tools.review_cloned_page())

    assert result["status"] == "ok"
    assert result["advice_only"] is True
    # All six classes come back labelled, whether or not they found anything.
    assert len(result["captures"]) == 6
    assert all(capture["label"] for capture in result["captures"])
    # The walk was handed the engine's own render of THIS document — the tailwind runtime and all.
    assert "<html" in captured["html"].lower()
    assert captured["plan"].desktop.width == 1440
    assert captured["plan"].mobile.width == 375


def test_failed_repeat_review_retains_failure_alongside_previous_evidence(tmp_path, monkeypatch):
    tools = _tools(tmp_path, FakeRegistry())
    _patch_walk(monkeypatch, _fake_walk(tmp_path, desktop=(_measurement(),)))
    assert json.loads(tools.review_cloned_page())["status"] == "ok"
    _patch_walk(monkeypatch, CloneReviewRefused("review.browser_unavailable", "browser unavailable"))
    assert json.loads(tools.review_cloned_page())["status"] == "error"
    evidence = json.loads(tools._view_content("review")[0]["text"])
    assert evidence["clone_review"]["status"] == "failed"
    assert evidence["clone_review"]["error_code"] == "review.browser_unavailable"
    assert evidence["clone_review"]["previous_observation"]["evidence_settled"] is True
    final = json.loads(tools.finalize_web_run("completed_with_warnings", "Review unavailable"))
    assert final["review_evidence"]["clone_review"] == evidence["clone_review"]


def test_no_browser_refuses_and_reports_nothing_about_the_page(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, FakeRegistry())
    _patch_walk(
        monkeypatch,
        CloneReviewRefused("review.browser_unavailable", "playwright is not available"),
    )

    result = json.loads(tools.review_cloned_page())

    assert result["status"] == "error"
    assert result["error_code"] == "review.browser_unavailable"
    # No verdict of any kind — not "no problems found".
    assert "broken_clones" not in result
    assert "captures" not in result


def test_a_measured_verdict_is_written_to_the_library_with_the_gates_own_reason(
    tmp_path, monkeypatch
) -> None:
    registry = FakeRegistry()
    tools = _tools(tmp_path, registry)
    _patch_walk(
        monkeypatch,
        _fake_walk(
            tmp_path,
            desktop=(_measurement(height_px=3200.0, content_extent_px=400.0),),
        ),
    )

    result = json.loads(tools.review_cloned_page())

    assert registry.marked == [(FRAGMENT_ID, DEGRADED_REASON_RUNTIME_DEAD_HEIGHT)]
    assert result["marked_degraded"] == [
        {"fragment_id": FRAGMENT_ID, "reason": DEGRADED_REASON_RUNTIME_DEAD_HEIGHT}
    ]
    broken = result["broken_clones"][0]
    assert broken["reason"] == DEGRADED_REASON_RUNTIME_DEAD_HEIGHT
    assert broken["measurement"]["desktop"]["height_px"] == 3200.0
    codes = {item["code"] for item in result["diagnostics"]}
    assert "LUMA0800" in codes


def test_a_verdict_the_library_would_not_take_is_reported_rather_than_swallowed(
    tmp_path, monkeypatch
) -> None:
    registry = FakeRegistry(refuse=True)
    tools = _tools(tmp_path, registry)
    _patch_walk(
        monkeypatch,
        _fake_walk(
            tmp_path,
            desktop=(_measurement(),),
            mobile=(
                _measurement(
                    viewport="mobile", width_px=375.0, scroll_width_px=900.0, height_px=600.0
                ),
            ),
        ),
    )

    result = json.loads(tools.review_cloned_page())

    assert registry.marked == []
    assert result["broken_clones"][0]["reason"] == DEGRADED_REASON_MOBILE_UNUSABLE
    assert result["marked_degraded"] == []
    failure = next(item for item in result["diagnostics"] if item["code"] == "LUMA0803")
    assert "will keep offering that band as healthy" in failure["message"]


def test_a_walk_that_could_not_observe_a_class_says_so_loudly(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, FakeRegistry())
    _patch_walk(monkeypatch, _fake_walk(tmp_path, desktop=(_measurement(),), mobile_made=False))

    result = json.loads(tools.review_cloned_page())

    gap = next(item for item in result["diagnostics"] if item["code"] == "LUMA0801")
    assert "mobile viewport" in gap["message"]
    assert "not the same as saying they are fine" in gap["message"]
    evidence = json.loads(tools._view_content("review")[0]["text"])
    assert evidence["clone_review"]["unobserved_capture_classes"] == [WALK_CLASS_MOBILE]


def test_console_errors_ride_the_advice_and_never_the_marker(tmp_path, monkeypatch) -> None:
    registry = FakeRegistry()
    tools = _tools(tmp_path, registry)
    _patch_walk(
        monkeypatch,
        _fake_walk(
            tmp_path,
            desktop=(_measurement(),),
            console=(
                ConsoleEntry(
                    level="error",
                    text="Uncaught ReferenceError: gsap is not defined",
                    url="https://isolation.test/legacy.js",
                    line=7,
                ),
            ),
        ),
    )

    result = json.loads(tools.review_cloned_page())

    assert registry.marked == []  # a console error is not a verdict about one band
    finding = next(
        item for item in result["page_findings"] if item["code"] == "review.console_error"
    )
    assert "legacy.js:7" in finding["message"]


def test_a_critique_that_cannot_be_composed_leaves_the_walk_and_loses_only_the_opinion(
    tmp_path, monkeypatch
) -> None:
    tools = _tools(tmp_path, FakeRegistry())
    _patch_walk(monkeypatch, _fake_walk(tmp_path, desktop=(_measurement(),)))

    def _explode(*args, **kwargs):
        raise RuntimeError("the critique blew up")

    monkeypatch.setattr(
        "lumen_agent.tools.web_substrate.compose_critique", _explode, raising=True
    )

    result = json.loads(tools.review_cloned_page())

    # The turn is NOT dead and the captures are still real.
    assert result["status"] == "ok"
    assert len(result["captures"]) == 6
    assert result["advice_available"] is False
    assert result["broken_clones"] == []
    assert result["page_findings"][0]["code"] == "review.advice_unavailable"
    assert any(item["code"] == "LUMA0802" for item in result["diagnostics"])


def test_the_blind_side_by_side_is_written_with_its_key_in_a_separate_file(
    tmp_path, monkeypatch
) -> None:
    from lumen_api.clone_review import build_blind_side_by_side

    from io import BytesIO

    from PIL import Image

    def _png(fill: int) -> bytes:
        buffer = BytesIO()
        Image.new("L", (600, 900), fill).save(buffer, format="PNG")
        return buffer.getvalue()

    blind = build_blind_side_by_side(
        published_png=_png(250), reference_png=_png(200), seed="run:1"
    )
    registry = FakeRegistry(
        reference={
            "status": "ok",
            "snapshot_id": "snap_1",
            "page_url": "https://insight.example/",
            "comparison": {"status": "ok", "bands": [], "skipped_bands": []},
            "blind_png": blind.image_png,
            "blind_key": blind.key,
        }
    )
    tools = _tools(tmp_path, registry)
    _patch_walk(monkeypatch, _fake_walk(tmp_path, desktop=(_measurement(),)))

    result = json.loads(tools.review_cloned_page())

    artifact = result["blind_side_by_side"]
    image_path = Path(artifact["image_path"])
    key_path = Path(artifact["answer_key_path"])
    assert image_path.exists() and key_path.exists()
    assert image_path != key_path  # the whole mechanism: the key is NOT in the picture
    key = json.loads(key_path.read_text(encoding="utf-8"))
    assert set(key["panels"]) == {"A", "B"}
    assert artifact["panels"] == ["A", "B"]
    assert "BEFORE opening the answer key" in artifact["note"]
    # Nothing in the tool's own result gives the answer away.
    assert "published" not in json.dumps(artifact)


def test_a_workspace_with_no_reference_capture_says_which_half_is_missing(
    tmp_path, monkeypatch
) -> None:
    tools = _tools(tmp_path, FakeRegistry(reference=None))
    _patch_walk(monkeypatch, _fake_walk(tmp_path, desktop=(_measurement(),)))

    result = json.loads(tools.review_cloned_page())

    assert result["reference_unavailable"] == "no_snapshot_provenance"
    gap = next(item for item in result["diagnostics"] if item["code"] == "LUMA0801")
    assert "the client's own page" in gap["message"]
    assert "blind_side_by_side" not in result


# =================================================================================================
# Fix round — R19-1: a durable write requires settled evidence
# =================================================================================================


@pytest.mark.parametrize("styles_ready,media_ready", [(False, True), (True, False), (True, None)])
def test_an_unsettled_walk_reports_the_finding_and_writes_nothing(
    tmp_path, monkeypatch, styles_ready, media_ready
) -> None:
    """The false `mobile_unusable` the review found: a page whose utilities have not compiled
    overflows 375px trivially, and the marker it would write can never be cleared."""
    registry = FakeRegistry()
    tools = _tools(tmp_path, registry)
    _patch_walk(
        monkeypatch,
        _fake_walk(
            tmp_path,
            desktop=(_measurement(),),
            mobile=(
                _measurement(
                    viewport="mobile", width_px=375.0, scroll_width_px=900.0, height_px=600.0
                ),
            ),
            styles_ready=styles_ready,
            media_ready=media_ready,
        ),
    )

    result = json.loads(tools.review_cloned_page())

    assert result["evidence_settled"] is False
    # The finding is STILL made — it is advice this round, not a secret.
    assert result["broken_clones"][0]["reason"] == DEGRADED_REASON_MOBILE_UNUSABLE
    assert registry.marked == []
    assert result["marked_degraded"] == []
    assert any(
        item["code"] == "review.evidence_unsettled" for item in result["page_findings"]
    )
    work = next(item for item in result["diagnostics"] if item["code"] == "LUMA0800")
    assert "NOTHING was recorded" in work["hint"]


def test_a_settled_walk_writes_as_before(tmp_path, monkeypatch) -> None:
    registry = FakeRegistry()
    tools = _tools(tmp_path, registry)
    _patch_walk(
        monkeypatch,
        _fake_walk(
            tmp_path,
            desktop=(_measurement(height_px=3200.0, content_extent_px=400.0),),
            styles_ready=True,
        ),
    )

    result = json.loads(tools.review_cloned_page())

    assert result["evidence_settled"] is True
    assert registry.marked == [(FRAGMENT_ID, DEGRADED_REASON_RUNTIME_DEAD_HEIGHT)]
    assert not any(
        item["code"] == "review.evidence_unsettled" for item in result["page_findings"]
    )


def test_the_rubric_no_longer_claims_the_walked_page_is_script_free() -> None:
    """Ruling R19-2: no false premise ships. The page the gate walks carries our Tailwind JIT."""
    rubric = load_clone_review_rubric()
    assert "console errors ATTRIBUTED TO THE PAGE" in rubric
    assert "does run scripts of its own" in rubric
    assert "are not the page's fault" in rubric
    # The old, false, unqualified claim is gone.
    assert "A cloned band carries no scripts, so an error has a real cause." not in rubric


# =================================================================================================
# Round-2 fixes — the readiness gate fails CLOSED, and the blind artifact survives an abstention
# =================================================================================================


def _head_of(tools: LumenWebTools) -> str:
    html, _diagnostics, _missing = tools._render_page_html()
    lowered = html.lower()
    start = lowered.find("<head")
    end = lowered.find("</head>")
    assert start >= 0 and end > start, "the engine emitted no head to anchor on"
    return html[start:end]


def test_the_readiness_anchor_is_real_in_the_page_we_actually_render(tmp_path) -> None:
    """The PREMISE, tested against a real editor-mode render rather than against a fake.

    Two properties, and the second is the one round 2 exists for:

    1. with the runtime present our marked `<script>` is in `<head>`, so the predicate has an
       anchor to look forward from — and at PARSE time no untyped, non-empty `<style>` follows it,
       so the predicate is honestly `false` until the JIT appends its output;
    2. with the runtime ABSENT the marked script does not exist anywhere, so the predicate's first
       clause fails and it can never answer `true` — which is the exact case the previous version
       got wrong, because the engine's own unconditional untyped `@layer base` style satisfied it.
    """
    from selectolax.lexbor import LexborHTMLParser

    from lumen_api.clone_review.walk import TAILWIND_RUNTIME_MARKER

    tools = _tools(tmp_path, FakeRegistry())
    head = _head_of(tools)
    tree = LexborHTMLParser(head)

    anchors = tree.css(f"script[{TAILWIND_RUNTIME_MARKER}]")
    assert len(anchors) == 1, "the review gate's readiness anchor is missing from the render"

    # The engine DOES emit an untyped, non-empty <style> — that is what the old predicate
    # wrongly accepted — and every one of them sits BEFORE our anchor.
    styles = [
        node
        for node in tree.css("style")
        if not node.attributes.get("type") and (node.text() or "").strip()
    ]
    assert styles, "the engine's own untyped style block is gone; this test's premise moved"
    marker_at = head.index(TAILWIND_RUNTIME_MARKER)
    for node in styles:
        assert head.index(node.html or "") < marker_at, (
            "an untyped engine style follows the runtime anchor, which would make the readiness "
            "predicate answer true before the JIT has compiled anything"
        )


def test_a_render_with_no_tailwind_runtime_can_never_be_settled(tmp_path, monkeypatch) -> None:
    """Breakage #1: the vendored runtime is untracked, so this is a reachable deployment state."""
    from selectolax.lexbor import LexborHTMLParser

    import lumen_agent.tools.web_substrate as substrate
    from lumen_api.clone_review.walk import TAILWIND_RUNTIME_MARKER

    monkeypatch.setattr(substrate, "tailwind_runtime_path", lambda _root: None)
    registry = FakeRegistry()
    tools = _tools(tmp_path, registry)

    # No anchor in the rendered head at all.
    head = _head_of(tools)
    assert TAILWIND_RUNTIME_MARKER not in head
    assert LexborHTMLParser(head).css("style"), "the engine still emits its own style blocks"

    # ...and the tool refuses to call the evidence settled, even for a page that claims readiness.
    _patch_walk(
        monkeypatch,
        _fake_walk(
            tmp_path,
            desktop=(_measurement(height_px=3200.0, content_extent_px=200.0),),
            mobile=(
                _measurement(
                    viewport="mobile", width_px=375.0, scroll_width_px=900.0, height_px=600.0
                ),
            ),
            styles_ready=True,
        ),
    )
    result = json.loads(tools.review_cloned_page())

    assert result["tailwind_runtime_missing"] is True
    assert result["evidence_settled"] is False
    assert registry.marked == []
    assert result["marked_degraded"] == []
    assert result["broken_clones"], "the finding is still reported — it is advice, not a secret"


def test_the_blind_artifact_survives_a_comparison_that_abstained(tmp_path, monkeypatch) -> None:
    """Breakage #4: a viewport mismatch is a missing number, not a missing acceptance artifact."""
    from io import BytesIO

    from PIL import Image

    from lumen_api.clone_review import build_blind_side_by_side

    def _png(fill: int) -> bytes:
        buffer = BytesIO()
        Image.new("L", (600, 900), fill).save(buffer, format="PNG")
        return buffer.getvalue()

    blind = build_blind_side_by_side(
        published_png=_png(250), reference_png=_png(200), seed="mismatch"
    )
    registry = FakeRegistry(
        reference={
            "status": "unavailable",
            "because": "reference_viewport_mismatch",
            "snapshot_id": "snap_1",
            "page_url": "https://insight.example/",
            "comparison": {"status": "unavailable", "because": "reference_viewport_mismatch"},
            "blind_png": blind.image_png,
            "blind_key": blind.key,
        }
    )
    tools = _tools(tmp_path, registry)
    _patch_walk(monkeypatch, _fake_walk(tmp_path, desktop=(_measurement(),)))

    result = json.loads(tools.review_cloned_page())

    assert result["reference_unavailable"] == "reference_viewport_mismatch"
    evidence = json.loads(tools._view_content("review")[0]["text"])
    assert evidence["clone_review"]["reference_unavailable"] == "reference_viewport_mismatch"
    assert any(item["code"] == "review.source_comparison_unavailable" for item in evidence["gaps"])
    tools._doc_version += 1
    assert json.loads(tools._view_content("review")[0]["text"])["clone_review"]["status"] == "stale"
    artifact = result["blind_side_by_side"]
    assert Path(artifact["image_path"]).exists()
    assert Path(artifact["answer_key_path"]).exists()


def test_the_review_result_carries_its_new_schema_version(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, FakeRegistry())
    _patch_walk(monkeypatch, _fake_walk(tmp_path))
    assert json.loads(tools.review_cloned_page())["schema_version"] == 2


def test_the_review_states_its_section_coverage_when_it_is_partial():
    """Final-review X1: the gate probes only fragment-wrapped bands, so a draft repair or a
    composed section is structurally invisible to it — the CP1 walk measured 4 of 11 bands and
    the incompleteness line counted walk classes only. Partial coverage is now a named gap in
    the same LUMA0801 breath, with both numbers."""
    from types import SimpleNamespace

    from lumen_agent.tools.web_substrate import LumenWebTools

    walk = SimpleNamespace(abstentions=[])
    diagnostics = LumenWebTools._review_diagnostics(
        object(),
        walk,
        broken=(),
        advice_failure=None,
        mark_failures=[],
        reference_note=None,
        settled=True,
        probed=4,
        section_total=11,
    )
    incomplete = [d for d in diagnostics if d["code"] == "LUMA0801"]
    assert len(incomplete) == 1
    message = incomplete[0]["message"]
    assert "4 of the page's 11 bands" in message
    assert "were not measured" in message

    # Full coverage says nothing — the line exists for the gap, not as ceremony.
    assert (
        LumenWebTools._review_diagnostics(
            object(),
            walk,
            broken=(),
            advice_failure=None,
            mark_failures=[],
            reference_note=None,
            settled=True,
            probed=11,
            section_total=11,
        )
        == []
    )
