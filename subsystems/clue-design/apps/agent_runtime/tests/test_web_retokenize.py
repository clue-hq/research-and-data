"""G5 — the web-lane geometry retokenizer.

The scene lane proved the shape (`test_retokenize.py`): a raw literal that
EQUALS a kit token's value is rebound to the token, deterministically, on the
agent's own unseeded draft only. This is the web twin, and the equality is the
whole contract — a rebind is a pure RENAMING, so the rendered pixels are
byte-identical before and after and the page merely starts following the kit
PIN instead of a frozen number.

Two layers, on purpose:

* the pure pass (`build_web_retokenize_operations`) against a resolved geometry
  map — exactness, ties, variants, arbitrary values, determinism;
* the hook (`LumenWebTools`) against the REAL core helper — the guards, the
  ledger, invertibility, the failure posture, and the trace line.

Note the topology deliberately NOT copied from the scene suite: that module
imports the FROZEN ARCHIVE copy of the pass. This one imports the live module.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import LumenWebTools
from lumen_agent.web_retokenize import (
    REM_PX,
    SPACING_STEP_REM,
    STOCK_RADIUS_PX,
    STOCK_RADIUS_REM,
    build_web_retokenize_operations,
    summarize_class_pairs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TAILWIND_THEME_CSS = (
    REPO_ROOT / "apps" / "editor" / "node_modules" / "tailwindcss" / "theme.css"
)


# --- fixtures ---------------------------------------------------------------


def _geometry(**overrides: str) -> dict[str, str]:
    """A resolved geometry map in the exact shape G1's FFI hands Python:
    utility CSS-var name → CSS value. These are the values the helper really
    produces for the kit `_kit()` builds below (asserted in
    `test_the_fixture_geometry_map_is_what_the_helper_really_compiles`)."""
    geometry = {
        "radius-button": "10px",
        "radius-card": "16px",
        "radius-badge": "999px",
        "shadow-brand": "0 2px 8px 0 #00000014",
        "shadow-card": "0 2px 8px 0 #00000014",
        "border-width-card": "1px",
        "border-width-divider": "1px",
        "spacing-section": "96px",
        "spacing-stack": "16px",
        "spacing-card": "24px",
    }
    geometry.update(overrides)
    return geometry


def _doc(*class_strings: str) -> dict:
    """The structural subset of a WebDoc the pure pass reads. The helper-backed
    tests below run against real documents; this keeps the pure cases legible."""
    return {
        "pages": [
            {
                "id": "home",
                "nodes": {
                    f"n{index}": {"id": f"n{index}", "classes": value}
                    for index, value in enumerate(class_strings)
                },
            }
        ]
    }


def _classes(operations: list[dict]) -> list[str]:
    return [op["classes"] for op in operations]


# --- 1. exact match rebinds -------------------------------------------------


def test_a_raw_step_equal_to_the_kit_radius_is_rebound() -> None:
    geometry = _geometry()
    # The equality that licenses the swap, stated out loud: the kit's card
    # radius and Tailwind's `rounded-2xl` are the SAME 16 pixels.
    assert geometry["radius-card"] == "16px"
    assert STOCK_RADIUS_PX["rounded-2xl"] == "16"

    operations = build_web_retokenize_operations(
        _doc("rounded-2xl bg-card px-6 flex items-center"), geometry
    )
    assert operations == [
        {
            "kind": "set_node_classes",
            "page_id": "home",
            "id": "n0",
            "classes": "rounded-card bg-card px-6 flex items-center",
        }
    ]
    # Every other token is byte-identical and in its original position.
    before = "rounded-2xl bg-card px-6 flex items-center".split()
    after = operations[0]["classes"].split()
    assert len(before) == len(after)
    assert [b for b, a in zip(before, after) if b != a] == ["rounded-2xl"]


def test_each_spacing_axis_rebinds_to_its_own_single_candidate() -> None:
    geometry = _geometry()
    operations = build_web_retokenize_operations(
        _doc("py-24 p-6 gap-4 mx-auto"), geometry
    )
    assert _classes(operations) == ["py-section p-card gap-stack mx-auto"]


def test_a_spacing_axis_never_reads_another_axis_value() -> None:
    """`p-24` is 96px — the SECTION rhythm — but `p-` is the card-padding axis
    and 96 != 24, so nothing moves. Cross-axis borrowing would silently change
    padding on a live page."""
    assert build_web_retokenize_operations(_doc("p-24"), _geometry()) == []


def test_neighbouring_spacing_utilities_are_not_mistaken_for_the_axis() -> None:
    """`px-`/`pt-`/`pb-`/`gap-x-` share a prefix with the ruled axes and must be
    left alone even when their value matches."""
    unchanged = "px-6 pt-6 pb-6 ps-6 gap-x-4 gap-y-4 mt-24"
    assert build_web_retokenize_operations(_doc(unchanged), _geometry()) == []


# --- 2. ties skip -----------------------------------------------------------


def test_a_tie_between_two_radius_utilities_leaves_the_raw_class_alone() -> None:
    """No nearest-match, no first-wins: an ambiguous rename is a decision the
    pass is not entitled to make."""
    tied = _geometry(**{"radius-button": "16px", "radius-card": "16px"})
    assert build_web_retokenize_operations(_doc("rounded-2xl"), tied) == []


def test_a_three_way_radius_tie_also_skips() -> None:
    tied = _geometry(
        **{"radius-button": "16px", "radius-card": "16px", "radius-badge": "16px"}
    )
    assert build_web_retokenize_operations(_doc("rounded-2xl"), tied) == []


# --- 3. no match skips ------------------------------------------------------


def test_a_step_that_equals_no_utility_stays_exactly_as_authored() -> None:
    near = _geometry(**{"radius-card": "6px"})
    # 8px (rounded-lg) against 10 / 6 / 999 — close is not equal.
    assert build_web_retokenize_operations(_doc("rounded-lg"), near) == []


def test_the_already_bound_utility_and_unknown_classes_are_untouched() -> None:
    doc = _doc("rounded-card p-card gap-stack py-section shadow-brand blob-9 rounded")
    # `rounded` is 4px and equals nothing in this map, so the whole string is
    # unchanged — including the four utilities that are already bound.
    assert build_web_retokenize_operations(doc, _geometry()) == []


def test_side_and_corner_radius_variants_are_never_rebound() -> None:
    """`rounded-t-2xl` is a partial shape; the kit's utilities are all-corner.
    Rewriting one to `rounded-card` would round corners that were square."""
    doc = _doc("rounded-t-2xl rounded-tl-2xl rounded-s-2xl rounded-e-[16px]")
    assert build_web_retokenize_operations(doc, _geometry()) == []


def test_rounded_full_is_outside_the_table() -> None:
    """Tailwind v4 compiles `rounded-full` to `calc(infinity * 1px)`, which is
    not byte-equal to any measured px radius — not even a 999px badge."""
    assert "rounded-full" not in STOCK_RADIUS_PX
    assert build_web_retokenize_operations(_doc("rounded-full"), _geometry()) == []


def test_shadows_and_border_widths_are_excluded_axes() -> None:
    doc = _doc("shadow-lg border-2 border")
    assert build_web_retokenize_operations(doc, _geometry()) == []


# --- 4. variant prefixes ride untouched -------------------------------------


def test_a_breakpoint_variant_is_preserved_and_only_the_base_changes() -> None:
    operations = build_web_retokenize_operations(
        _doc("rounded-lg md:rounded-2xl"), _geometry()
    )
    assert _classes(operations) == ["rounded-lg md:rounded-card"]


def test_stacked_variants_ride_untouched() -> None:
    operations = build_web_retokenize_operations(
        _doc("hover:md:rounded-2xl lg:py-24"), _geometry()
    )
    assert _classes(operations) == ["hover:md:rounded-card lg:py-section"]


# --- 5. arbitrary values ----------------------------------------------------


def test_an_arbitrary_radius_equal_to_the_kit_value_is_rebound() -> None:
    operations = build_web_retokenize_operations(_doc("rounded-[16px]"), _geometry())
    assert _classes(operations) == ["rounded-card"]


def test_an_arbitrary_section_rhythm_is_rebound() -> None:
    operations = build_web_retokenize_operations(_doc("py-[96px]"), _geometry())
    assert _classes(operations) == ["py-section"]


def test_an_arbitrary_value_in_another_unit_is_left_alone() -> None:
    """`rounded-[1rem]` renders the same 16px, but the pass compares CSS values
    after unit normalization of PX only — it does not reason about rem."""
    assert build_web_retokenize_operations(_doc("rounded-[1rem]"), _geometry()) == []


def test_a_decimal_arbitrary_value_matches_a_decimal_kit_value() -> None:
    geometry = _geometry(**{"radius-card": "6.5px"})
    operations = build_web_retokenize_operations(_doc("rounded-[6.50px]"), geometry)
    assert _classes(operations) == ["rounded-card"]


# --- purity / determinism ---------------------------------------------------


def test_the_pass_never_mutates_the_document_it_reads() -> None:
    doc = _doc("rounded-2xl", "py-24")
    before = copy.deepcopy(doc)
    build_web_retokenize_operations(doc, _geometry())
    assert doc == before


def test_the_operation_order_follows_pages_then_nodes_in_stored_order() -> None:
    doc = {
        "pages": [
            {
                "id": "home",
                "nodes": {
                    "b": {"classes": "rounded-2xl"},
                    "a": {"classes": "py-24"},
                },
            },
            {"id": "about", "nodes": {"c": {"classes": "gap-4"}}},
        ]
    }
    operations = build_web_retokenize_operations(doc, _geometry())
    assert [(op["page_id"], op["id"]) for op in operations] == [
        ("home", "b"),
        ("home", "a"),
        ("about", "c"),
    ]
    assert build_web_retokenize_operations(doc, _geometry()) == operations


def test_a_geometry_map_with_no_usable_values_produces_nothing() -> None:
    assert build_web_retokenize_operations(_doc("rounded-2xl py-24"), {}) == []
    broken = {"radius-card": "clamp(1rem, 2vw, 2rem)", "spacing-section": ""}
    assert build_web_retokenize_operations(_doc("rounded-2xl py-24"), broken) == []


def test_the_class_pair_summary_names_the_swap() -> None:
    doc = _doc("rounded-2xl", "rounded-2xl md:py-24")
    operations = build_web_retokenize_operations(doc, _geometry())
    assert summarize_class_pairs(doc, operations) == [
        "rounded-2xl→rounded-card ×2",
        "md:py-24→md:py-section ×1",
    ]


# --- 12. the stock table cannot silently drift ------------------------------


def _theme_css_vars() -> dict[str, str]:
    """`--name: value;` pairs from the installed Tailwind theme."""
    source = TAILWIND_THEME_CSS.read_text(encoding="utf-8")
    return dict(re.findall(r"^\s*--([a-z0-9-]+):\s*([^;]+);", source, flags=re.M))


def test_the_drift_guard_can_actually_read_the_installed_theme() -> None:
    """Guard the guard: a parse that matched nothing would make the drift check
    below vacuously green while the table rotted."""
    assert TAILWIND_THEME_CSS.is_file(), (
        f"{TAILWIND_THEME_CSS} is missing — run `npm install` under apps/editor"
    )
    variables = _theme_css_vars()
    assert variables.get("spacing") == "0.25rem"
    assert len([name for name in variables if name.startswith("radius-")]) >= 8


def test_the_stock_radius_table_matches_the_installed_tailwind_theme() -> None:
    """A Tailwind upgrade that moves a step must fail HERE, loudly, instead of
    silently rebinding `rounded-2xl` to a radius it no longer renders."""
    variables = _theme_css_vars()
    for utility, rem in STOCK_RADIUS_REM.items():
        variable = "radius" if utility == "rounded" else utility.replace("rounded-", "radius-")
        assert variables.get(variable) == f"{rem}rem", (
            f"{utility}: the theme says --{variable}: {variables.get(variable)!r}, "
            f"the table says {rem}rem"
        )
        assert STOCK_RADIUS_PX[utility] == str(
            (Decimal(rem) * REM_PX).normalize()
        ), utility


def test_the_spacing_step_matches_the_installed_tailwind_theme() -> None:
    assert _theme_css_vars().get("spacing") == f"{SPACING_STEP_REM}rem"


# --- the hook, against the real core helper ---------------------------------


def _measured(value: float, role: str) -> dict:
    """A measured px token in the engine's own shape."""
    return {
        "description": "G5 fixture",
        "provenance": {"confidence": 1.0, "source": "website:https://g5.test"},
        "role": role,
        "value": {
            "default": {"kind": "number", "unit": "px", "value": float(value)},
            "modes": {},
        },
    }


def _kit() -> dict:
    """A kit whose measured shape lands exactly on `_geometry()`: a 16px card
    radius (== `rounded-2xl`) and a 96px section rhythm (== `py-24`); the other
    eight utilities fall through to their platform constants.

    Built on the real platform kit so it satisfies the engine's whole BrandKit
    schema — a hand-rolled dict is rejected at `parse_brand_kit`, which would
    make every helper-backed case below a plumbing failure instead of a
    behavioural one."""
    from lumen_api.core import CoreClient

    kit = CoreClient(repo_root=REPO_ROOT).platform_default_brand_kit()
    kit["id"] = "brand_kit_g5"
    kit["name"] = "G5"
    kit["tokens"].setdefault("radii", {})["radius.card"] = _measured(16, "radius")
    kit["tokens"].setdefault("spacing", {})["space.section"] = _measured(96, "spacing")
    return kit


RAW_HTML = """
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col gap-6">
    <h1 data-variant="display">Ship faster</h1>
    <div id="hero_card" class="bg-card rounded-2xl px-6 md:rounded-2xl">
      <p data-variant="small">A card with a raw radius.</p>
    </div>
  </div>
</section>
"""


def _config(tmp_path: Path, *, kit: dict | None, source: str | None):
    return replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        brand_kit=kit,
        brand_kit_source=source,
    )


def _empty_doc(document_id: str = "doc_g5") -> dict:
    from lumen_api.core import CoreClient

    return CoreClient(repo_root=REPO_ROOT).web_new_doc(document_id, "G5 site", None)[
        "web_doc"
    ]


def _authored_doc(config, html: str = RAW_HTML) -> dict:
    """A document the AGENT authored this turn (so the tools built on it are
    unseeded), produced by the real ingest path."""
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    doc = core.web_new_doc("doc_g5_seeded", "G5 site", None)["web_doc"]
    return core.web_ingest_html(doc, "home", html, None, config.brand_kit)["web_doc"]


def _unseeded_tools(tmp_path: Path, *, kit=None, source="document") -> LumenWebTools:
    config = _config(tmp_path, kit=kit if kit is not None else _kit(), source=source)
    tools = LumenWebTools(config, "Build a page", initial_web_doc=_empty_doc())
    result = json.loads(tools.author_web_page(RAW_HTML))
    assert result["status"] == "ok", result
    return tools


def _trace_events(tools: LumenWebTools) -> list[dict]:
    path = tools.trace_dir / "trace.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _all_classes(doc: dict) -> list[str]:
    return [
        node.get("classes", "")
        for page in doc.get("pages") or []
        for node in (page.get("nodes") or {}).values()
    ]


def test_the_fixture_geometry_map_is_what_the_helper_really_compiles(tmp_path) -> None:
    """The pure tests above are only worth anything if the map they use is the
    map G1's FFI actually hands Python for this kit."""
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    response = core.web_validate(_empty_doc(), _kit())
    assert response["web_theme"]["geometry"] == _geometry()


def test_an_unseeded_briefed_turn_rebinds_before_the_reviewer_ever_looks(
    tmp_path,
) -> None:
    """The pass is wired at the START of render_web_preview: even a render that
    dies at the helper leaves the document rebound."""
    from lumen_api.core import CoreError

    tools = _unseeded_tools(tmp_path)
    assert any("rounded-2xl" in value for value in _all_classes(tools.web_doc))

    def _boom(*args, **kwargs):
        raise CoreError("helper.dead", "no renderer in this test")

    tools.core.web_render = _boom  # type: ignore[method-assign]
    result = json.loads(tools.render_web_preview())
    assert result["status"] == "error"

    classes = _all_classes(tools.web_doc)
    assert not any("rounded-2xl" in value for value in classes)
    assert any("rounded-card" in value for value in classes)
    assert any("py-section" in value for value in classes)
    # The rebind is a renaming, not a rewrite: nothing else moved.
    assert any("mx-auto max-w-[1200px] px-6 py-section flex flex-col gap-6" == value
               for value in classes)


def test_a_seeded_document_is_never_retokenized(tmp_path) -> None:
    """Resolution-once: an existing page's classes are a human's or an earlier
    turn's decision."""
    config = _config(tmp_path, kit=_kit(), source="document")
    seeded = _authored_doc(config)
    tools = LumenWebTools(config, "Change the headline", initial_web_doc=seeded)
    assert tools.seeded_from_initial_content is True

    before = copy.deepcopy(tools.web_doc)
    tools._retokenize_geometry()
    assert tools.web_doc == before
    assert tools.operations_ledger == []
    assert not [e for e in _trace_events(tools) if e["event"] == "web_geometry_retokenized"]


def test_an_unseeded_turn_is_flagged_unseeded(tmp_path) -> None:
    config = _config(tmp_path, kit=_kit(), source="document")
    tools = LumenWebTools(config, "Build a page", initial_web_doc=_empty_doc())
    assert tools.seeded_from_initial_content is False


@pytest.mark.parametrize("source", [None, "platform_default"])
def test_a_platform_default_kit_is_never_retokenized(tmp_path, source) -> None:
    tools = _unseeded_tools(tmp_path, kit=_kit(), source=source)
    ledger_before = len(tools.operations_ledger)
    before = copy.deepcopy(tools.web_doc)
    tools._retokenize_geometry()
    assert tools.web_doc == before
    assert len(tools.operations_ledger) == ledger_before


def test_no_kit_at_all_is_never_retokenized(tmp_path) -> None:
    config = _config(tmp_path, kit=None, source="document")
    tools = LumenWebTools(config, "Build a page", initial_web_doc=_empty_doc())
    assert json.loads(tools.author_web_page(RAW_HTML))["status"] == "ok"
    before = copy.deepcopy(tools.web_doc)
    tools._retokenize_geometry()
    assert tools.web_doc == before


def test_the_second_pass_over_a_rebound_document_finds_nothing(tmp_path) -> None:
    tools = _unseeded_tools(tmp_path)
    tools._retokenize_geometry()
    ledger = len(tools.operations_ledger)
    version = tools._doc_version
    after_first = copy.deepcopy(tools.web_doc)

    tools._retokenize_geometry()
    assert tools.web_doc == after_first
    assert len(tools.operations_ledger) == ledger
    assert tools._doc_version == version


def test_the_rebind_rides_the_ledger_and_is_invertible(tmp_path) -> None:
    from lumen_api.core import CoreClient

    tools = _unseeded_tools(tmp_path)
    before = copy.deepcopy(tools.web_doc)
    ledger_before = len(tools.operations_ledger)

    tools._retokenize_geometry()
    applied = tools.operations_ledger[ledger_before:]
    assert applied, "the rebind must ride the ledger through Accept"
    assert {op["kind"] for op in applied} == {"set_node_classes"}
    assert tools.web_doc != before

    # The ops are the core's own — replaying them on the pre-rebind document
    # reproduces the post-rebind document exactly, and the inverses the checked
    # apply hands back restore the original classes byte-for-byte.
    core = CoreClient(repo_root=REPO_ROOT)
    response = core.web_apply_ops(copy.deepcopy(before), applied)
    assert response["web_doc"] == tools.web_doc
    restored = core.web_apply_ops(
        response["web_doc"], list(reversed(response["inverse_operations"]))
    )
    assert _all_classes(restored["web_doc"]) == _all_classes(before)


def test_a_rejected_apply_changes_nothing_and_never_blocks_the_preview(
    tmp_path,
) -> None:
    from lumen_api.core import CoreError

    tools = _unseeded_tools(tmp_path)
    before = copy.deepcopy(tools.web_doc)
    ledger_before = len(tools.operations_ledger)
    version_before = tools._doc_version

    def _boom(*args, **kwargs):
        raise CoreError("op.rejected", "the checked apply refused this batch")

    tools.core.web_apply_ops = _boom  # type: ignore[method-assign]
    tools._retokenize_geometry()

    assert tools.web_doc == before
    assert len(tools.operations_ledger) == ledger_before
    assert tools._doc_version == version_before
    assert not [e for e in _trace_events(tools) if e["event"] == "web_geometry_retokenized"]


def test_the_trace_records_the_rebind_for_the_coordinator(tmp_path) -> None:
    tools = _unseeded_tools(tmp_path)
    tools._retokenize_geometry()
    events = [e for e in _trace_events(tools) if e["event"] == "web_geometry_retokenized"]
    assert len(events) == 1
    event = events[0]
    assert event["actor"] == "coordinator"
    assert event["payload"]["operation_count"] == len(
        [op for op in tools.operations_ledger if op["kind"] == "set_node_classes"]
    )
    assert "rounded-2xl→rounded-card" in " ".join(event["payload"]["class_pairs"])
    assert "rounded-2xl→rounded-card" in event["output_summary"]


def test_a_pass_with_nothing_to_do_records_nothing(tmp_path) -> None:
    tools = _unseeded_tools(tmp_path)
    tools._retokenize_geometry()
    tools._retokenize_geometry()
    events = [e for e in _trace_events(tools) if e["event"] == "web_geometry_retokenized"]
    assert len(events) == 1
