"""§5.4 — deterministic autofix: the code loop below the model.

`docs/deepagent-fast-loop-v1-spec.md` §5.4. The 2026-08-24 baseline spent model
calls — 10–25s and ~100K input tokens each — repairing preflight diagnostics
whose correct fix the engine had already implied. This suite pins the two
classes that ship, the guards that keep them from guessing, and the four
properties the loop owes the rest of the runtime:

* a RED case per class: the diagnostic is present, and the loop clears it with
  zero model calls (the tests never construct a model — that is the assertion);
* a ROLLBACK case per class: an unfixable variant leaves the original
  diagnostic exactly as the engine wrote it, plus a note that autofix tried;
* the bounded-passes cap;
* flag-off, which must be indistinguishable from the pre-fast-loop runtime.

The fake engine below is a MINIATURE of the real one, not a script: it
re-derives diagnostics from whatever scene it is handed, using the same rules
`crates/lumen-core/src/layout.rs` uses (a fixed box smaller than its content
overflows; a hug box does not; a hug box wider than its parent exceeds parent
bounds; a slot with no fixtures has no fit validation; a fixture that does not
fit its bound node overflows). That matters: a scripted engine would let the
loop "pass" by asserting on inputs, whereas here every acceptance is the fake
engine genuinely re-measuring the patched scene, exactly as `_verify` requires.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from typing import Any, Optional

import pytest

from lumen_agent import autofix as autofix_mod
from lumen_agent.autofix import (
    EXCLUDED_CLASSES,
    SHIPPED_CLASSES,
    AutofixPatch,
    diagnostic_key,
    plan_autofix,
    run_autofix,
)
from lumen_agent.tools.substrate import LumenDesignTools

from agent_fixtures import FakeCoreClient, runtime_config

JsonObject = dict[str, Any]

#: The fake measurer: one character is this wide, one line is this tall. Real
#: shaping lives in Skia; what matters here is that a width/height verdict is
#: DERIVED from content rather than declared by the test.
_CHAR_W = 10.0
_LINE_H = 40.0


# --------------------------------------------------------------------------- #
# the miniature engine
# --------------------------------------------------------------------------- #
def _text(node_id: str, content: str, *, width: Any, height: Any, **extra) -> JsonObject:
    node = {
        "id": node_id,
        "name": node_id,
        "kind": {"kind": "text", "content": content, "font_size": 32.0},
        "children": [],
        "size": {"width": width, "height": height},
        "fills": [],
        "strokes": [],
        "clip": False,
        "opacity": 1.0,
        "locked": False,
    }
    node.update(extra)
    return node


def _fixed(value: float) -> JsonObject:
    return {"kind": "fixed", "value": value}


_HUG = {"kind": "hug"}


def _slot(slot_id: str, key: str, *, bound: list[str], **extra) -> JsonObject:
    slot = {
        "id": slot_id,
        "key": key,
        "label": key,
        "content_type": "text_short",
        "bound_nodes": bound,
        "required": True,
        "placeholder": None,
        "validation": {"samples": [], "worst_case": None, "max_length": None},
    }
    slot.update(extra)
    return slot


def _diag(code: str, severity: str, kind: str, ident: str, message: str = "") -> JsonObject:
    return {
        "severity": severity,
        "phase": "layout",
        "code": code,
        "message": message or f"{code} on {ident}",
        "subject": {"kind": kind, "id": ident},
        "hint": None,
    }


class FakeEngine:
    """Applies operations and re-derives diagnostics, like the real helper.

    ``parent_width`` stands in for the artboard/parent box every text node sits
    in: a hug box wider than it produces LUMV0801, which is precisely how a
    well-meant widen becomes a worse scene — and therefore the rollback case.
    """

    def __init__(self, scene: JsonObject, *, parent_width: float = 10_000.0) -> None:
        self.scene = copy.deepcopy(scene)
        self.parent_width = parent_width
        self.apply_calls = 0
        self.preflight_calls = 0

    # -- engine surface ---------------------------------------------------- #
    def apply_operations(self, scene: JsonObject, operations: list[JsonObject]) -> JsonObject:
        self.apply_calls += 1
        draft = copy.deepcopy(scene)
        for operation in operations:
            if operation["kind"] == "update_node":
                node = draft["nodes"][operation["node_id"]]
                patch = operation["patch"]
                for field, value in patch.items():
                    if isinstance(value, dict) and value.get("kind") == "set":
                        node[field] = copy.deepcopy(value["value"])
            elif operation["kind"] == "upsert_slot":
                slot = copy.deepcopy(operation["slot"])
                draft["slots"][slot["id"]] = slot
            else:  # pragma: no cover - the loop emits only the two kinds above
                raise AssertionError(f"unexpected operation {operation['kind']}")
        return draft

    def preflight(self, scene: JsonObject) -> tuple[JsonObject, list[JsonObject]]:
        self.preflight_calls += 1
        return copy.deepcopy(scene), self.diagnose(scene)

    # -- the rules --------------------------------------------------------- #
    def diagnose(self, scene: JsonObject) -> list[JsonObject]:
        diagnostics: list[JsonObject] = []
        for node_id, node in sorted((scene.get("nodes") or {}).items()):
            kind = node.get("kind") or {}
            if kind.get("kind") != "text":
                continue
            severity = "warning" if node.get("position_mode") == "absolute" else "error"
            needed_w = len(kind.get("content") or "") * _CHAR_W
            width, height = node["size"]["width"], node["size"]["height"]
            if width.get("kind") == "fixed" and width["value"] < needed_w:
                diagnostics.append(
                    _diag("LUMV0902", severity, "node", node_id,
                          f"non-wrapping text node {node_id} overflows horizontally")
                )
            if width.get("kind") == "hug" and needed_w > self.parent_width:
                diagnostics.append(
                    _diag("LUMV0801", "error", "node", node_id,
                          f"node {node_id} exceeds parent bounds on page page_test")
                )
            if height.get("kind") == "fixed" and height["value"] < _LINE_H:
                diagnostics.append(
                    _diag("LUMV0903", severity, "node", node_id,
                          f"text node {node_id} exceeds available height")
                )

        for slot_id, slot in sorted((scene.get("slots") or {}).items()):
            validation = slot.get("validation") or {}
            # LUMV0509 counts ONLY fit-validation fixtures (validation.rs:545);
            # a placeholder does not satisfy it. The measured fixture SET
            # (layout.rs::slot_fixtures) does include the placeholder. Two
            # different questions — the fake keeps them apart, like the engine.
            if (
                not validation.get("samples")
                and not validation.get("worst_case")
                and validation.get("max_length") is None
            ):
                diagnostics.append(
                    _diag("LUMV0509", "warning", "slot", slot_id,
                          f"text slot {slot['key']} has no fit-validation fixtures")
                )
            fixtures = list(validation.get("samples") or [])
            if validation.get("worst_case"):
                fixtures.append(validation["worst_case"])
            if slot.get("placeholder"):
                fixtures.append(slot["placeholder"])
            for node_id in slot.get("bound_nodes") or []:
                node = (scene.get("nodes") or {}).get(node_id)
                if not node:
                    continue
                width = node["size"]["width"]
                box = width["value"] if width.get("kind") == "fixed" else float("inf")
                if any(len(fixture) * _CHAR_W > box for fixture in fixtures):
                    diagnostics.append(
                        _diag("LUMV0810", "error", "slot", slot_id,
                              f"slot {slot['key']} fixture overflows text node {node_id}")
                    )
        return diagnostics

    # -- convenience -------------------------------------------------------- #
    def run(self, *, max_passes: int = 2, **kwargs):
        return run_autofix(
            self.scene,
            self.diagnose(self.scene),
            apply_operations=self.apply_operations,
            preflight=self.preflight,
            max_passes=max_passes,
            **kwargs,
        )


def _codes(diagnostics: list[JsonObject]) -> list[str]:
    return sorted(str(d["code"]) for d in diagnostics)


# =========================================================================== #
# class 1 — text_box_hug
# =========================================================================== #
def test_text_overflow_is_repaired_without_a_model_call() -> None:
    """RED CASE. A too-short text box is a closed-form fix: hand the sizing back
    to the engine's own measurer and let it decide the number.

    This is the exact defect that used to cost a full orchestrator → reviewer →
    critique → author round in the baseline. No model is constructed anywhere in
    this test; the repair is pure code plus two engine calls.
    """
    engine = FakeEngine(
        {
            "nodes": {"headline": _text("headline", "Plan smarter", width=_fixed(40.0), height=_fixed(12.0))},
            "slots": {},
        }
    )
    assert _codes(engine.diagnose(engine.scene)) == ["LUMV0902", "LUMV0903"]

    result = engine.run()

    assert result.diagnostics == [], "the post-autofix scene must be preflight-clean"
    assert [r.klass for r in result.applied] == ["text_box_hug"]
    assert result.rolled_back == []
    # BOTH failing dimensions ride ONE patch: the operation carries a whole
    # SizeSpec, so two patches on one node in one pass would clobber each other.
    assert result.applied[0].codes == ("LUMV0902", "LUMV0903")
    assert result.scene["nodes"]["headline"]["size"] == {"width": _HUG, "height": _HUG}


def test_a_widen_that_breaks_the_parent_is_rolled_back() -> None:
    """ROLLBACK CASE. Hug is only correct if the result still fits its parent.

    The engine, not the planner, is what notices: the loop applies the patch to a
    COPY, re-preflights, sees a diagnostic key that was not there before, and
    keeps the original scene. The author gets the LUMV0902 it would have gotten
    anyway — plus the note that the mechanical fix was already tried, so it does
    not spend a call rediscovering that widening is not the answer here.
    """
    engine = FakeEngine(
        {
            "nodes": {"headline": _text("headline", "A headline far too wide", width=_fixed(40.0), height=_HUG)},
            "slots": {},
        },
        parent_width=100.0,
    )
    before = engine.diagnose(engine.scene)

    result = engine.run()

    assert result.applied == []
    assert result.diagnostics == before, "the original diagnostic must survive verbatim"
    assert result.scene["nodes"]["headline"]["size"]["width"] == _fixed(40.0)
    assert len(result.rolled_back) == 1
    assert "LUMV0801" in result.rolled_back[0].reason
    assert result.as_payload()["rolled_back"][0]["rolled_back_because"].startswith("introduced")


def test_a_freehand_overflow_is_the_humans_decision_and_is_left_alone() -> None:
    """The engine downgrades text-fit codes to *warning* on a freehand node
    because "a human resizing a pinned text box below its content is explicit
    intent" (layout.rs:1187-1197). Filtering on error severity inherits that
    ruling rather than re-deriving it — so a pinned box is never silently regrown.
    """
    engine = FakeEngine(
        {
            "nodes": {
                "pinned": _text(
                    "pinned", "Plan smarter", width=_fixed(40.0), height=_fixed(12.0),
                    position_mode="absolute",
                )
            },
            "slots": {},
        }
    )
    assert _codes(engine.diagnose(engine.scene)) == ["LUMV0902", "LUMV0903"]

    result = engine.run()

    assert not result.attempted
    assert engine.apply_calls == 0, "an untouchable node must cost no engine call"


@pytest.mark.parametrize(
    "dimension,why",
    [
        ({"kind": "hug"}, "already hug — the overflow means something else"),
        ({"kind": "token", "token": "$size.headline"}, "a brand binding must not be silently dropped"),
        ({"kind": "fill", "value": {"weight": 1.0}}, "fill is a stated layout intent, not a defect"),
    ],
)
def test_only_a_fixed_dimension_is_swappable(dimension: JsonObject, why: str) -> None:
    """The patch is closed-form only over `fixed`. Everything else is a decision."""
    scene = {
        "nodes": {"headline": _text("headline", "Plan smarter", width=dimension, height=_HUG)},
        "slots": {},
    }
    diagnostics = [_diag("LUMV0902", "error", "node", "headline")]
    assert plan_autofix(scene, diagnostics) == [], why


def test_a_locked_node_is_never_resized() -> None:
    scene = {
        "nodes": {
            "headline": _text("headline", "Plan smarter", width=_fixed(40.0), height=_HUG, locked=True)
        },
        "slots": {},
    }
    assert plan_autofix(scene, [_diag("LUMV0902", "error", "node", "headline")]) == []


# =========================================================================== #
# class 2 — slot_fixture
# =========================================================================== #
def test_a_fixtureless_slot_takes_the_sample_its_own_node_already_renders() -> None:
    """RED CASE. The fixture a slot is missing is a string, and the string the
    slot is FOR is sitting in the node it binds — no measurement, no invention.
    """
    engine = FakeEngine(
        {
            "nodes": {"headline": _text("headline", "Plan smarter", width=_fixed(400.0), height=_HUG)},
            "slots": {"slot_headline": _slot("slot_headline", "campaign.headline", bound=["headline"])},
        }
    )
    assert _codes(engine.diagnose(engine.scene)) == ["LUMV0509"]

    result = engine.run()

    assert result.diagnostics == []
    assert [r.klass for r in result.applied] == ["slot_fixture"]
    assert result.scene["slots"]["slot_headline"]["validation"]["samples"] == ["Plan smarter"]
    # `worst_case` is deliberately NOT written: the longest plausible content is
    # a content judgment, and this loop does not make those.
    assert result.scene["slots"]["slot_headline"]["validation"]["worst_case"] is None
    assert "Plan smarter" in result.applied[0].detail


def test_a_sample_that_would_overflow_its_own_node_is_rolled_back() -> None:
    """ROLLBACK CASE. Deriving the sample from live content is safe only while
    that content fits. When it does not, the sample turns into a fresh LUMV0810
    and the whole patch goes back — the slot keeps its honest LUMV0509.
    """
    engine = FakeEngine(
        {
            # width is a token, so the text_box_hug class cannot rescue this one
            # first; the slot fix is left to face the overflow alone.
            "nodes": {
                "headline": _text(
                    "headline", "A headline far too wide for its box",
                    width={"kind": "token", "token": "$size.col"}, height=_HUG,
                )
            },
            "slots": {"slot_headline": _slot("slot_headline", "campaign.headline", bound=["headline"])},
        }
    )
    # Make the bound box narrow in the engine's eyes without offering a fixed
    # dimension the other class could take.
    engine.scene["nodes"]["headline"]["size"]["width"] = _fixed(60.0)
    engine.scene["nodes"]["headline"]["locked"] = True
    before = engine.diagnose(engine.scene)
    assert _codes(before) == ["LUMV0509", "LUMV0902"]

    result = engine.run()

    assert result.applied == []
    assert result.diagnostics == before
    assert result.scene["slots"]["slot_headline"]["validation"]["samples"] == []
    assert "LUMV0810" in result.rolled_back[0].reason


def test_a_slot_with_no_derivable_content_is_left_for_the_author() -> None:
    """No bound text node, nothing to derive — and inventing copy is exactly the
    judgment call §5.4 keeps with the model."""
    scene = {
        "nodes": {"box": {"id": "box", "kind": {"kind": "rect"}, "size": {"width": _HUG, "height": _HUG}}},
        "slots": {"slot_x": _slot("slot_x", "campaign.headline", bound=["box"])},
    }
    assert plan_autofix(scene, [_diag("LUMV0509", "warning", "slot", "slot_x")]) == []

    empty = copy.deepcopy(scene)
    empty["nodes"]["box"] = _text("box", "   ", width=_HUG, height=_HUG)
    assert plan_autofix(empty, [_diag("LUMV0509", "warning", "slot", "slot_x")]) == []


@pytest.mark.parametrize(
    "validation",
    [
        {"samples": ["x"], "worst_case": None, "max_length": None},
        {"samples": [], "worst_case": "xxxx", "max_length": None},
        {"samples": [], "worst_case": None, "max_length": 40},
    ],
)
def test_a_slot_that_already_has_a_fit_fixture_is_left_alone(validation: JsonObject) -> None:
    """Any fit-validation fixture means the author has already said something
    about this slot's content, and this loop does not second-guess it."""
    scene = {
        "nodes": {"headline": _text("headline", "Plan smarter", width=_HUG, height=_HUG)},
        "slots": {"slot_h": _slot("slot_h", "campaign.headline", bound=["headline"],
                                  validation=validation)},
    }
    assert plan_autofix(scene, [_diag("LUMV0509", "warning", "slot", "slot_h")]) == []


def test_a_placeholder_blocks_lumv0800_but_not_lumv0509() -> None:
    """The two codes ask DIFFERENT questions, and conflating them silently
    disables the class on the only path that produces it.

    Live-proven against the real helper 2026-08-24: the DSL's `slot(key)`
    constructor sets `placeholder` to the bound node's own text, so every
    DSL-authored text slot arrives WITH a placeholder and WITH a LUMV0509
    (validation.rs:545 counts only samples/worst_case/validation.max_length —
    a placeholder is not a fit fixture). A union precondition declined every
    one of them. LUMV0800 is the other question — `slot_fixtures` empty — and
    a placeholder does answer it.
    """
    slot = _slot("slot_h", "campaign.headline", bound=["headline"],
                 placeholder="Plan smarter")
    scene = {
        "nodes": {"headline": _text("headline", "Plan smarter", width=_HUG, height=_HUG)},
        "slots": {"slot_h": slot},
    }

    on_0509 = plan_autofix(scene, [_diag("LUMV0509", "warning", "slot", "slot_h")])
    assert [p.klass for p in on_0509] == ["slot_fixture"]
    assert on_0509[0].operations[0]["slot"]["validation"]["samples"] == ["Plan smarter"]

    assert plan_autofix(scene, [_diag("LUMV0800", "error", "slot", "slot_h")]) == []

    # Both at once: only the code whose precondition holds is CLAIMED, because a
    # target the patch cannot clear would force the whole thing to roll back.
    both = plan_autofix(
        scene,
        [_diag("LUMV0509", "warning", "slot", "slot_h"),
         _diag("LUMV0800", "error", "slot", "slot_h")],
    )
    assert [p.codes for p in both] == [("LUMV0509",)]


def test_lumv0800_is_only_a_slot_fix_when_its_subject_is_a_slot() -> None:
    """LUMV0800 means two unrelated things ("required slot needs a fixture" AND
    "node exceeds exportable bounds"), and Python cannot tell them apart by code.
    The subject kind is the disambiguator — and moving a node back inside the
    artboard is emphatically not a closed-form fix.
    """
    scene = {
        "nodes": {"headline": _text("headline", "Plan smarter", width=_fixed(40.0), height=_HUG)},
        "slots": {"slot_h": _slot("slot_h", "campaign.headline", bound=["headline"])},
    }
    on_node = plan_autofix(scene, [_diag("LUMV0800", "error", "node", "headline")])
    assert [p.klass for p in on_node] == [], "the node-bounds meaning has no autofix"

    on_slot = plan_autofix(scene, [_diag("LUMV0800", "error", "slot", "slot_h")])
    assert [p.klass for p in on_slot] == ["slot_fixture"]


# =========================================================================== #
# scope — what this version deliberately does NOT fix
# =========================================================================== #
@pytest.mark.parametrize(
    "diagnostic",
    [
        # spec §5.4 candidate 3. `TokenFallbackPolicy::UseFallbacks` (brand.rs:1594)
        # is declared and never constructed, so preflight computes NO fallback
        # value for this loop to apply; choosing a substitute is a design choice.
        _diag("LUMB0201", "error", "node", "headline", "color token $x is not defined"),
        _diag("LUMB0401", "error", "node", "headline", "typography token $y is not defined"),
        # the engine reports that a fixture needs N lines but never how tall the
        # box would have to be, so any repair here is a guess from prose.
        _diag("LUMV0904", "error", "node", "headline", "text node headline exceeds max_lines"),
        _diag("LUMV0813", "error", "slot", "slot_h", "fixture needs 3 lines but max_lines is 2"),
    ],
)
def test_judgment_shaped_diagnostics_are_left_to_the_model(diagnostic: JsonObject) -> None:
    scene = {
        "nodes": {"headline": _text("headline", "Plan smarter", width=_fixed(40.0), height=_HUG)},
        "slots": {"slot_h": _slot("slot_h", "campaign.headline", bound=["headline"])},
    }
    assert plan_autofix(scene, [diagnostic]) == []


def test_the_shipped_and_excluded_class_lists_are_stated_in_code() -> None:
    """A future reader must be able to see WHY a spec-named class is missing
    without re-scouting the Rust engine."""
    assert SHIPPED_CLASSES == ("text_box_hug", "slot_fixture")
    assert "token_fallback" in EXCLUDED_CLASSES
    assert "UseFallbacks" in EXCLUDED_CLASSES["token_fallback"]


# =========================================================================== #
# the loop itself
# =========================================================================== #
def test_the_pass_cap_is_a_hard_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """BOUNDED PASSES. Termination normally comes from the no-progress exit and
    the never-retry-a-key rule; the cap is the last line of defence, so it is
    tested against a planner that would otherwise never stop offering work.
    """
    offered = {"n": 0}

    def endless(scene: JsonObject, diagnostics: list[JsonObject]) -> list[AutofixPatch]:
        offered["n"] += 1
        return [
            AutofixPatch(
                klass="text_box_hug",
                targets=((f"LUMV0903", "node", f"node_{offered['n']}"),),
                operations=({"kind": "update_node", "node_id": "headline",
                             "patch": {"clip": {"kind": "set", "value": False}}},),
                detail=f"synthetic patch {offered['n']}",
            )
        ]

    monkeypatch.setattr(autofix_mod, "plan_autofix", endless)
    engine = FakeEngine(
        {"nodes": {"headline": _text("headline", "ok", width=_HUG, height=_HUG)}, "slots": {}}
    )

    for cap in (1, 2, 5):
        offered["n"] = 0
        result = engine.run(max_passes=cap)
        assert result.passes == cap
        assert len(result.applied) == cap


def test_zero_passes_makes_no_engine_call_at_all() -> None:
    """`max_passes=0` is the in-band off switch the flag maps to."""
    engine = FakeEngine(
        {
            "nodes": {"headline": _text("headline", "Plan smarter", width=_fixed(40.0), height=_fixed(12.0))},
            "slots": {},
        }
    )
    result = engine.run(max_passes=0)
    assert not result.attempted
    assert (engine.apply_calls, engine.preflight_calls) == (0, 0)


def test_the_loop_stops_as_soon_as_a_pass_makes_no_progress() -> None:
    """A rejected patch is never retried, so an unfixable scene costs exactly one
    attempt — not one per allowed pass."""
    engine = FakeEngine(
        {
            "nodes": {"headline": _text("headline", "A headline far too wide", width=_fixed(40.0), height=_HUG)},
            "slots": {},
        },
        parent_width=100.0,
    )
    result = engine.run(max_passes=5)
    assert result.passes == 1
    assert (engine.apply_calls, engine.preflight_calls) == (1, 1)


def test_an_engine_that_refuses_costs_the_scene_nothing() -> None:
    """Autofix is an optimization. An engine error must degrade to "the author
    handles it", never to a lost scene or a failed turn."""
    scene = {
        "nodes": {"headline": _text("headline", "Plan smarter", width=_fixed(40.0), height=_fixed(12.0))},
        "slots": {},
    }
    engine = FakeEngine(scene)
    before = engine.diagnose(scene)

    def boom(*_args, **_kwargs):
        raise RuntimeError("helper exploded")

    result = run_autofix(
        scene, before, apply_operations=boom, preflight=engine.preflight, max_passes=2
    )
    assert result.scene is scene
    assert result.diagnostics == before
    assert result.rolled_back[0].reason == "engine refused the operation (RuntimeError)"


def test_both_classes_land_together_in_one_pass() -> None:
    """The real production shape, mirrored from a live helper run (2026-08-24).

    A DSL-authored slotted text node that overflows raises four diagnostics at
    once — LUMV0509 (no fit fixture), LUMV0902/0903 (the box), LUMV0810 (the
    placeholder fixture overflowing that same box). Against the real
    `lumen-api-helper` this loop cleared ALL FOUR in one pass with two engine
    calls per patch and zero model calls.

    Text boxes are planned before slots on purpose, and that ordering is what
    makes it one pass: a slot sample is measured against its bound box, so
    fixing the box first lets the sample land instead of being rolled back.
    """
    engine = FakeEngine(
        {
            "nodes": {
                "headline": _text("headline", "Plan smarter", width=_fixed(40.0), height=_fixed(12.0))
            },
            # the DSL's `slot(key)` constructor mirrors the node text into
            # `placeholder` and leaves `validation` empty — this exact shape
            # is what the union-precondition bug used to refuse
            "slots": {
                "slot_h": _slot("slot_h", "campaign.headline", bound=["headline"],
                                placeholder="Plan smarter")
            },
        }
    )
    assert _codes(engine.diagnose(engine.scene)) == [
        "LUMV0509", "LUMV0810", "LUMV0902", "LUMV0903"
    ]

    result = engine.run(max_passes=1)

    assert result.diagnostics == []
    assert [r.klass for r in result.applied] == ["text_box_hug", "slot_fixture"]
    assert result.counts_by_class() == {"text_box_hug": 1, "slot_fixture": 1}


def test_diagnostic_key_folds_code_and_subject() -> None:
    """The loop's whole set arithmetic rests on this key. A code alone is not an
    identity (LUMV0800 means three different things)."""
    assert diagnostic_key(_diag("LUMV0903", "error", "node", "a")) == ("LUMV0903", "node", "a")
    assert diagnostic_key({"code": "LUMP0300"}) == ("LUMP0300", "", "")


# =========================================================================== #
# the substrate seam — preflight_design
# =========================================================================== #
class _AutofixCore(FakeCoreClient):
    """A `CoreClient` whose preflight answers from the miniature engine, so the
    substrate test exercises the same derive-verify-or-roll-back path."""

    engine: Optional[FakeEngine] = None
    seed_scene: Optional[JsonObject] = None

    def __init__(self, repo_root) -> None:
        super().__init__(repo_root)
        self.engine = FakeEngine(copy.deepcopy(type(self).seed_scene or {}))
        self.preflight_calls = 0

    def preflight_scene(self, scene, brand_kit, brand_fonts=None):
        self.preflight_calls += 1
        diagnostics = self.engine.diagnose(scene)
        return {
            "scene": copy.deepcopy(scene),
            "diagnostics": diagnostics,
            "preflight": {
                "has_errors": any(d["severity"] == "error" for d in diagnostics),
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }

    def apply_operations(self, scene, operations, scope=None):
        self.applied_operations.extend(operations)
        return {
            "scene": self.engine.apply_operations(scene, list(operations)),
            "applied_operations": len(operations),
            "diagnostics": [],
        }


def _tools(tmp_path, monkeypatch, scene: JsonObject, **config_kwargs) -> LumenDesignTools:
    _AutofixCore.seed_scene = scene
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _AutofixCore)
    config = dataclasses.replace(runtime_config(tmp_path), **config_kwargs)
    tools = LumenDesignTools(config, "Make a LinkedIn ad")
    tools.scene = copy.deepcopy(scene)
    return tools


_OVERFLOWING = {
    "meta": {"id": "doc", "title": "t"},
    "pages": {},
    "nodes": {"headline": _text("headline", "Plan smarter", width=_fixed(40.0), height=_fixed(12.0))},
    "slots": {},
    "assets": {},
}


def test_flag_off_leaves_preflight_byte_identical(tmp_path, monkeypatch) -> None:
    """FLAG OFF. `LUMEN_AGENT_FAST_LOOP` down must be indistinguishable from the
    pre-fast-loop runtime: same payload keys, same engine traffic, no artifact,
    no counter."""
    tools = _tools(tmp_path, monkeypatch, _OVERFLOWING)
    assert tools.config.autofix_passes == 0

    payload = json.loads(tools.preflight_design())

    assert set(payload) == {"preflight", "raw_preflight", "effective_brand"}
    assert "autofix" not in payload
    assert not (tools.trace_dir / "iterations" / "001" / "autofix.json").exists()
    assert tools.core.preflight_calls == 1
    assert tools.core.applied_operations == []
    assert tools.metrics.snapshot()["autofix_count"] == 0
    assert [d["code"] for d in payload["preflight"]["diagnostics"]] == ["LUMV0902", "LUMV0903"]


def test_flag_on_hands_the_author_the_post_autofix_diagnostics(tmp_path, monkeypatch) -> None:
    """FLAG ON, red case at the real seam. The tool result the model reads is
    clean, the repair is on the ledger, and the trace says what moved."""
    tools = _tools(tmp_path, monkeypatch, _OVERFLOWING, fast_loop=True)

    payload = json.loads(tools.preflight_design())

    assert payload["preflight"]["diagnostics"] == []
    assert payload["preflight"]["has_errors"] is False
    assert tools.latest_preflight_has_errors is False
    assert payload["autofix"]["applied_count"] == 1
    assert payload["autofix"]["by_class"] == {"text_box_hug": 1}
    assert payload["autofix"]["applied"][0]["detail"].startswith("text node headline:")

    # the artifact §5.4 asks for, next to the round's other diagnostics
    written = json.loads((tools.trace_dir / "iterations" / "001" / "autofix.json").read_text())
    assert written == payload["autofix"]

    # committed: the working scene moved, and the operation is on the proposal
    # ledger the editor's Accept replays (an unlogged autofix would vanish there)
    assert tools.scene["nodes"]["headline"]["size"] == {"width": _HUG, "height": _HUG}
    sources = [entry["source"] for entry in tools.operations_ledger]
    assert sources == ["autofix"]
    assert tools.operations_ledger[0]["operation"]["kind"] == "update_node"

    assert tools.metrics.snapshot()["autofix_count"] == 1
    assert tools.metrics.snapshot()["autofix_by_class"] == {"text_box_hug": 1}


def test_a_rolled_back_autofix_shows_the_author_the_original_and_says_it_tried(
    tmp_path, monkeypatch
) -> None:
    """FLAG ON, rollback case at the real seam. Nothing is committed, the
    diagnostic is untouched, and the attempt is on the record so the author does
    not spend a call retrying the same mechanical repair."""
    scene = copy.deepcopy(_OVERFLOWING)
    scene["nodes"]["headline"] = _text(
        "headline", "A headline far too wide", width=_fixed(40.0), height=_HUG
    )
    tools = _tools(tmp_path, monkeypatch, scene, fast_loop=True)
    tools.core.engine.parent_width = 100.0

    payload = json.loads(tools.preflight_design())

    assert [d["code"] for d in payload["preflight"]["diagnostics"]] == ["LUMV0902"]
    assert payload["preflight"]["has_errors"] is True
    assert payload["autofix"]["applied_count"] == 0
    assert payload["autofix"]["rolled_back_count"] == 1
    assert "LUMV0801" in payload["autofix"]["rolled_back"][0]["rolled_back_because"]

    assert tools.scene["nodes"]["headline"]["size"]["width"] == _fixed(40.0)
    assert tools.operations_ledger == []
    snapshot = tools.metrics.snapshot()
    assert (snapshot["autofix_count"], snapshot["autofix_rolled_back"]) == (0, 1)


def test_autofix_never_fails_the_turn_at_the_substrate_seam(tmp_path, monkeypatch) -> None:
    """A crash inside the loop costs the optimization, never the preflight."""
    tools = _tools(tmp_path, monkeypatch, _OVERFLOWING, fast_loop=True)
    monkeypatch.setattr(
        "lumen_agent.tools.substrate.run_autofix",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("planner exploded")),
    )

    payload = json.loads(tools.preflight_design())

    assert "autofix" not in payload
    assert [d["code"] for d in payload["preflight"]["diagnostics"]] == ["LUMV0902", "LUMV0903"]
    events = [
        json.loads(line)["event"]
        for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert "autofix_failed" in events
