"""The W3 composition corpus, proven against the REAL engine.

Brand Ad Assets v1 §5 W3 added six worked examples to the block catalog — four
snippets (card-on-a-ground, pill chip, framed plate, zone rule) and two
full-artboard skeletons (unequal-weight comparison panel, card on a washed
ground). They exist because the reference-ad pilots showed the design agent
reliably failing at MULTI-BOX composition: it had never been shown a card with a
shadow, a hug-sized pill, or a plate-on-washed-ground as *validated, copyable*
DSL, so it invented the geometry every run and the geometry was wrong.

A corpus teaches by worked example, which makes its honesty load-bearing in a way
prose is not: the agent copies these blocks verbatim. So this suite does not
check that the docs *say* the right things — the anti-phantom guard in
`apps/agent_runtime/tests/test_composition_corpus_docs.py` does that. This suite
lifts each fenced `text` block straight out of the markdown and puts it through
the real `CoreClient` — `compile_dsl_into_scene` then `preflight_scene` against
the platform-default Brand Kit — which is the exact mechanism every pre-existing
block in `knowledge/design/blocks/` was vetted with (`.context/p02-validate.py`).
A block that has not passed the engine does not ship.

Three things are asserted per block, not one:

1. it COMPILES with no error/blocker diagnostic and no `halted_at`;
2. it PREFLIGHTS clean against the platform-default kit;
3. the `Validator proof` JSON the doc PUBLISHES is the answer the engine
   actually gives — same `ok`, same `stage`, same warning set. A stale published
   proof is the failure mode that lets a block rot silently while still looking
   vetted.

Two blocks additionally make a claim about SOLVED GEOMETRY rather than about
validity, and prose cannot hold those honest, so they are pinned to
`layout_geometry`: the comparison skeleton's 300/780 structural split, and the
pill chip's hug width. And `test_a_corrupted_block_fails_validation` is the red
case — it proves this harness has teeth by breaking a shipped block and watching
the same code path reject it.

`LUMB0613`/`LUMB0614` (platform font not embeddable/subsettable) are
environmental and never fail a block, which is why they appear in the published
proofs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from lumen_api.core import CoreClient

DESIGN_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DOCS = DESIGN_ROOT / "apps" / "agent_runtime" / "knowledge_docs"
BLOCKS = KNOWLEDGE_DOCS / "knowledge" / "design" / "blocks"


@dataclass(frozen=True)
class CorpusBlock:
    """One `## <heading>` section of a block-catalog doc, and its DSL."""

    doc: str
    heading: str
    page_id: str

    @property
    def path(self) -> Path:
        return BLOCKS / self.doc

    def section(self) -> str:
        return _section(self.path, self.heading)

    def dsl(self) -> str:
        fences = re.findall(r"```text\n(.*?)```", self.section(), re.S)
        assert len(fences) == 1, (
            f"{self.heading} has {len(fences)} fenced `text` blocks, expected exactly one — "
            "the extractor and the reviewer both read one block per section"
        )
        return fences[0]

    def published_proof(self) -> dict[str, Any]:
        fences = re.findall(r"```json\n(.*?)```", self.section(), re.S)
        assert len(fences) == 1, f"{self.heading} does not publish exactly one validator proof"
        return json.loads(fences[0])


# The W3 wave, in the order a reader meets them. `page_id` is the DSL's own page
# line, kept here so a section silently swapped for a different block is caught.
W3_BLOCKS = (
    CorpusBlock("data-display.md", "Card on a ground (elevated plate)", "card_on_ground"),
    CorpusBlock("data-display.md", "Framed plate (a document inside a card)", "framed_plate"),
    CorpusBlock("actions.md", "Pill chip (hug-sized, fully rounded)", "pill_chip"),
    CorpusBlock(
        "layout.md",
        "Divider — zone rule inside a card (weight and inset)",
        "zone_divider",
    ),
    CorpusBlock(
        "patterns.md",
        "Unequal-weight comparison panel — before/after with a structural winner (1080×1080)",
        "unequal_compare",
    ),
    CorpusBlock(
        "patterns.md",
        "Card on a washed ground — the layer stack (1080×1080)",
        "card_on_wash",
    ),
)

every_w3_block = pytest.mark.parametrize(
    "block", W3_BLOCKS, ids=[b.page_id for b in W3_BLOCKS]
)


def _section(path: Path, heading: str) -> str:
    """The text from `## <heading>` up to the next `## ` (or EOF)."""

    text = path.read_text(encoding="utf-8")
    marker = f"\n## {heading}\n"
    start = text.find(marker)
    assert start != -1, f"{path.name} has no section `## {heading}`"
    rest = text[start + len(marker) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _validate(dsl: str) -> dict[str, Any]:
    """Compile + preflight through the real engine.

    Deliberately the same two-stage shape as `.context/p02-validate.py`, the
    script every published `Validator proof` in this catalog was produced with —
    if the two ever disagree, the proofs stop meaning what they say.
    """

    client = CoreClient()
    scene = client.new_scene("w3_corpus", "vet")
    compiled = client.compile_dsl_into_scene(scene, dsl)
    output = (compiled.get("dsl") or {}).get("compile_output") or {}
    diagnostics = output.get("diagnostics") or []
    fatal = [d for d in diagnostics if d and d.get("severity") in ("error", "blocker")]
    if output.get("halted_at") or fatal:
        return {
            "ok": False,
            "stage": "compile",
            "halted_at": output.get("halted_at"),
            "errors": [
                {"code": d.get("code"), "message": d.get("message"), "line": d.get("line")}
                for d in fatal
            ],
            "warnings": [],
        }

    preflight = client.preflight_scene(compiled["scene"], client.platform_default_brand_kit())
    diagnostics = preflight.get("diagnostics") or []
    return {
        "ok": not any(d.get("severity") in ("error", "blocker") for d in diagnostics),
        "stage": "preflight",
        "errors": [
            {
                "code": d.get("code"),
                "message": d.get("message"),
                "node": d.get("target_node_id"),
                "slot": d.get("target_slot_id"),
            }
            for d in diagnostics
            if d.get("severity") in ("error", "blocker")
        ],
        "warnings": [d.get("code") for d in diagnostics if d.get("severity") == "warning"],
    }


def _geometry(dsl: str) -> dict[str, Any]:
    client = CoreClient()
    scene = client.new_scene("w3_corpus_geo", "geo")
    compiled = client.compile_dsl_into_scene(scene, dsl)
    return client.layout_geometry(compiled["scene"])["geometry"]


def _box(geometry: dict[str, Any], node: str) -> dict[str, float]:
    assert node in geometry, f"no node `{node}` in the solved scene"
    return geometry[node]["layout_bounds"]


# ============================================================================
# 1. Every W3 block compiles and preflights clean against the real engine
# ============================================================================


@every_w3_block
def test_the_block_is_a_single_self_contained_page(block: CorpusBlock) -> None:
    """Each catalog block is one whole document — a `page`, one clipped root
    `artboard`, the block, and its `#slot:` fixture lines. A fragment could not be
    validated at all, so the extraction contract is asserted before the engine
    call, where the failure is readable."""

    dsl = block.dsl()

    assert dsl.startswith(f"page {block.page_id} "), dsl.splitlines()[0]
    assert "artboard" in dsl
    assert "clip(true)" in dsl


@every_w3_block
def test_the_block_compiles_and_preflights_clean(block: CorpusBlock) -> None:
    result = _validate(block.dsl())

    assert result["ok"] is True, f"{block.heading} does not validate: {result['errors']}"
    assert result["stage"] == "preflight"
    assert result["errors"] == []


@every_w3_block
def test_the_published_validator_proof_is_the_engine_s_actual_answer(
    block: CorpusBlock,
) -> None:
    """The proof block in the doc is a claim about this engine. Left unchecked it
    is the one part of a block that can rot without anything looking broken — the
    DSL still compiles, the doc still says `ok: true`, and the warning list quietly
    stops being true."""

    published = block.published_proof()
    actual = _validate(block.dsl())

    assert published["ok"] == actual["ok"]
    assert published["stage"] == actual["stage"]
    assert published["errors"] == actual["errors"] == []
    assert sorted(set(published["warnings"])) == sorted(set(actual["warnings"])), (
        f"{block.heading} publishes warnings {published['warnings']} "
        f"but the engine reports {sorted(set(actual['warnings']))}"
    )


@every_w3_block
def test_no_block_hardcodes_a_brand_colour(block: CorpusBlock) -> None:
    """Fills and text colours are token roles, never hex. The ONE exemption is the
    shadow/scrim colour: the Brand Kit's `shadows` token group is empty on the
    platform default, so there is no role to reference — those use a neutral
    `#000000` ink (and `#00000000`, the transparent stop, for which there is no
    `$transparent` token either). Any OTHER hex in a W3 block would be a brand
    colour baked into the corpus, which is exactly what a kit-driven pipeline
    cannot afford."""

    dsl = block.dsl()
    hexes = set(re.findall(r"#[0-9a-fA-F]{6,8}", dsl))

    assert hexes <= {"#000000", "#00000000"}, f"{block.heading} hardcodes {sorted(hexes)}"
    for line in dsl.splitlines():
        found = set(re.findall(r"#[0-9a-fA-F]{6,8}", line))
        if "#000000" in found:
            assert "shadow(" in line, f"opaque neutral outside a shadow: {line.strip()}"
        if "#00000000" in found:
            assert "stop(" in line, f"transparent stop outside a gradient: {line.strip()}"


# ============================================================================
# 2. The two geometry claims — pinned to the solver, not to prose
# ============================================================================


def test_the_comparison_skeleton_splits_the_canvas_unequally_by_construction() -> None:
    """The whole point of the skeleton: `before` is a FIXED 300 and `after` is
    `fill`, so `after` absorbs every remaining point and the solve is 300/780. The
    doc claims those numbers; here they come from the solver. If someone "tidies"
    the field to a fixed height, the panels become editable to equal — the named
    failure mode — and this fails."""

    block = next(b for b in W3_BLOCKS if b.page_id == "unequal_compare")
    geometry = _geometry(block.dsl())

    before, after = _box(geometry, "before"), _box(geometry, "after")

    assert before["height"] == 300.0
    assert after["height"] == 780.0
    assert before["height"] + after["height"] == 1080.0
    # The claim is dominance, not two magic numbers: the field must win outright.
    assert after["height"] > 2 * before["height"]
    # …and it wins because it is `fill`, so it starts where the band ends.
    assert after["y"] == before["height"]
    assert "s(1080,fill)" in block.dsl()

    # The doc states the same split in words; keep the two from drifting apart.
    assert "300 / 780" in block.section()


def test_the_pill_chip_really_hugs_its_label() -> None:
    """`s(hug,hug)` on the FRAME plus a definite-width label is the idiom, and the
    arithmetic the doc publishes (260 + 24 + 24 = 308) is a solver fact. Only the
    WIDTH is asserted: `layout_geometry` runs without the kit attached, so text
    heights there are not the branded heights and asserting one would pin a number
    that means nothing."""

    block = next(b for b in W3_BLOCKS if b.page_id == "pill_chip")
    geometry = _geometry(block.dsl())

    chip, label = _box(geometry, "chip"), _box(geometry, "chip_text")

    assert label["width"] == 260.0
    assert chip["width"] == 308.0  # 260 + pad(12,24) on both sides
    assert chip["width"] == label["width"] + 48.0
    assert "s(hug,hug)" in block.dsl()
    assert "308" in block.section()


def test_the_zone_rule_is_inset_to_the_card_and_shares_the_copy_s_left_edge() -> None:
    """The snippet's whole teaching point is the INSET: `s(fill,1)` as a direct
    child of the card spans the card's CONTENT width (888 − 2×56 = 776) and starts
    on the same left edge as the copy. Hung off the artboard instead, it would run
    888 wide and read as a band across the ad."""

    block = next(b for b in W3_BLOCKS if b.page_id == "zone_divider")
    geometry = _geometry(block.dsl())

    card = _box(geometry, "card")
    rule = _box(geometry, "zone_rule")
    message = _box(geometry, "message")

    assert card["width"] == 888.0
    assert rule["width"] == 776.0 == card["width"] - 2 * 56
    assert rule["x"] == message["x"], "the rule and the copy do not share a left edge"
    assert rule["height"] == 1.0, "the hairline weight is the literal 1 in s(fill,1)"
    assert "776" in block.section()


def test_the_framed_plate_keeps_a_real_margin_on_every_side_of_the_panel() -> None:
    """A frame is a frame only while the margin survives. The doc publishes
    `720 − 2×40 = 640`; here the solver confirms the panel is inset 40pt from the
    plate on both sides, so a future edit that grows the panel to the card edge
    fails instead of quietly turning the frame into a crop."""

    block = next(b for b in W3_BLOCKS if b.page_id == "framed_plate")
    geometry = _geometry(block.dsl())

    plate, panel = _box(geometry, "plate"), _box(geometry, "panel")

    assert (plate["width"], plate["height"]) == (720.0, 880.0)
    assert panel["width"] == 640.0 == plate["width"] - 2 * 40
    assert panel["x"] - plate["x"] == 40.0
    assert panel["y"] - plate["y"] == 40.0
    # Fixed, not hug: the frame proportion is the design decision.
    assert "s(720,880)" in block.dsl()


# ============================================================================
# 3. The red case — this harness can actually fail
# ============================================================================


def test_a_corrupted_block_fails_validation() -> None:
    """A green suite full of passing blocks proves nothing unless the same path
    rejects a broken one. Two corruptions, at both stages:

    - a phantom token (`$surface.nonexistent`) — the class of defect the corpus
      exists to prevent, since the agent copies a token it sees here;
    - copy far past the block's stated budget in a fixed-width slot, which is the
      `LUMV0810` overflow the whole catalog is calibrated against.
    """

    block = next(b for b in W3_BLOCKS if b.page_id == "card_on_ground")
    dsl = block.dsl()

    assert _validate(dsl)["ok"] is True, "the shipped block must be the green baseline"

    phantom = dsl.replace("fill($surface.card)", "fill($surface.nonexistent)")
    assert phantom != dsl
    phantom_result = _validate(phantom)
    assert phantom_result["ok"] is False, "a phantom token passed validation"

    overflowing = dsl.replace(
        '"Close the quarter with fewer tools."',
        '"Close the quarter with fewer tools and finally give your revenue team back '
        'the four days a month they currently spend reconciling four disconnected '
        'systems by hand before anyone can even open the board deck."',
    )
    assert overflowing != dsl
    overflow_result = _validate(overflowing)
    assert overflow_result["ok"] is False, "an overflowing headline passed validation"
    assert any(error["code"] for error in overflow_result["errors"])
