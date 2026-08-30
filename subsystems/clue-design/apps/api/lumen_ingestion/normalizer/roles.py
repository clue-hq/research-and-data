"""Deterministic role assignment (§3.2) + dark colorway (§3.6).

Light-theme semantic roles are assigned from clustered evidence by fixed rules;
the dark colorway is assigned from captured dark evidence when present, else
synthesized from the light palette. Every decision records a `basis`
("declared" | "evidence" | "derived" | "default") and a compact provenance
string so the emitter can stamp per-token provenance and the report can explain
choices.

`declared` is the top of that order (clone-fidelity F0.3): when the site itself
named the role in a custom property, that statement beats anything we can infer
by clustering its swatches. See `capture/declared_roles.py` for what counts as a
declaration and — just as importantly — what does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..colorspace import (
    PASTEL_C,
    contrast_ratio,
    hex_to_oklab,
    hex_to_oklch,
    hue_distance,
    oklab_distance,
    with_lch,
    with_lightness,
)
from ..evidence import DeclaredRoleEvidence, RenderTruth
from .cluster import MERGE_DISTANCE, ColorCluster

NEAR_NEUTRAL_C = 0.03
SATURATED_C = 0.07
_CONTRAST_MIN = 4.5

_SATURATED_HINTS = {"button-bg", "accent", "link"}
_BRAND_FALLBACK = "#0F766E"

#: What a `declared` basis is worth (clone-fidelity F0.3). A role the site named in its own
#: stylesheet is as good as a directly observed swatch — and no better: 1.0 stays reserved
#: for things that cannot be wrong, and a declaration can be stale or aspirational.
DECLARED_ROLE_CONFIDENCE = 0.9


@dataclass
class RoleAssignment:
    hex: str
    # "evidence" (an observed swatch) | "measured" (read off the rendered page,
    # but a cluster representative — see bands.py) | "derived" | "default".
    # `emit._confidence_for` maps each to its confidence; a basis it does not
    # know falls to 0.3, so add new ones there too.
    basis: str
    provenance: str       # compact provenance string
    cluster: ColorCluster | None = None


@dataclass
class LightRoles:
    assignments: dict[str, RoleAssignment]
    extras: list[ColorCluster]
    diagnostics: list[dict] = field(default_factory=list)


def _pointer(cluster: ColorCluster) -> str:
    return f"{cluster.pointer_source}:{cluster.pointer_locator}"


def _is_near_neutral(cluster: ColorCluster) -> bool:
    return _is_near_neutral_hex(cluster.representative)


def _is_near_neutral_hex(hex_value: str) -> bool:
    """Is this color a neutral — a black, white or grey — rather than a hue?

    Deliberately `NEAR_NEUTRAL_C` (0.03) and NOT the `_is_saturated` floor (0.07) that the
    clustered brand search uses. The gate exists to catch a declaration that names a NEUTRAL
    as the brand, not to impose a saturation minimum: plenty of real brands are muted, and a
    declaration is exactly the evidence that lets us keep one clustering would have discarded
    (`_is_saturated` would have refused a slate-blue brand and fallen through to the platform
    teal — strictly worse than believing the site).
    """
    return hex_to_oklch(hex_value)[1] < NEAR_NEUTRAL_C


def _is_saturated(cluster: ColorCluster) -> bool:
    return hex_to_oklch(cluster.representative)[1] >= SATURATED_C


def _has_hint(cluster: ColorCluster, *hints: str) -> bool:
    return any(hint in cluster.role_hints for hint in hints)


def _has_custom_prop(cluster: ColorCluster) -> bool:
    return any(hint.startswith("custom-prop:") for hint in cluster.role_hints)


def _declared_map(
    declared: list[DeclaredRoleEvidence] | None,
) -> dict[str, DeclaredRoleEvidence]:
    """role → the declaration for it. Later duplicates lose (capture emits at most one)."""
    out: dict[str, DeclaredRoleEvidence] = {}
    for entry in declared or []:
        out.setdefault(entry.role, entry)
    return out


def _declared_assignment(entry: DeclaredRoleEvidence) -> RoleAssignment:
    return RoleAssignment(entry.value, "declared", f"custom-prop:{entry.property_name}")


def _claim_matching_clusters(
    light: list[ColorCluster], hex_value: str, chosen_ids: set[int]
) -> None:
    """Retire the clusters a declared role has just spoken for.

    A declaration carries no cluster of its own, so without this the very same swatch would
    still be sitting in the pool — free to be crowned the accent, or to reappear as a named
    extra beside the role it already fills.
    """
    for cluster in light:
        if cluster.representative.upper() == hex_value.upper():
            chosen_ids.add(id(cluster))


# --- render-truth election (Phase-1 brand-color overhaul) -----------------------
#
# When the capture carries a pixel census, ELECTION AUTHORITY moves to the
# rendered page: what the visitor actually saw decides which colors win, and
# stylesheet-derived evidence keeps only its naming jobs (declared token roles,
# extras labels). The failure this buries: a focus-ring custom prop out-voting
# the real CTA color because CSS mentioned it more (live finding: apollo.io).

#: A brand/accent candidate must cover at least this share of fold chrome when
#: it arrives via the census alone (buttons/gradients/text carry their own
#: region evidence and only need nonzero rendered presence).
RENDER_BRAND_FLOOR = 0.002
#: The page background family must cover at least this share of the census.
RENDER_PAGE_FLOOR = 0.05
#: Census top-cluster share above which a page reads as near-monochrome — with
#: a large hero canvas that usually means WebGL never painted headless.
MONOCHROME_SHARE = 0.97
LARGE_CANVAS_FRACTION = 0.15


def _truth_family_share(truth: RenderTruth, hex_value: str) -> float:
    lab = hex_to_oklab(hex_value)
    best = 0.0
    for cl in list(truth.page_clusters) + list(truth.fold_clusters):
        if oklab_distance(hex_to_oklab(cl.hex), lab) <= MERGE_DISTANCE:
            best = max(best, cl.share)
    return best


def _truth_token_for(truth: RenderTruth, hex_value: str) -> str | None:
    lab = hex_to_oklab(hex_value)
    best, dist = None, MERGE_DISTANCE
    for name, token_hex in truth.resolved_tokens.items():
        d = oklab_distance(hex_to_oklab(token_hex), lab)
        if d <= dist:
            best, dist = name, d
    return best


def _render_truth_candidates(truth: RenderTruth) -> list[dict]:
    """Brand/accent candidates in tier order, deduped perceptually.

    Tier 1: >=2 rendered buttons agree (the CTA color is authoritative even at
    tiny page share). Tier 2: computed gradient stops over large surfaces (a
    census cannot elect a gradient; live finding: sarvam.ai). Tier 3: chromatic
    accent text on >=2 elements. Tier 4: saturated-or-pastel fold-census
    clusters above the floor. Tier 5: a single saturated button (weakest — one
    button proved able to out-rank a token-corroborated hero color, live
    finding: freshcontext.ai).
    """
    candidates: list[dict] = []

    def add(hex_value: str, tier: int, strength: float, why: str) -> None:
        lab = hex_to_oklab(hex_value)
        for cand in candidates:
            if oklab_distance(hex_to_oklab(cand["hex"]), lab) <= MERGE_DISTANCE:
                cand["evidence"].append(why)
                cand["tier"] = min(cand["tier"], tier)
                cand["strength"] += strength
                return
        candidates.append({"hex": hex_value, "tier": tier, "strength": strength, "evidence": [why]})

    for fam in truth.button_families:
        if fam.count >= 2 and hex_to_oklch(fam.hex)[1] >= SATURATED_C and _truth_family_share(truth, fam.hex) > 0:
            add(fam.hex, 1, float(fam.count), f"modal color of {fam.count} rendered buttons")
    for stop in truth.gradient_stops:
        add(stop.hex, 2, stop.area_fraction * 100, f"computed gradient stop over {stop.area_fraction:.0%} of page area")
    for fam in truth.accent_text:
        if fam.count >= 2 and _truth_family_share(truth, fam.hex) > 0:
            add(fam.hex, 3, float(fam.count), f"accent text color on {fam.count} sampled elements")
    for cl in truth.fold_clusters:
        if hex_to_oklch(cl.hex)[1] >= PASTEL_C and cl.share >= RENDER_BRAND_FLOOR:
            add(cl.hex, 4, cl.share * 100, f"{cl.share:.1%} of above-the-fold chrome")
    for fam in truth.button_families:
        if fam.count == 1 and hex_to_oklch(fam.hex)[1] >= SATURATED_C and _truth_family_share(truth, fam.hex) > 0:
            add(fam.hex, 5, 1.0, "modal color of 1 rendered button")

    for cand in candidates:
        token = _truth_token_for(truth, cand["hex"])
        if token:
            cand["evidence"].append(f"token {token}")
    candidates.sort(key=lambda c: (c["tier"], -c["strength"]))
    return candidates


def _measured(hex_value: str, evidence: list[str]) -> RoleAssignment:
    return RoleAssignment(hex_value, "measured", "render:" + "; ".join(evidence))


def _assign_from_render_truth(
    light: list[ColorCluster],
    declared: list[DeclaredRoleEvidence] | None,
    truth: RenderTruth,
) -> LightRoles:
    diagnostics: list[dict] = []
    assignments: dict[str, RoleAssignment] = {}
    stated = _declared_map(declared)
    claimed_hexes: set[str] = set()

    def _visible_declaration(entry: DeclaredRoleEvidence | None, role: str) -> DeclaredRoleEvidence | None:
        """A declaration must also be TRUE: visible somewhere on the rendered page.

        The founder's original ruling, applied to the declared layer itself —
        "even if it is being picked from the CSS, verify it is the color the
        page shows". Live case: apollo.io's declared-role reader crowned
        `--PhoneInputCountryFlag-backgroundColor--loading` (#0000001A, a
        10%-alpha black) as surface.page, which then poisoned the text
        contrast walk. An 8-digit declared value is compared by its opaque
        base; near-zero census presence refuses the declaration loudly.
        """
        if entry is None:
            return None
        base = entry.value[:7]
        if len(entry.value) == 9 and int(entry.value[7:9], 16) < 128:
            diagnostics.append(
                _diag(
                    "LUMI0534",
                    "warning",
                    f"declared {role} ({entry.property_name} = {entry.value}) is mostly "
                    "transparent — not a page-visible color; rendered evidence used",
                )
            )
            return None
        if _truth_family_share(truth, base) <= 0.0:
            diagnostics.append(
                _diag(
                    "LUMI0534",
                    "warning",
                    f"declared {role} ({entry.property_name} = {entry.value}) is not visible "
                    "anywhere on the rendered page; rendered evidence used",
                )
            )
            return None
        return entry

    # 1. page background — declared beats measured, but only a declaration the
    # page actually shows; measured = the computed body bg verified against the
    # census, else the census's own top family.
    declared_page = _visible_declaration(stated.get("surface.page"), "surface.page")
    if declared_page is not None:
        page = _declared_assignment(declared_page)
    elif truth.body_bg and _truth_family_share(truth, truth.body_bg) >= RENDER_PAGE_FLOOR:
        share = _truth_family_share(truth, truth.body_bg)
        page = _measured(truth.body_bg, [f"computed body background; census family covers {share:.0%} of chrome"])
    elif truth.page_clusters:
        top = truth.page_clusters[0]
        page = _measured(top.hex, [f"census top family ({top.share:.0%} of chrome)"])
    else:
        page = RoleAssignment("#FFFFFF", "default", "default:surface.page defaulted")
        diagnostics.append(_diag("LUMI0201", "info", "surface.page defaulted"))
    assignments["surface.page"] = page
    claimed_hexes.add(page.hex.upper())

    # 2. text — declared clears the same AA gate as ever; measured = computed
    # body color, contrast-enforced.
    declared_text = _visible_declaration(stated.get("text.primary"), "text.primary")
    if declared_text is not None and contrast_ratio(declared_text.value, page.hex) < _CONTRAST_MIN:
        diagnostics.append(
            _diag(
                "LUMI0518",
                "warning",
                f"declared text role {declared_text.property_name} ({declared_text.value}) "
                f"cannot be read on the page surface ({page.hex}); rendered evidence used",
            )
        )
        declared_text = None
    if declared_text is not None:
        text = _declared_assignment(declared_text)
    elif truth.body_text:
        text = _measured(truth.body_text, ["computed body text color"])
    else:
        text = RoleAssignment(with_lightness(page.hex, 0.25), "derived", "derived:text.primary(page-25)")
    text = _ensure_contrast_light(text, page.hex, diagnostics)
    assignments["text.primary"] = text
    claimed_hexes.add(text.hex.upper())

    # 3+4. brand and accent — declared keeps its gates; otherwise the tiered
    # rendered-truth candidates. No candidate at all -> the honest teal default
    # plus, when the census smells like a blocked/unpainted capture, a loud
    # needs-review diagnostic instead of a confident fabrication.
    candidates = _render_truth_candidates(truth)

    declared_brand = _visible_declaration(stated.get("surface.brand"), "surface.brand")
    if declared_brand is not None and _is_near_neutral_hex(declared_brand.value):
        diagnostics.append(
            _diag(
                "LUMI0519",
                "warning",
                f"declared brand role {declared_brand.property_name} "
                f"({declared_brand.value}) is a neutral, not a brand color; "
                f"rendered evidence used",
            )
        )
        declared_brand = None
    if declared_brand is not None:
        brand = _declared_assignment(declared_brand)
    elif candidates:
        top = candidates[0]
        brand = _measured(top["hex"], top["evidence"])
    else:
        brand = RoleAssignment(_BRAND_FALLBACK, "default", "default:no brand color found")
        diagnostics.append(_diag("LUMI0203", "warning", "no brand color found — platform teal used"))
        top_share = truth.page_clusters[0].share if truth.page_clusters else 0.0
        if top_share >= MONOCHROME_SHARE:
            canvas_note = (
                f"; a canvas covers {truth.canvas_viewport_fraction:.0%} of the first viewport "
                "(WebGL hero may not have painted headless)"
                if truth.canvas_viewport_fraction >= LARGE_CANVAS_FRACTION
                else ""
            )
            diagnostics.append(
                _diag(
                    "LUMI0531",
                    "warning",
                    "rendered census is near-monochrome "
                    f"({top_share:.0%} one family) — the capture was likely blocked or unpainted{canvas_note}; "
                    "brand kit needs human review",
                )
            )
    assignments["surface.brand"] = brand
    claimed_hexes.add(brand.hex.upper())

    declared_accent = _visible_declaration(stated.get("surface.accent"), "surface.accent")
    if declared_accent is not None and declared_accent.value.upper() == brand.hex.upper():
        declared_accent = None
    elif declared_accent is not None and _is_near_neutral_hex(declared_accent.value):
        diagnostics.append(
            _diag(
                "LUMI0519",
                "warning",
                f"declared accent role {declared_accent.property_name} "
                f"({declared_accent.value}) is a neutral, not an accent color; "
                f"rendered evidence used",
            )
        )
        declared_accent = None
    if declared_accent is not None:
        assignments["surface.accent"] = _declared_assignment(declared_accent)
        claimed_hexes.add(declared_accent.value.upper())
    else:
        brand_h = hex_to_oklch(brand.hex)[2]
        brand_lab = hex_to_oklab(brand.hex)
        for cand in candidates:
            if oklab_distance(hex_to_oklab(cand["hex"]), brand_lab) <= MERGE_DISTANCE:
                continue
            if hue_distance(hex_to_oklch(cand["hex"])[2], brand_h) <= 30.0:
                continue
            assignments["surface.accent"] = _measured(cand["hex"], cand["evidence"])
            claimed_hexes.add(cand["hex"].upper())
            break

    # 5. extras — named swatches from the evidence clusters keep their job (the
    # census has no names); anything already elected stays out.
    extras = [
        c
        for c in light
        if c.representative.upper() not in claimed_hexes
        and (c.name or any(h.startswith("named:") for h in c.role_hints))
    ]
    return LightRoles(assignments=assignments, extras=extras, diagnostics=diagnostics)


def assign_light_roles(
    clusters: list[ColorCluster],
    declared: list[DeclaredRoleEvidence] | None = None,
    render_truth: RenderTruth | None = None,
) -> LightRoles:
    light = [c for c in clusters if c.theme == "light"]
    # Rendered-pixel election when the capture carries a census (website
    # rendered tier). Every other producer — PDFs, uploads, pre-probe bundles —
    # keeps the evidence-cluster election below, unchanged.
    if render_truth is not None and render_truth.page_clusters:
        return _assign_from_render_truth(light, declared, render_truth)
    diagnostics: list[dict] = []
    assignments: dict[str, RoleAssignment] = {}
    chosen_ids: set[int] = set()
    stated = _declared_map(declared)

    # 1. page_bg
    declared_page = stated.get("surface.page")
    if declared_page is not None:
        page = _declared_assignment(declared_page)
        _claim_matching_clusters(light, page.hex, chosen_ids)
    else:
        page_hinted = _first(light, lambda c: _has_hint(c, "page-bg"))
        if page_hinted is not None:
            page = RoleAssignment(page_hinted.representative, "evidence", _pointer(page_hinted), page_hinted)
            chosen_ids.add(id(page_hinted))
        else:
            bright_neutral = _first(
                light,
                lambda c: _is_near_neutral(c) and hex_to_oklch(c.representative)[0] > 0.9,
            )
            if bright_neutral is not None:
                page = RoleAssignment(bright_neutral.representative, "evidence", _pointer(bright_neutral), bright_neutral)
                chosen_ids.add(id(bright_neutral))
            else:
                page = RoleAssignment("#FFFFFF", "default", "default:surface.page defaulted")
                diagnostics.append(_diag("LUMI0201", "info", "surface.page defaulted"))
    assignments["surface.page"] = page

    # 2. text_primary. A DECLARED text color still has to clear the same AA gate the
    # clustered one always has: a site can name `--primary-foreground` (shadcn's INVERSE
    # text) as readily as `--text-color`, and a declaration we cannot read on the page is
    # worse than the heuristic it displaced. Refusal is loud, never silent.
    declared_text = stated.get("text.primary")
    if declared_text is not None and contrast_ratio(declared_text.value, page.hex) < _CONTRAST_MIN:
        diagnostics.append(
            _diag(
                "LUMI0518",
                "warning",
                f"declared text role {declared_text.property_name} ({declared_text.value}) "
                f"cannot be read on the page surface ({page.hex}); clustered evidence used",
            )
        )
        declared_text = None
    if declared_text is not None:
        text = _declared_assignment(declared_text)
        _claim_matching_clusters(light, text.hex, chosen_ids)
    else:
        text_hinted = _first(
            light,
            lambda c: _has_hint(c, "body-text") and contrast_ratio(c.representative, page.hex) >= _CONTRAST_MIN,
        )
        if text_hinted is not None:
            text = RoleAssignment(text_hinted.representative, "evidence", _pointer(text_hinted), text_hinted)
            chosen_ids.add(id(text_hinted))
        else:
            dark_neutral = _last(
                sorted(
                    [c for c in light if _is_near_neutral(c) and c.weight > 0],
                    key=lambda c: (-hex_to_oklch(c.representative)[0],),
                )
            )
            if dark_neutral is not None:
                text = RoleAssignment(dark_neutral.representative, "evidence", _pointer(dark_neutral), dark_neutral)
                chosen_ids.add(id(dark_neutral))
            else:
                derived = with_lightness(page.hex, 0.25)
                text = RoleAssignment(derived, "derived", "derived:text.primary(page-25)")
    text = _ensure_contrast_light(text, page.hex, diagnostics)
    assignments["text.primary"] = text

    # 3. brand. Like the text gate above, a DECLARED brand still has to be the kind of color
    # the role is for. Webflow's Client-First convention names a brand's whole family off one
    # prefix — `--base-color-brand--black`, `--…--green`, `--…--white` — so "the site called
    # it brand" is not on its own evidence that a given member IS the brand. Capture already
    # ranks the family by chroma; if even the most chromatic member is a neutral, the site
    # named a family and not a brand, and clustering (which has always required saturation)
    # is the better answer. Loud, never silent.
    declared_brand = stated.get("surface.brand")
    if declared_brand is not None and _is_near_neutral_hex(declared_brand.value):
        diagnostics.append(
            _diag(
                "LUMI0519",
                "warning",
                f"declared brand role {declared_brand.property_name} "
                f"({declared_brand.value}) is a neutral, not a brand color; "
                f"clustered evidence used",
            )
        )
        declared_brand = None
    if declared_brand is not None:
        brand = _declared_assignment(declared_brand)
        _claim_matching_clusters(light, brand.hex, chosen_ids)
    else:
        brand_hinted = _first(
            light,
            lambda c: _is_saturated(c) and (_has_hint(c, *_SATURATED_HINTS) or _has_custom_prop(c)),
        )
        if brand_hinted is not None:
            brand = RoleAssignment(brand_hinted.representative, "evidence", _pointer(brand_hinted), brand_hinted)
            chosen_ids.add(id(brand_hinted))
        else:
            brand_any = _first(light, _is_saturated)
            if brand_any is not None:
                brand = RoleAssignment(brand_any.representative, "evidence", _pointer(brand_any), brand_any)
                chosen_ids.add(id(brand_any))
            else:
                brand = RoleAssignment(_BRAND_FALLBACK, "default", "default:no brand color found")
                diagnostics.append(_diag("LUMI0203", "warning", "no brand color found — platform teal used"))
    assignments["surface.brand"] = brand

    # 4. accent_secondary. Named clusters are author-labelled swatches destined
    # for the extras list (rule 5), so they are not auto-promoted to accent here;
    # accent auto-selection only considers unnamed saturated evidence.
    # A declared accent that merely restates the brand color is dropped: the kit already
    # carries that hex under its own role, and `surface.accent` exists to be the OTHER one.
    declared_accent = stated.get("surface.accent")
    if declared_accent is not None and declared_accent.value.upper() == brand.hex.upper():
        declared_accent = None
    # The accent is the brand's twin: the clustered path only ever filled it from a saturated
    # cluster, so the same neutrality guard applies for the same reason (`--…-accent--white`
    # is as real a Client-First name as `--…-brand--white`). Smaller blast radius than brand
    # — `surface.accent`, `text.accent`, the `accent.primary` alias — but the identical bug.
    elif declared_accent is not None and _is_near_neutral_hex(declared_accent.value):
        diagnostics.append(
            _diag(
                "LUMI0519",
                "warning",
                f"declared accent role {declared_accent.property_name} "
                f"({declared_accent.value}) is a neutral, not an accent color; "
                f"clustered evidence used",
            )
        )
        declared_accent = None
    if declared_accent is not None:
        assignments["surface.accent"] = _declared_assignment(declared_accent)
        _claim_matching_clusters(light, declared_accent.value, chosen_ids)
    else:
        brand_h = hex_to_oklch(brand.hex)[2]
        accent_cluster = _first(
            light,
            lambda c: _is_saturated(c)
            and id(c) not in chosen_ids
            and c.name is None
            and not any(h.startswith("named:") for h in c.role_hints)
            and hue_distance(hex_to_oklch(c.representative)[2], brand_h) > 30.0,
        )
        if accent_cluster is not None:
            assignments["surface.accent"] = RoleAssignment(
                accent_cluster.representative, "evidence", _pointer(accent_cluster), accent_cluster
            )
            chosen_ids.add(id(accent_cluster))

    # 5. extras — named clusters not otherwise chosen
    extras = [
        c
        for c in light
        if id(c) not in chosen_ids and (c.name or any(h.startswith("named:") for h in c.role_hints))
    ]

    return LightRoles(assignments=assignments, extras=extras, diagnostics=diagnostics)


def _ensure_contrast_light(role: RoleAssignment, bg_hex: str, diagnostics: list[dict]) -> RoleAssignment:
    if contrast_ratio(role.hex, bg_hex) >= _CONTRAST_MIN:
        return role
    original = role.hex
    _, _, h = hex_to_oklch(role.hex)
    c = min(hex_to_oklch(role.hex)[1], 0.02)
    # Walk toward the endpoint (black vs white) that yields more contrast on the
    # page. WCAG luminance, not OKLCH L, decides — saturated mid-L swatches read
    # dark, so probing both ends is more reliable than a lightness threshold.
    direction = -1.0 if contrast_ratio("#000000", bg_hex) >= contrast_ratio("#FFFFFF", bg_hex) else 1.0
    L = hex_to_oklch(role.hex)[0]
    steps = 0
    while 0.0 <= L <= 1.0 and steps < 60:
        L = min(1.0, max(0.0, L + direction * 0.02))
        candidate = with_lch(L, c, h)
        steps += 1
        if contrast_ratio(candidate, bg_hex) >= _CONTRAST_MIN:
            diagnostics.append(
                _diag("LUMI0202", "warning", f"text.primary adjusted for contrast (was {original})")
            )
            return RoleAssignment(candidate, "derived", "derived:text.primary(contrast-adjusted)", role.cluster)
        if L in (0.0, 1.0):
            break
    diagnostics.append(
        _diag("LUMI0202", "warning", f"text.primary adjusted for contrast (was {original})")
    )
    endpoint = 0.0 if direction < 0 else 1.0
    return RoleAssignment(with_lch(endpoint, c, h), "derived", "derived:text.primary(contrast-adjusted)", role.cluster)


# --- dark colorway ---------------------------------------------------------


@dataclass
class DarkColorway:
    values: dict[str, str]           # token path -> hex
    basis: str                       # "captured" | "synthesized"
    diagnostics: list[dict] = field(default_factory=list)


def build_dark_colorway(
    clusters: list[ColorCluster],
    light: LightRoles,
    primary_ramp: dict[str, str],
) -> DarkColorway:
    dark_clusters = [c for c in clusters if c.theme == "dark"]
    if dark_clusters:
        return _capture_dark(dark_clusters, light)
    return _synthesize_dark(light, primary_ramp)


_DARK_PAGE_MAX_L = 0.30


def _capture_dark(dark_clusters: list[ColorCluster], light: LightRoles) -> DarkColorway:
    # dark page_bg = darkest high-weight cluster. If the darkest captured "dark"
    # swatch is not actually dark enough to seat AA text, clamp its lightness
    # down (keeping hue/chroma) so the dark colorway remains usable.
    page = min(dark_clusters, key=lambda c: (hex_to_oklch(c.representative)[0], -c.weight)).representative
    page_L, page_c, page_h = hex_to_oklch(page)
    if page_L > _DARK_PAGE_MAX_L:
        page = with_lch(_DARK_PAGE_MAX_L, page_c, page_h)
    # dark text = lightest cluster with contrast on page
    text_candidates = sorted(dark_clusters, key=lambda c: -hex_to_oklch(c.representative)[0])
    text = text_candidates[0].representative
    for candidate in text_candidates:
        if contrast_ratio(candidate.representative, page) >= _CONTRAST_MIN:
            text = candidate.representative
            break
    text = _ensure_contrast(text, page)
    # brand = highest-weight saturated dark cluster else light brand
    brand_cluster = _first(dark_clusters, _is_saturated)
    brand = brand_cluster.representative if brand_cluster else light.assignments["surface.brand"].hex

    values = _dark_semantic_map(page, text, brand, light)
    return DarkColorway(values=values, basis="captured")


def _synthesize_dark(light: LightRoles, primary_ramp: dict[str, str]) -> DarkColorway:
    brand_hex = light.assignments["surface.brand"].hex
    _, brand_c, brand_h = hex_to_oklch(brand_hex)
    c_d = min(brand_c * 0.25, 0.04)

    page = with_lch(0.18, c_d, brand_h)
    text = _ensure_contrast(with_lch(0.95, min(c_d, 0.02), brand_h), page)

    values: dict[str, str] = {
        "surface.page": page,
        "surface.canvas": with_lch(0.15, c_d, brand_h),
        "surface.card": with_lch(0.22, c_d, brand_h),
        "surface.elevated": with_lch(0.26, c_d, brand_h),
        "surface.muted": with_lch(0.24, c_d, brand_h),
        "surface.brand": primary_ramp["400"],
        "surface.brand.subtle": with_lch(0.28, c_d * 1.5, brand_h),
        "surface.inverse": light.assignments["surface.page"].hex,
        "text.primary": text,
        "text.secondary": with_lch(0.78, min(c_d, 0.02), brand_h),
        "text.muted": with_lch(0.62, min(c_d, 0.02), brand_h),
        "text.inverse": light.assignments["text.primary"].hex,
        "text.brand": primary_ramp["300"],
        "border.subtle": with_lch(0.30, c_d, brand_h),
        "border.default": with_lch(0.38, c_d, brand_h),
        "border.strong": with_lch(0.48, c_d, brand_h),
        "border.brand": primary_ramp["500"],
        "focus.ring": primary_ramp["400"],
    }

    accent = light.assignments.get("surface.accent")
    if accent is not None:
        _, a_c, a_h = hex_to_oklch(accent.hex)
        values["surface.accent"] = with_lch(0.75, a_c, a_h)
        values["text.accent"] = with_lch(0.8, a_c, a_h)
    else:
        values["surface.accent"] = primary_ramp["300"]
        values["text.accent"] = primary_ramp["300"]

    diagnostics = [_diag("LUMI0210", "info", "dark colorway synthesized from light palette")]
    return DarkColorway(values=values, basis="synthesized", diagnostics=diagnostics)


def _dark_semantic_map(page: str, text: str, brand: str, light: LightRoles) -> dict[str, str]:
    _, brand_c, brand_h = hex_to_oklch(brand)
    c_d = min(brand_c * 0.25, 0.04)
    values = {
        "surface.page": page,
        "surface.canvas": with_lch(max(0.05, hex_to_oklch(page)[0] - 0.03), c_d, brand_h),
        "surface.card": with_lch(hex_to_oklch(page)[0] + 0.04, c_d, brand_h),
        "surface.elevated": with_lch(hex_to_oklch(page)[0] + 0.08, c_d, brand_h),
        "surface.muted": with_lch(hex_to_oklch(page)[0] + 0.06, c_d, brand_h),
        "surface.brand": brand,
        "surface.brand.subtle": with_lch(0.28, c_d * 1.5, brand_h),
        "surface.accent": brand,
        "surface.inverse": light.assignments["surface.page"].hex,
        "text.primary": text,
        "text.secondary": with_lch(0.78, min(c_d, 0.02), brand_h),
        "text.muted": with_lch(0.62, min(c_d, 0.02), brand_h),
        "text.inverse": light.assignments["text.primary"].hex,
        "text.brand": brand,
        "text.accent": brand,
        "border.subtle": with_lch(0.30, c_d, brand_h),
        "border.default": with_lch(0.38, c_d, brand_h),
        "border.strong": with_lch(0.48, c_d, brand_h),
        "border.brand": brand,
        "focus.ring": brand,
    }
    return values


def _ensure_contrast(text_hex: str, page_hex: str) -> str:
    """Return a text color that meets AA contrast on `page_hex`, walking the text
    lightness toward whichever end (up to white / down to black) is farther from
    the page lightness. Works whether the captured/synth page is light or dark."""
    if contrast_ratio(text_hex, page_hex) >= _CONTRAST_MIN:
        return text_hex
    _, _, h = hex_to_oklch(text_hex)
    direction = 1.0 if contrast_ratio("#FFFFFF", page_hex) >= contrast_ratio("#000000", page_hex) else -1.0
    c = min(hex_to_oklch(text_hex)[1], 0.02)
    L = hex_to_oklch(text_hex)[0]
    steps = 0
    while 0.0 <= L <= 1.0 and steps < 60:
        L = min(1.0, max(0.0, L + direction * 0.02))
        candidate = with_lch(L, c, h)
        steps += 1
        if contrast_ratio(candidate, page_hex) >= _CONTRAST_MIN:
            return candidate
        if L in (0.0, 1.0):
            break
    return with_lch(1.0 if direction > 0 else 0.0, c, h)


def _first(items, predicate):
    for item in items:
        if predicate(item):
            return item
    return None


def _last(items):
    return items[-1] if items else None


def _diag(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}
