"""Type-ramp mapping (§3.4).

Maps `type_samples` (+ font role hints) to the 12 required `type.*` roles. When an
anchor sample exists for a role its size/weight/line-height feed the emitted
style; otherwise sizes derive from a body size B and headline size H. Heading and
body families come from the most-frequent family among heading/body samples (or
fonts[] role hints), falling back to a single family used for both.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..evidence import BrandEvidence, FontEvidence, TypeSample

_DEFAULT_BODY = 16.0
_DEFAULT_HEADLINE = 32.0
_DEFAULT_HEADING_WEIGHT = 700
_DEFAULT_BODY_WEIGHT = 400

_HEADING_LABELS = {"h1", "h2", "h3"}
_BODY_LABELS = {"body", "p"}

# Label -> role mapping for anchoring. PUBLIC because it is the only statement
# of which type roles a real sample can anchor, and the F2.4 grammar audit
# (`lumen_ingestion.grammar_audit`) has to say measured-vs-computed per role
# without re-deriving that table and drifting from it.
ANCHOR_LABELS: dict[str, str] = {
    "h1": "headline",
    "h2": "title",
    "body": "body",
    "p": "body",
    "button": "cta",
    "caption": "caption",
}

_HEADING_ROLES = {"display", "headline", "title", "stat", "eyebrow"}


@dataclass
class TypeAnchors:
    heading_family: str
    body_family: str
    headline_size: float
    body_size: float
    heading_weight: int
    body_weight: int
    samples: dict[str, TypeSample]


def _family_from(samples: list[TypeSample], labels: set[str], fonts: list[FontEvidence], role: str) -> str | None:
    counts: dict[str, int] = {}
    order: list[str] = []
    for sample in samples:
        if sample.label in labels and sample.family:
            if sample.family not in counts:
                order.append(sample.family)
            counts[sample.family] = counts.get(sample.family, 0) + 1
    if counts:
        return max(order, key=lambda fam: (counts[fam], -order.index(fam)))
    for font in fonts:
        if font.role_hint == role:
            return font.family
    return None


def resolve_anchors(evidence: BrandEvidence) -> TypeAnchors:
    samples = evidence.type_samples
    by_label: dict[str, TypeSample] = {}
    for sample in samples:
        by_label.setdefault(sample.label, sample)

    heading_family = _family_from(samples, _HEADING_LABELS, evidence.fonts, "heading")
    body_family = _family_from(samples, _BODY_LABELS, evidence.fonts, "body")

    # PDF-shaped labels
    if heading_family is None:
        heading_family = _family_from(samples, {"pdf-heading"}, evidence.fonts, "heading")
    if body_family is None:
        body_family = _family_from(samples, {"pdf-body"}, evidence.fonts, "body")

    if heading_family is None and body_family is not None:
        heading_family = body_family
    if body_family is None and heading_family is not None:
        body_family = heading_family
    if heading_family is None:
        # Any font at all, else system default.
        heading_family = evidence.fonts[0].family if evidence.fonts else "Inter"
    if body_family is None:
        body_family = heading_family

    headline_sample = by_label.get("h1") or by_label.get("pdf-heading")
    body_sample = by_label.get("body") or by_label.get("p") or by_label.get("pdf-body")

    headline_size = (
        headline_sample.size_px if headline_sample and headline_sample.size_px else _DEFAULT_HEADLINE
    )
    body_size = body_sample.size_px if body_sample and body_sample.size_px else _DEFAULT_BODY
    heading_weight = (
        headline_sample.weight if headline_sample and headline_sample.weight else _DEFAULT_HEADING_WEIGHT
    )
    body_weight = body_sample.weight if body_sample and body_sample.weight else _DEFAULT_BODY_WEIGHT

    return TypeAnchors(
        heading_family=heading_family,
        body_family=body_family,
        headline_size=float(headline_size),
        body_size=float(body_size),
        heading_weight=int(heading_weight),
        body_weight=int(body_weight),
        samples=by_label,
    )


def _round_half(value: float) -> float:
    return round(value * 2.0) / 2.0


def custodied_weights(evidence: BrandEvidence) -> dict[str, list[int]]:
    """{family: sorted weights we actually hold BYTES for}.

    Custody, not declaration: a face with a `source_url` and no `asset_id` is a
    face the kit knows about but cannot paint, so it cannot honour a role.
    A family with no custodied faces at all is absent from this map — that is
    the LUMI0230 "font files not sourced" case, and it is not this function's
    to re-report.
    """
    out: dict[str, list[int]] = {}
    for font in evidence.fonts:
        weights = sorted({
            face.weight for face in font.faces
            if face.asset_id is not None and face.weight
        })
        if weights:
            out[font.family] = weights
    return out


def _nearest_custodied(target: int, available: list[int]) -> int:
    """Closest shipped weight; ties go to the heavier face.

    A tie means the target sits exactly between two faces (400 asked of
    [300, 500]). Rounding up keeps a display/stat role as emphatic as the kit
    can make it, which is the intent the role was carrying.
    """
    return min(available, key=lambda w: (abs(w - target), -w))


def weight_snap_diagnostic(family: str, role: str, declared: int, actual: int) -> dict:
    """One LUMI0232 advisory per role whose declared weight the kit cannot paint.

    Severity `warning`: the kit is publishable and the role now renders exactly
    what it declares — this records that the DECLARATION moved, so nobody reads
    the emitted 300 as evidence the site's stat numerals were light.
    """
    return {
        "code": "LUMI0232",
        "severity": "warning",
        "message": (
            f"type.{role} asked for '{family}' weight {declared} but the kit custodies "
            f"only {family} weight(s) that cannot serve it; the role now declares "
            f"{actual}, the nearest face the kit actually ships — add a {declared} "
            f"face to restore the intended weight"
        ),
    }


#: A real style's leading, as a ratio of its font size. Outside this band the number is a unit
#: misparse (the 2026-09-04 Apollo kit carried 4.5 = 72px / 16), never a design choice.
LINE_HEIGHT_RATIO_RANGE: tuple[float, float] = (0.5, 2.5)
#: Tracking beyond half an em in either direction is likewise a misparse.
LETTER_SPACING_EM_LIMIT: float = 0.5


def type_unit_diagnostic(role: str, field: str, value: float, locator: str) -> dict:
    """One LUMI0233 warning per (role, field) whose harvested unit could not be a real style."""
    return {
        "code": "LUMI0233",
        "severity": "warning",
        "message": (
            f"type.{role} {field} {value:g} (from {locator}) is outside the range a real style "
            f"can carry; it was a unit misparse, so the role keeps its derived default"
        ),
    }


def build_type_styles(
    anchors: TypeAnchors,
    cta_color: str = "text.inverse",
    custodied: dict[str, list[int]] | None = None,
) -> tuple[dict[str, dict], list[dict]]:
    """Return {role: {font_family, font_size, font_weight, line_height,
    letter_spacing, color, font_asset}} for the 12 required roles, plus any
    diagnostics raised while building them.

    A role may only declare a (family, weight) pair the custodied faces can
    actually paint. apollo.io's kit declared `type.stat` as seasonMix 700 while
    custodying only a weight-300 face: the engine substituted the nearest face
    and raised LUMS0104 at preflight, and the authoring agent — reading that as
    "the kit cannot do bold" — abandoned the kit family entirely and invented
    `Bricolage Grotesque`. Snapping the declaration at BIRTH means the role
    always states the truth, so preflight has nothing to complain about.
    """
    B = anchors.body_size
    H = anchors.headline_size
    hw = anchors.heading_weight
    bw = anchors.body_weight

    # (role, size, weight, line_height, color, letter_spacing)
    spec: list[tuple[str, float, int, float, str, float]] = [
        ("display", H * 1.6, max(hw, 700), 1.05, "text.primary", -0.02),
        ("headline", H, hw, 1.1, "text.primary", -0.01),
        ("title", H * 0.72, hw, 1.15, "text.primary", 0.0),
        ("subtitle", B * 1.25, 500, 1.3, "text.secondary", 0.0),
        ("body", B, bw, 1.45, "text.primary", 0.0),
        ("body.small", B * 0.875, bw, 1.4, "text.primary", 0.0),
        ("caption", B * 0.75, 500, 1.35, "text.secondary", 0.0),
        ("eyebrow", B * 0.75, 600, 1.2, "text.brand", 0.08),
        ("label", B * 0.8125, 600, 1.2, "text.primary", 0.0),
        ("cta", B, 600, 1.2, cta_color, 0.0),
        ("stat", H * 1.25, max(hw, 700), 1.0, "text.brand", 0.0),
        ("legal", B * 0.6875, bw, 1.3, "text.muted", 0.0),
    ]

    shipped = custodied or {}
    styles: dict[str, dict] = {}
    diagnostics: list[dict] = []
    for role, size, weight, line_height, color, letter_spacing in spec:
        anchor = _anchor_for(role, anchors)
        final_size = size
        final_weight = weight
        final_lh = line_height
        final_ls = letter_spacing
        if anchor is not None:
            if anchor.size_px:
                final_size = anchor.size_px
            if anchor.weight:
                final_weight = anchor.weight
            if anchor.line_height:
                lo, hi = LINE_HEIGHT_RATIO_RANGE
                if lo <= anchor.line_height <= hi:
                    final_lh = anchor.line_height
                else:
                    diagnostics.append(
                        type_unit_diagnostic(role, "line_height", anchor.line_height, anchor.pointer.locator)
                    )
            if anchor.letter_spacing is not None:
                if abs(anchor.letter_spacing) <= LETTER_SPACING_EM_LIMIT:
                    final_ls = anchor.letter_spacing
                else:
                    diagnostics.append(
                        type_unit_diagnostic(role, "letter_spacing", anchor.letter_spacing, anchor.pointer.locator)
                    )
        family = anchors.heading_family if role in _HEADING_ROLES else anchors.body_family
        font_asset = "brand" if role in _HEADING_ROLES else ("body" if anchors.body_family != anchors.heading_family else "brand")

        # Never declare a weight this family cannot paint.
        available = shipped.get(family)
        if available and int(final_weight) not in available:
            declared = int(final_weight)
            final_weight = _nearest_custodied(declared, available)
            diagnostics.append(
                weight_snap_diagnostic(family, role, declared, final_weight)
            )

        styles[f"type.{role}"] = {
            "kind": "style",
            "font_family": family,
            "font_size": _round_half(final_size),
            "font_weight": int(final_weight),
            "line_height": round(final_lh, 4),
            "letter_spacing": round(final_ls, 4),
            "color": color,
            "font_asset": font_asset,
        }
    return styles, diagnostics


def _anchor_for(role: str, anchors: TypeAnchors) -> TypeSample | None:
    for label, mapped in ANCHOR_LABELS.items():
        if mapped == role and label in anchors.samples:
            return anchors.samples[label]
    return None
