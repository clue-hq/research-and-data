"""`normalize_evidence` — turn a `BrandEvidence` bundle into a validated engine
Brand Kit plus an evidence-pointer ingestion report (§3).

Deterministic: identical evidence in → identical kit out. No randomness, no time
calls (created_at is a parameter). An optional `RoleAssist` may refine the draft;
`NullRoleAssist` (the default) is a deterministic no-op.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..assist import AssistDraft, NullRoleAssist, RoleAssist
from ..colorspace import (
    contrast_ratio,
    hex_to_oklch,
    with_lch,
    with_lightness,
)
from ..evidence import BrandEvidence
from .bands import build_band_surfaces
from .cluster import cluster_colors
from .emit import KitBuilder, build_constraints
from .font_metrics import build_type_size_ramp, glyph_gap_diagnostic
from .geometry import MEASURED_CONFIDENCE, build_shadows
from .ramps import derive_ramp, neutral_hue
from .roles import (
    RoleAssignment,
    assign_light_roles,
    build_dark_colorway,
)
from .scales import build_opacity, build_radii, build_spacing, build_strokes
from .typography import (
    TYPE_MEASUREMENT_FIELDS,
    anchor_for_role,
    build_type_styles,
    custodied_weights,
    measured_style_fields,
    resolve_anchors,
)

_CONTRAST_MIN = 4.5


@dataclass
class NormalizeResult:
    brand_kit: dict
    ingestion_report: dict
    diagnostics: list[dict]


def normalize_evidence(
    evidence: BrandEvidence,
    *,
    brand_kit_id: str,
    version: int = 1,
    name: str,
    created_at: str,
    assist: RoleAssist | None = None,
    font_metrics: dict[str, dict] | None = None,
) -> NormalizeResult:
    assist = assist or NullRoleAssist()
    diagnostics: list[dict] = []

    clusters = cluster_colors(evidence.colors)
    # Declared roles ride alongside the clusters, not through them (clone-fidelity F0.3):
    # the site's own naming of a color outranks anything we can infer from how often that
    # color appears. Empty for every non-website capture and every pre-F0.3 bundle, in
    # which case `assign_light_roles` behaves exactly as it always has.
    light = assign_light_roles(clusters, evidence.declared_roles, evidence.render_truth)
    diagnostics.extend(light.diagnostics)

    page_hex = light.assignments["surface.page"].hex
    text_hex = light.assignments["text.primary"].hex
    brand_hex = light.assignments["surface.brand"].hex

    # Ramps.
    primary_ramp = derive_ramp(brand_hex, neutral=False)
    neutral_anchor = with_lch(*_desaturate(text_hex))
    neutral_ramp = derive_ramp(
        neutral_anchor, neutral=True, hue_override=neutral_hue(page_hex)
    )

    # Assist refinement (deterministic no-op by default).
    draft = AssistDraft(
        clusters=[
            {"hex": c.representative, "weight": c.weight, "hints": c.role_hints, "name": c.name}
            for c in clusters
        ],
        color_roles={k: v.hex for k, v in light.assignments.items()},
        type_anchors={},
        narrative=evidence.narrative.model_dump(),
        rules=[r.text for r in evidence.rules],
    )
    assist_result = assist.refine(draft)
    tone_override = assist_result.tone if assist_result and assist_result.tone else None
    description = assist_result.description if assist_result else None

    # Full semantic color set (light) — derived from the three anchors.
    semantic_light = _derive_semantic_light(light, page_hex, text_hex, brand_hex, primary_ramp)

    # Dark colorway.
    dark = build_dark_colorway(clusters, light, primary_ramp)
    diagnostics.extend(dark.diagnostics)

    builder = KitBuilder(
        evidence,
        brand_kit_id=brand_kit_id,
        version=version,
        name=name,
        created_at=created_at,
    )

    # Emit palette ramps first (no dark modes — theme-invariant).
    builder.add_ramp("palette.primary", primary_ramp, "derived:brand-ramp")
    builder.add_ramp("palette.neutral", neutral_ramp, "derived:neutral-ramp")

    # Emit semantic colors with dark modes.
    for path, assignment in semantic_light.items():
        builder.add_color(path, assignment, dark.values.get(path))

    # Extras (named colors). The human-readable name is preserved on the token
    # description. An alias under the original name is added only when that name
    # is itself a valid token path (engine rejects space-bearing alias keys,
    # LUMB0120) and differs from the slug; multi-word names live on the
    # description alone.
    for cluster in light.extras:
        extra_path = builder.add_extra_color(cluster)
        slug = extra_path.rsplit(".", 1)[1]
        if cluster.name and _is_path_safe(cluster.name) and cluster.name != slug:
            builder.add_alias(cluster.name, extra_path, "ingestion alias")

    # Measured band surfaces. The page's background rhythm is measured; a color
    # the page RECURS on (or stands on for a fifth of its scroll) is a surface
    # the brand owns, so it gets a name instead of reaching the brief agent as
    # an unnamed hex. Runs after the extras so the dedupe sees every color the
    # kit already carries. Geometry-gated: evidence without a measured band
    # sequence mints nothing and its kit stays byte-identical.
    for band in build_band_surfaces(
        evidence.geometry.background_sequence,
        [entry["value"]["default"]["value"] for entry in builder.colors.values()],
    ):
        builder.add_color(
            band.path,
            RoleAssignment(band.hex, "measured", band.provenance),
            None,
            confidence=MEASURED_CONFIDENCE,
            description=band.description,
        )

    # accent alias (spec §4).
    builder.add_alias("accent.primary", "surface.accent", "ingestion alias")

    # Typography.
    anchors = resolve_anchors(evidence)
    if assist_result and assist_result.heading_family and _family_in_evidence(evidence, assist_result.heading_family):
        anchors.heading_family = assist_result.heading_family
    if assist_result and assist_result.body_family and _family_in_evidence(evidence, assist_result.body_family):
        anchors.body_family = assist_result.body_family
    cta_color = _cta_color_token(semantic_light, brand_hex)
    styles, type_diags = build_type_styles(
        anchors, cta_color=cta_color, custodied=custodied_weights(evidence)
    )
    diagnostics.extend(type_diags)
    for path, style in styles.items():
        anchor = anchor_for_role(path.removeprefix("type."), anchors)
        measured = measured_style_fields(anchors, path, style)
        if measured == TYPE_MEASUREMENT_FIELDS and anchor is not None:
            type_basis = "evidence"
            type_pointer = f"{anchor.pointer.source}:{anchor.pointer.locator}"
        else:
            type_basis = "derived" if evidence.type_samples or evidence.fonts else "default"
            type_pointer = "default:type-scale"
            if type_basis == "derived":
                type_pointer = f"derived:{path}; measured=" + (",".join(sorted(measured)) or "none")
                if anchor is not None and measured:
                    type_pointer += f" @ {anchor.pointer.source}:{anchor.pointer.locator}"
        builder.add_typography(path, style, type_basis, type_pointer)

    # Number scales. Measured geometry (design-brief slice 2) claims the steps
    # the brand's own site can fill; the rest stay on the derived base scale.
    spacing, spacing_measured, spacing_diags = build_spacing(evidence.numbers)
    diagnostics.extend(spacing_diags)
    builder.add_numbers(
        builder.spacing, spacing, "spacing", "derived:spacing-scale", spacing_measured
    )
    radii, radii_measured = build_radii(evidence.numbers)
    builder.add_numbers(builder.radii, radii, "radius", "derived:radius-scale", radii_measured)
    strokes, strokes_measured = build_strokes(evidence.numbers)
    builder.add_numbers(
        builder.stroke_widths, strokes, "stroke", "derived:stroke-scale", strokes_measured
    )
    builder.add_numbers(builder.opacity, build_opacity(), "visibility", "derived:opacity-scale")
    # Elevation: measured or honestly empty — never a fabricated default.
    builder.add_shadows(build_shadows(evidence.shadows))

    # K4 rung 2: the canonical type.size ramp, x-height-normalized against the
    # platform reference font using metrics MEASURED from this kit's own font
    # bytes (pipeline extracts them; None → identity ramp). Baked here at the
    # producer so every resolver inherits plain numbers — no resolver-side
    # math mirrors, and the derived values persist per the resolution-once
    # contract. The scraped ROLE sizes are untouched: they were measured on
    # the site rendered in the brand font, so they are already perceptually
    # ground truth.
    heading_metrics = (font_metrics or {}).get(anchors.heading_family) or (
        font_metrics or {}
    ).get(anchors.body_family)
    ramp_values, ramp_source = build_type_size_ramp(
        (heading_metrics or {}).get("x_height_ratio")
    )
    builder.add_numbers(builder.numbers, ramp_values, "font_size", ramp_source)

    # Fonts.
    _emit_fonts(builder, anchors)
    for font_json in builder.fonts.values():
        measured = (font_metrics or {}).get(font_json.get("family"))
        if measured:
            font_json["metrics"] = measured
            # Glyph-coverage audit is baked into the measured block by
            # extract_font_metrics; surface a LUMI0806 advisory per gapped face.
            missing = measured.get("missing_glyphs")
            if missing:
                diagnostics.append(
                    glyph_gap_diagnostic(font_json.get("family"), missing)
                )

    # Logos + images.
    if evidence.logos:
        builder.add_logos(evidence.logos)
    builder.add_images()

    asset_gaps = builder.report_missing_asset_tokens()
    diagnostics.extend(builder.diagnostics)

    constraints = build_constraints(evidence, tone_override, cta_color=cta_color)
    notes = _provenance_notes(evidence, dark.basis, description)

    brand_kit = builder.build(notes, constraints)
    if description:
        brand_kit["description"] = description

    ingestion_report = _build_report(
        evidence, clusters, builder, dark.basis, asset_gaps, description, tone_override
    )

    return NormalizeResult(
        brand_kit=brand_kit,
        ingestion_report=ingestion_report,
        diagnostics=diagnostics,
    )


def _is_path_safe(name: str) -> bool:
    if not name or name.startswith(".") or name.endswith(".") or ".." in name:
        return False
    return all(ch.isalnum() or ch in "_-." for ch in name)


def _desaturate(hex_value: str) -> tuple[float, float, float]:
    L, c, h = hex_to_oklch(hex_value)
    return L, min(c, 0.02), h


def _derive_semantic_light(
    light,
    page_hex: str,
    text_hex: str,
    brand_hex: str,
    primary_ramp: dict[str, str],
) -> dict[str, RoleAssignment]:
    page = light.assignments["surface.page"]
    text = light.assignments["text.primary"]
    brand = light.assignments["surface.brand"]
    accent = light.assignments.get("surface.accent")

    page_L, page_c, page_h = hex_to_oklch(page_hex)
    _, _, brand_h = hex_to_oklch(brand_hex)

    def derived(hex_value: str, what: str) -> RoleAssignment:
        return RoleAssignment(hex_value, "derived", f"derived:{what}")

    inverse = with_lch(0.18, min(page_c, 0.02), page_h)
    accent_hex = accent.hex if accent else primary_ramp["400"]
    accent_basis = accent if accent else derived(accent_hex, "accent(primary-400)")

    out: dict[str, RoleAssignment] = {
        "surface.page": page,
        "surface.canvas": derived(with_lch(min(0.995, page_L + 0.005), page_c, page_h), "surface.canvas"),
        "surface.card": page,
        "surface.elevated": derived(with_lch(min(1.0, page_L), 0.0, page_h), "surface.elevated"),
        "surface.brand": brand,
        "surface.brand.subtle": derived(primary_ramp["100"], "surface.brand.subtle"),
        "surface.accent": accent_basis,
        "surface.muted": derived(with_lch(max(0.0, page_L - 0.05), page_c, page_h), "surface.muted"),
        "surface.inverse": derived(inverse, "surface.inverse"),
        "text.primary": text,
        "text.secondary": derived(with_lightness(text_hex, min(0.45, hex_to_oklch(text_hex)[0] + 0.2)), "text.secondary"),
        "text.muted": derived(with_lightness(text_hex, min(0.55, hex_to_oklch(text_hex)[0] + 0.3)), "text.muted"),
        "text.inverse": derived(_readable_on(inverse), "text.inverse"),
        "text.brand": derived(_brand_text(brand_hex, page_hex, primary_ramp), "text.brand"),
        "text.accent": derived(_brand_text(accent_hex, page_hex, primary_ramp), "text.accent"),
        "border.subtle": derived(with_lch(max(0.0, page_L - 0.08), min(page_c, 0.02), page_h), "border.subtle"),
        "border.default": derived(with_lch(max(0.0, page_L - 0.16), min(page_c, 0.02), page_h), "border.default"),
        "border.strong": derived(with_lch(max(0.0, page_L - 0.35), min(page_c, 0.02), page_h), "border.strong"),
        "border.brand": derived(primary_ramp["500"], "border.brand"),
        "focus.ring": derived(primary_ramp["500"], "focus.ring"),
    }
    return out


def _readable_on(bg_hex: str) -> str:
    white = "#FFFFFF"
    dark = "#0B0F14"
    if contrast_ratio(white, bg_hex) >= contrast_ratio(dark, bg_hex):
        return white
    return dark


def _cta_color_token(semantic_light: dict[str, RoleAssignment], brand_hex: str) -> str:
    """Text token for type.cta (text sitting on surface.brand buttons).

    text.inverse serves surface.inverse, so on a LIGHT brand color it is
    light-on-light; fall back to text.primary when it reads better on brand.
    """
    inverse_ratio = contrast_ratio(semantic_light["text.inverse"].hex, brand_hex)
    if inverse_ratio >= _CONTRAST_MIN:
        return "text.inverse"
    primary_ratio = contrast_ratio(semantic_light["text.primary"].hex, brand_hex)
    return "text.primary" if primary_ratio > inverse_ratio else "text.inverse"


def _brand_text(brand_hex: str, page_hex: str, primary_ramp: dict[str, str]) -> str:
    """A brand-derived text color that reads on the page surface."""
    if contrast_ratio(brand_hex, page_hex) >= _CONTRAST_MIN:
        return brand_hex
    for stop in ("700", "800", "900", "950"):
        candidate = primary_ramp[stop]
        if contrast_ratio(candidate, page_hex) >= _CONTRAST_MIN:
            return candidate
    return primary_ramp["950"]


def _family_in_evidence(evidence: BrandEvidence, family: str) -> bool:
    if any(f.family == family for f in evidence.fonts):
        return True
    return any(s.family == family for s in evidence.type_samples)


def _emit_fonts(builder: KitBuilder, anchors) -> None:
    evidence = builder.evidence
    heading_font = _font_for_family(evidence, anchors.heading_family)
    body_font = _font_for_family(evidence, anchors.body_family)

    if heading_font is not None:
        builder.add_font("brand", heading_font, ["Arial", "sans-serif"])
    else:
        builder.add_font("brand", _synthetic_font(anchors.heading_family), ["Arial", "sans-serif"])

    if anchors.body_family != anchors.heading_family:
        if body_font is not None:
            builder.add_font("body", body_font, ["Arial", "sans-serif"])
        else:
            builder.add_font("body", _synthetic_font(anchors.body_family), ["Arial", "sans-serif"])


def _font_for_family(evidence: BrandEvidence, family: str):
    for font in evidence.fonts:
        if font.family == family:
            return font
    return None


def _synthetic_font(family: str):
    from ..evidence import EvidencePointer, FontEvidence

    return FontEvidence(
        family=family,
        role_hint="unknown",
        faces=[],
        fallback_stack=[],
        license_hint=None,
        pointer=EvidencePointer(source="derived", locator="synthesizer"),
    )


def _provenance_notes(evidence: BrandEvidence, dark_basis: str, description: str | None) -> list[str]:
    notes = [f"Ingested from {evidence.source.get('kind', 'unknown')} evidence."]
    notes.append(
        "Dark colorway captured from evidence."
        if dark_basis == "captured"
        else "Dark colorway synthesized from the light palette."
    )
    if description:
        notes.append(description)
    return notes


def _build_report(
    evidence,
    clusters,
    builder,
    dark_basis: str,
    asset_gaps: list[str],
    description: str | None,
    tone_override,
) -> dict:
    gaps = sorted(
        asset_gaps
        + [a["token"] for a in builder.role_assignments if a["basis"] == "default"]
    )
    narrative = evidence.narrative.model_dump()
    if description:
        narrative["description"] = description
    return {
        "schema_version": 1,
        "source": evidence.source,
        "stats": {
            "colors_observed": len(evidence.colors),
            "clusters": len(clusters),
            "fonts": len(evidence.fonts),
            "logos": len(evidence.logos),
            "images": len(evidence.images),
            "rules": len(evidence.rules),
        },
        "role_assignments": builder.role_assignments,
        "dark_colorway": "captured" if dark_basis == "captured" else "synthesized",
        "gaps": gaps,
        "narrative": narrative,
        # Usage rules (don'ts, combinations, clearspace…) survive here for the
        # review UI and later agent briefs — most have no BrandConstraints field.
        "rules": [{"kind": r.kind, "text": r.text} for r in evidence.rules],
    }
