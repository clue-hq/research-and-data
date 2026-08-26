"""F0.3 source-truth styling — the site's OWN declarations outrank our heuristics.

Three mechanisms, one theme: a modern marketing site (Webflow / Framer / shadcn class)
literally *declares* its design tokens, its interaction states and its dark palette in CSS.
Before this slice we threw all three away and re-derived a palette by clustering whatever
colors happened to appear. These tests pin the reversal:

1. a declared custom property whose NAME carries a role word becomes that role directly
   (`basis: declared`, pointer `custom-prop:<name>`, confidence 0.9), beating the cluster;
2. `:hover/:focus/:active/:disabled` rules on interactive selectors survive as StateStyle
   evidence instead of being flattened into anonymous swatches;
3. `@media (prefers-color-scheme: dark)` custom-property overrides make the dark colorway
   CAPTURED rather than synthesized.

Plus the two long-standing parser crashes from `design/research/RUN-REPORT.md`.
"""

from __future__ import annotations

import tempfile

import pytest

from lumen_ingestion import BrandEvidence, normalize_evidence
from lumen_ingestion.capture import CaptureOutcome, build_evidence
from lumen_ingestion.capture.budget import MAX_STATE_STYLE_COUNT
from lumen_ingestion.capture.declared_roles import role_for_property_name
from lumen_ingestion.capture.parse import parse_color_value, parse_site
from lumen_ingestion.capture.snapshot import SiteSnapshot, Stylesheet
from lumen_ingestion.evidence import (
    ColorEvidence,
    DeclaredRoleEvidence,
    EvidencePointer,
)
from lumen_ingestion.normalizer.roles import DECLARED_ROLE_CONFIDENCE


def _noop(stage: str, progress: float) -> None:
    return None


class _StubCore:
    def ingest_asset(self, **kwargs):
        return {"ok": True, "asset": {"record": {"id": kwargs["asset_id"]}}}


def _snapshot(css: str, *, html: str = "<html><body><p>hi</p></body></html>") -> SiteSnapshot:
    return SiteSnapshot(
        requested_url="https://example.com/",
        final_url="https://example.com/",
        fetched_at="2026-08-27T00:00:00Z",
        tier="static",
        html=html,
        stylesheets=[Stylesheet(url="https://example.com/site.css", text=css)],
    )


def _evidence(snapshot: SiteSnapshot) -> BrandEvidence:
    outcome = CaptureOutcome(
        snapshot=snapshot,
        tier=snapshot.tier,
        escalated=False,
        escalation_reason=None,
        diagnostics=[],
    )
    with tempfile.TemporaryDirectory() as store:
        return build_evidence(outcome, core=_StubCore(), store_root=store, reporter=_noop)


def _report(evidence: BrandEvidence) -> dict:
    return normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_f03",
        version=1,
        name="F0.3",
        created_at="2026-08-27",
    ).ingestion_report


def _assignment(report: dict, token: str) -> dict:
    for entry in report["role_assignments"]:
        if entry["token"] == token:
            return entry
    raise AssertionError(f"{token} not in role_assignments")


# --------------------------------------------------------------------------- #
# 1. Declared variables as role declarations
# --------------------------------------------------------------------------- #

#: A Webflow-shaped declaration block: the palette is stated, not inferred.
_WEBFLOW_CSS = """
:root {
  --base-color-brand--green: #30d8a7;
  --base-color-accent--coral: #ff5c39;
  --base-color-background--page: #fbfbf9;
  --base-color-text--body: #101418;
}
body { background: #ffffff; color: #333333; }
.hero { background: #6633ee; }
.hero-2 { background: #6633ee; }
.hero-3 { background: #6633ee; }
"""


def test_declared_names_map_to_the_four_anchors() -> None:
    assert role_for_property_name("--base-color-brand--green") == "surface.brand"
    assert role_for_property_name("--base-color-accent--coral") == "surface.accent"
    assert role_for_property_name("--base-color-background--page") == "surface.page"
    assert role_for_property_name("--base-color-text--body") == "text.primary"
    # names, not colors: a hex-flavoured name with no role word maps to nothing
    assert role_for_property_name("--base-color-neutral--white") is None
    assert role_for_property_name("--violet") is None
    assert role_for_property_name("--navy") is None
    assert role_for_property_name("--x1") is None
    # a VARIANT of a role is not the anchor
    assert role_for_property_name("--background-hover") is None
    assert role_for_property_name("--text-muted") is None
    assert role_for_property_name("--brand-500") is None


def test_declared_roles_beat_the_clustered_candidates() -> None:
    parsed = parse_site(_snapshot(_WEBFLOW_CSS))
    declared = {d.role: d for d in parsed.declared_roles}
    assert declared["surface.brand"].value == "#30D8A7"
    assert declared["surface.brand"].property_name == "--base-color-brand--green"

    report = _report(_evidence(_snapshot(_WEBFLOW_CSS)))

    brand = _assignment(report, "surface.brand")
    assert brand == {
        "token": "surface.brand",
        "value": "#30D8A7",
        "basis": "declared",
        "pointer": "custom-prop:--base-color-brand--green",
    }
    # the heavily-repeated `.hero` purple is the candidate the clusterer would
    # have crowned; the declaration outranks it.
    assert brand["value"] != "#6633EE"

    assert _assignment(report, "surface.page")["basis"] == "declared"
    assert _assignment(report, "surface.page")["value"] == "#FBFBF9"
    assert _assignment(report, "text.primary")["basis"] == "declared"
    assert _assignment(report, "text.primary")["value"] == "#101418"
    assert _assignment(report, "surface.accent")["basis"] == "declared"
    assert _assignment(report, "surface.accent")["value"] == "#FF5C39"


def test_a_declared_role_carries_the_declared_confidence() -> None:
    kit = normalize_evidence(
        _evidence(_snapshot(_WEBFLOW_CSS)),
        brand_kit_id="brand_kit_f03",
        version=1,
        name="F0.3",
        created_at="2026-08-27",
    ).brand_kit
    provenance = kit["tokens"]["colors"]["surface.brand"]["provenance"]
    assert provenance["confidence"] == DECLARED_ROLE_CONFIDENCE == 0.9
    assert provenance["source"] == "custom-prop:--base-color-brand--green"


def test_alias_chains_resolve_to_the_pointed_at_color() -> None:
    css = """
    :root { --green: #30d8a7; --color-primary: var(--green); }
    body { background: #ffffff; color: #222222; }
    """
    parsed = parse_site(_snapshot(css))
    declared = {d.role: d for d in parsed.declared_roles}
    assert declared["surface.brand"].value == "#30D8A7"
    assert declared["surface.brand"].property_name == "--color-primary"


def test_non_semantic_prop_names_keep_todays_weighted_behaviour() -> None:
    css = """
    :root { --x1: #123456; --tone-7: #654321; }
    body { background: #ffffff; color: #1a1a1a; }
    .btn { background: #0055ff; }
    """
    parsed = parse_site(_snapshot(css))
    assert parsed.declared_roles == []
    # the custom props still arrive as weight-3.0 hinted color evidence, exactly as before
    props = [c for c in parsed.colors if c.locator.startswith("css :: --")]
    assert [(c.value, c.weight, c.role_hints) for c in props] == [
        ("#123456", 3.0, ["custom-prop:--x1"]),
        ("#654321", 3.0, ["custom-prop:--tone-7"]),
    ]
    report = _report(_evidence(_snapshot(css)))
    assert {a["basis"] for a in report["role_assignments"]} .isdisjoint({"declared"})


def test_a_declared_text_color_that_cannot_be_read_on_the_page_is_refused() -> None:
    """shadcn ships `--primary-foreground` — a foreground, but the INVERSE one.

    Rather than out-clever ourselves on naming, the declared text role keeps the
    same AA gate the clustered one has always had: a declaration that cannot be
    read on the declared page loses, loudly.
    """
    css = """
    :root { --background: #ffffff; --primary-foreground: #fafafa; }
    body { background: #ffffff; color: #1a1a1a; }
    """
    evidence = _evidence(_snapshot(css))
    result = normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_f03",
        version=1,
        name="F0.3",
        created_at="2026-08-27",
    )
    assert _assignment(result.ingestion_report, "surface.page")["basis"] == "declared"
    assert _assignment(result.ingestion_report, "text.primary")["basis"] != "declared"
    assert any(d["code"] == "LUMI0518" for d in result.diagnostics), result.diagnostics


# --------------------------------------------------------------------------- #
# 2. Interaction-state extraction
# --------------------------------------------------------------------------- #


def test_a_hover_rule_on_a_button_becomes_a_state_style() -> None:
    css = """
    :root { --btn-hover: #0044cc; }
    .btn:hover { background: var(--btn-hover); color: #ffffff; border-color: #002288;
                 box-shadow: 0 2px 8px rgba(0,0,0,0.2); opacity: 0.9; }
    a:focus-visible { outline: none; color: #0044cc; }
    button:disabled { opacity: 0.4; }
    .card:hover { background: #eeeeee; }
    """
    parsed = parse_site(_snapshot(css))
    by_selector = {(s.selector, s.state): s for s in parsed.state_styles}

    hover = by_selector[(".btn:hover", "hover")]
    assert hover.background == "#0044CC"
    assert hover.color == "#FFFFFF"
    assert hover.border_color == "#002288"
    assert hover.box_shadow == "0 2px 8px rgba(0,0,0,0.2)"  # kept as declared
    assert hover.opacity == 0.9
    assert hover.text_decoration is None
    assert hover.scheme == "light"

    assert ("a:focus-visible", "focus-visible") in by_selector
    assert ("button:disabled", "disabled") in by_selector
    # a non-interactive selector's hover is not an interaction state we model
    assert ("​.card:hover", "hover") not in by_selector
    assert all(not s.selector.startswith(".card") for s in parsed.state_styles)


def test_state_styles_reach_brand_evidence() -> None:
    css = ".btn:hover { background: #0044cc; }"
    evidence = _evidence(_snapshot(css))
    assert [(s.selector, s.state, s.background) for s in evidence.state_styles] == [
        (".btn:hover", "hover", "#0044CC")
    ]
    # round-trips through the persisted evidence JSON
    assert BrandEvidence.model_validate(evidence.model_dump()).state_styles == evidence.state_styles


def test_state_style_overflow_is_loud() -> None:
    rules = "\n".join(
        f".btn-{i}:hover {{ background: #0044cc; }}" for i in range(MAX_STATE_STYLE_COUNT + 5)
    )
    parsed = parse_site(_snapshot(rules))
    assert len(parsed.state_styles) == MAX_STATE_STYLE_COUNT
    overflow = [d for d in parsed.diagnostics if d["code"] == "LUMI0517"]
    assert len(overflow) == 1
    assert len(overflow[0]["dropped"]) == 5
    assert overflow[0]["severity"] == "warning"
    assert ".btn-200:hover" in overflow[0]["message"]


# --------------------------------------------------------------------------- #
# 3. Dark-scheme capture
# --------------------------------------------------------------------------- #

_DARK_CSS = """
:root { --background: #ffffff; --text-color: #101418; --color-primary: #30d8a7; }
body { background: #ffffff; color: #101418; }
@media (prefers-color-scheme: dark) {
  :root { --background: #0b0f14; --text-color: #f2f5f7; }
  .btn:hover { background: #1f2933; color: #f2f5f7; }
}
"""


def test_dark_custom_prop_overrides_capture_the_dark_colorway() -> None:
    parsed = parse_site(_snapshot(_DARK_CSS))
    dark = {c.value for c in parsed.colors if c.theme == "dark"}
    assert "#0B0F14" in dark
    assert "#F2F5F7" in dark
    # the light values are NOT overwritten by the dark block
    assert parsed.custom_props["--background"] == "#ffffff"

    report = _report(_evidence(_snapshot(_DARK_CSS)))
    assert report["dark_colorway"] == "captured"


def test_a_dark_scoped_hover_is_tagged_dark() -> None:
    parsed = parse_site(_snapshot(_DARK_CSS))
    schemes = {(s.selector, s.scheme) for s in parsed.state_styles}
    assert (".btn:hover", "dark") in schemes


def test_a_site_with_no_dark_block_still_synthesizes() -> None:
    css = ":root { --background: #ffffff; }\nbody { background: #fff; color: #111; }"
    report = _report(_evidence(_snapshot(css)))
    assert report["dark_colorway"] == "synthesized"


# --------------------------------------------------------------------------- #
# 4. The two parser crashes (RUN-REPORT.md §2)
# --------------------------------------------------------------------------- #


def test_a_cyclic_custom_property_chain_does_not_recurse_forever() -> None:
    """cursor.com/about ships `--a: var(--b); --b: var(--a)` — a RecursionError
    that failed the whole ingestion job."""
    diagnostics: list[dict] = []
    props = {"--a": "var(--b)", "--b": "var(--a)"}
    assert parse_color_value("var(--a)", props, diagnostics=diagnostics) is None
    assert diagnostics, "an unresolvable cycle must be reported, not silently dropped"
    message = diagnostics[0]["message"]
    assert "--a" in message and "--b" in message, message


def test_a_var_in_the_alpha_slot_does_not_crash() -> None:
    """apollo.io / Tailwind: `rgb(15 23 42 / var(--tw-text-opacity))` used to die
    in `float()` and take the job with it."""
    diagnostics: list[dict] = []
    value = parse_color_value(
        "rgba(24 24 27 / var(--tw-text-opacity))", {}, diagnostics=diagnostics
    )
    assert value == "#18181B"
    assert any("alpha" in d["message"] for d in diagnostics)


def test_a_resolvable_alpha_var_is_resolved_not_flattened_to_opaque() -> None:
    assert parse_color_value("rgba(255 0 0 / var(--o))", {"--o": "0.5"}) == "#FF000080"
    assert parse_color_value("rgba(255 0 0 / var(--o, 0.5))", {}) == "#FF000080"
    assert parse_color_value("hsl(0 100% 50% / var(--o))", {"--o": "50%"}) == "#FF000080"


def test_the_ordinary_color_forms_are_untouched() -> None:
    assert parse_color_value("rgb(15 23 42 / 60%)", {}) == "#0F172A99"
    assert parse_color_value("rgba(255,0,0,0.5)", {}) == "#FF000080"
    assert parse_color_value("#abc", {}) == "#AABBCC"
    assert parse_color_value("var(--x)", {"--x": "#30d8a7"}) == "#30D8A7"


# --------------------------------------------------------------------------- #
# 5. No behaviour change without declarations
# --------------------------------------------------------------------------- #


def test_evidence_without_declared_roles_normalizes_exactly_as_before() -> None:
    plain = BrandEvidence(
        source={"kind": "website"},
        colors=[
            ColorEvidence(
                value="#FFFFFF",
                weight=5.0,
                role_hints=["page-bg"],
                pointer=EvidencePointer(source="website", locator="css :: body"),
            ),
            ColorEvidence(
                value="#111111",
                weight=5.0,
                role_hints=["body-text"],
                pointer=EvidencePointer(source="website", locator="css :: body"),
            ),
            ColorEvidence(
                value="#0055FF",
                weight=4.0,
                role_hints=["button-bg"],
                pointer=EvidencePointer(source="website", locator="css :: .btn"),
            ),
        ],
    )
    report = _report(plain)
    assert _assignment(report, "surface.page")["basis"] == "evidence"
    assert _assignment(report, "surface.brand")["value"] == "#0055FF"
    assert {a["basis"] for a in report["role_assignments"]}.isdisjoint({"declared"})


def test_a_declared_role_leaves_its_cluster_out_of_the_extras() -> None:
    """The declared swatch must not ALSO appear as an anonymous accent/extra."""
    declared = DeclaredRoleEvidence(
        role="surface.brand",
        property_name="--color-primary",
        value="#30D8A7",
        pointer=EvidencePointer(source="website", locator="css :: --color-primary"),
    )
    evidence = BrandEvidence(
        source={"kind": "website"},
        declared_roles=[declared],
        colors=[
            ColorEvidence(
                value="#FFFFFF",
                weight=5.0,
                role_hints=["page-bg"],
                pointer=EvidencePointer(source="website", locator="css :: body"),
            ),
            ColorEvidence(
                value="#111111",
                weight=5.0,
                role_hints=["body-text"],
                pointer=EvidencePointer(source="website", locator="css :: body"),
            ),
            ColorEvidence(
                value="#30D8A7",
                weight=3.0,
                role_hints=["custom-prop:--color-primary"],
                pointer=EvidencePointer(source="website", locator="css :: --color-primary"),
            ),
        ],
    )
    report = _report(evidence)
    assert _assignment(report, "surface.brand") == {
        "token": "surface.brand",
        "value": "#30D8A7",
        "basis": "declared",
        "pointer": "custom-prop:--color-primary",
    }
    accent = _assignment(report, "surface.accent")
    assert accent["value"] != "#30D8A7"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
