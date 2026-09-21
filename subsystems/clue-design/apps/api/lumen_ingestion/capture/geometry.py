"""Brand-geometry measurement on the live page (design-brief plan, slice 2).

Before this module the kit's ``radii`` / ``stroke_widths`` / ``spacing`` groups
were *fabricated*: a fixed base scale stamped ``derived:radius-scale`` at
confidence 0.6, with ``shadows`` permanently ``{}``. A brand's button shape, card
corners, border weights, elevation language and vertical rhythm were never read
off its own site.

``GEOMETRY_JS`` is the browser-side probe (one ``page.evaluate`` in
``rendered.py``, run *after* the screenshot so its focus-ring pass cannot alter
the captured pixels). It returns a plain JSON harvest — no CSS parsing, no
judgement — and ``parse_geometry`` turns that harvest into the evidence types
that already existed for exactly this purpose (``NumberSample`` /
``ShadowSample``), plus the structured shape records the design-brief agent
reads in slice 3.

Fail-soft by construction: a missing, malformed, or partially-garbage harvest
yields an EMPTY ``GeometryHarvest`` plus a diagnostic — never an exception. The
normalizer then keeps today's derived scale, honestly labelled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..colorspace import hex_alpha
from ..evidence import (
    EvidencePointer,
    GeometryEvidence,
    NumberSample,
    SectionBackground,
    ShadowSample,
    SurfaceShape,
)
from .parse import parse_color_value

# Surfaces above this radius are read as "pill / fully round", never as a scale
# step (a 9999px chip must not become the brand's radius.xl).
PILL_RADIUS_PX = 9999.0
# Border widths above this are decorative slabs, not stroke weights.
_MAX_STROKE_PX = 12.0
# Spacing values outside this band are page-layout accidents, not rhythm.
_MIN_SPACING_PX = 2.0
_MAX_SPACING_PX = 320.0


# The browser-side probe. One expression, evaluated in the page; every number it
# returns is a *used* value read from getComputedStyle, so nothing here needs a
# CSS parser. Bounded on purpose (a 10k-node marketing page must not ship a
# multi-megabyte harvest through the job row).
GEOMETRY_JS = r"""
() => {
  const MAX_PER_CLASS = 60;
  const MAX_SURFACES = 320;
  const MAX_SECTIONS = 40;
  const MAX_FOCUS = 5;

  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
  const r2 = (n) => Math.round(n * 100) / 100;
  const opaque = (v) => (!v || v === 'transparent' || v === 'rgba(0, 0, 0, 0)') ? null : v;
  const notNone = (v) => (!v || v === 'none') ? null : v;

  const CORNERS = [
    'borderTopLeftRadius', 'borderTopRightRadius',
    'borderBottomRightRadius', 'borderBottomLeftRadius',
  ];

  const radiusOf = (cs, w, h) => {
    const base = Math.min(w, h);
    const radius = [];
    let pill = false;
    for (const key of CORNERS) {
      const raw = String(cs[key] || '0px');
      let value = num(raw);
      if (raw.indexOf('%') >= 0) value = (num(raw) / 100) * base;
      if (base > 0 && value >= (base / 2) - 0.5) pill = true;
      radius.push(r2(value));
    }
    return { radius, pill };
  };

  const effectiveBg = (el) => {
    let node = el;
    while (node) {
      const bg = opaque(getComputedStyle(node).backgroundColor);
      if (bg) return bg;
      node = node.parentElement;
    }
    return null;
  };

  const record = (el, cls) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return null;
    const rect = el.getBoundingClientRect();
    const w = rect.width, h = rect.height;
    if (w < 4 || h < 4) return null;
    const rad = radiusOf(cs, w, h);
    const rowGap = (cs.rowGap && cs.rowGap !== 'normal') ? r2(num(cs.rowGap)) : null;
    const colGap = (cs.columnGap && cs.columnGap !== 'normal') ? r2(num(cs.columnGap)) : null;
    return {
      cls: cls,
      tag: el.tagName.toLowerCase(),
      w: r2(w), h: r2(h),
      radius: rad.radius,
      pill: rad.pill,
      border: [cs.borderTopWidth, cs.borderRightWidth, cs.borderBottomWidth, cs.borderLeftWidth]
        .map((v) => r2(num(v))),
      borderStyle: cs.borderTopStyle || null,
      borderColor: opaque(cs.borderTopColor),
      shadow: notNone(cs.boxShadow),
      padding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft]
        .map((v) => r2(num(v))),
      gap: (rowGap === null && colGap === null) ? null : [rowGap, colGap],
      bg: opaque(cs.backgroundColor),
      bgImage: notNone(cs.backgroundImage),
      color: cs.color || null,
      font: cs.fontWeight + ' ' + cs.fontSize + '/' + cs.lineHeight + ' ' + cs.fontFamily,
    };
  };

  // Order is specificity order: the first class that claims an element keeps it,
  // so a <button class="card-cta"> is a button, not a card.
  const CLASSES = [
    ['button', 'button, [role="button"], input[type="submit"], input[type="button"],'
      + ' a[class*="btn"], a[class*="Btn"], a[class*="button"], a[class*="Button"],'
      + ' .btn, .button'],
    ['input', 'input:not([type="submit"]):not([type="button"]):not([type="hidden"])'
      + ':not([type="checkbox"]):not([type="radio"]), textarea, select'],
    ['chip', '[class*="badge"], [class*="Badge"], [class*="chip"], [class*="Chip"],'
      + ' [class*="pill"], [class*="Pill"], [class*="tag"], [class*="Tag"]'],
    ['card', 'article, [class*="card"], [class*="Card"], [class*="tile"], [class*="Tile"],'
      + ' [class*="panel"], [class*="Panel"]'],
    ['nav', 'nav, header, footer'],
    ['divider', 'hr, [role="separator"], [class*="divider"], [class*="Divider"]'],
    ['image', 'img, picture, figure'],
  ];

  const seen = new Set();
  const surfaces = [];
  for (const [cls, selector] of CLASSES) {
    let taken = 0;
    let nodes = [];
    try { nodes = Array.from(document.querySelectorAll(selector)); } catch (e) { nodes = []; }
    for (const el of nodes) {
      if (taken >= MAX_PER_CLASS || surfaces.length >= MAX_SURFACES) break;
      if (seen.has(el)) continue;
      seen.add(el);
      const entry = record(el, cls);
      if (!entry) continue;
      surfaces.push(entry);
      taken += 1;
    }
  }

  // Top-level sections: descend through single-child wrappers so the "sections"
  // are the page's real bands, not one full-height shell div.
  let root = document.querySelector('main') || document.body;
  for (let depth = 0; depth < 4; depth++) {
    const kids = Array.from(root.children).filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
    if (kids.length === 1) { root = kids[0]; continue; }
    break;
  }

  // A band's CONTENT box, not its border box: modern sections abut edge to edge
  // and carry their breathing room on inner wrappers, so the outer boxes alone
  // report every gap as zero.
  const contentBand = (el) => {
    let top = null, bottom = null;
    for (const child of Array.from(el.children)) {
      const r = child.getBoundingClientRect();
      if (r.height <= 0 || r.width <= 0) continue;
      const t = r.top + window.scrollY;
      if (top === null || t < top) top = t;
      if (bottom === null || t + r.height > bottom) bottom = t + r.height;
    }
    return (top === null) ? null : [top, bottom];
  };

  const sections = [];
  const bands = [];
  const sectionEls = [];
  // Every flow child the probe DECLINED to measure, and why (clone-fidelity F2 wave W1).
  // Without this the band sequence is a subsequence of the root's children with no record of
  // what was removed, so a page that hides one of several same-class sections leaves the
  // harvest ambiguous — and ambiguity costs the whole page its geometry. The browser is the
  // only thing that can answer "is this hidden?", so it answers here, once, compactly.
  const skipped = [];
  let truncated = false;
  const noteSkip = (el, reason) => {
    if (skipped.length >= MAX_SECTIONS) return;
    skipped.push({
      tag: el.tagName.toLowerCase(),
      id: el.getAttribute('id'),
      classes: el.getAttribute('class'),
      reason: reason,
    });
  };
  for (const el of Array.from(root.children)) {
    if (sections.length >= MAX_SECTIONS) { truncated = true; noteSkip(el, 'cap'); continue; }
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') { noteSkip(el, 'hidden'); continue; }
    const rect = el.getBoundingClientRect();
    if (rect.height < 40 || rect.width < innerWidth * 0.5) { noteSkip(el, 'small'); continue; }
    const bgImage = notNone(cs.backgroundImage);
    const top = rect.top + window.scrollY;
    sections.push({
      index: sections.length,
      tag: el.tagName.toLowerCase(),
      // The band's IDENTITY and its ABSOLUTE TOP (clone-fidelity F2.1). The color consumers
      // need neither, but the section harvest needs both: `id`/`class` are what let a stored
      // band be matched back to an element in a re-parse of the stored html, and `top` is what
      // turns a band into a crop of the stored screenshot. Read through getAttribute because
      // `className` is not a string on an SVG root.
      id: el.getAttribute('id'),
      classes: el.getAttribute('class'),
      top: r2(top),
      bg: effectiveBg(el),
      bgImage: bgImage,
      gradient: bgImage ? /gradient\(/i.test(bgImage) : false,
      height: r2(rect.height),
      padding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft]
        .map((v) => r2(num(v))),
    });
    bands.push(contentBand(el) || [top, top + rect.height]);
    sectionEls.push(el);
  }

  const gaps = [];
  for (let i = 1; i < bands.length; i++) {
    const gap = bands[i][0] - bands[i - 1][1];
    if (gap > 0) gaps.push(r2(gap));
  }

  // The rhythm inside each band: the vertical paddings and margins of the
  // full-width blocks a section stacks. This is where a site's real section
  // spacing lives once its bands abut.
  const RHYTHM_PER_SECTION = 24;
  const rhythm = [];
  for (const el of sectionEls) {
    let taken = 0;
    const walk = (node, depth) => {
      if (depth > 3) return;
      for (const child of Array.from(node.children)) {
        if (taken >= RHYTHM_PER_SECTION) return;
        const r = child.getBoundingClientRect();
        if (r.height < 8 || r.width < innerWidth * 0.3) continue;
        const cs = getComputedStyle(child);
        const values = [cs.paddingTop, cs.paddingBottom, cs.marginTop, cs.marginBottom]
          .map((v) => r2(num(v)));
        if (values.some((v) => v > 0)) { rhythm.push(values); taken += 1; }
        walk(child, depth + 1);
      }
    };
    walk(el, 0);
  }

  // Focus rings, where reachable: programmatic focus, read, restore.
  const focus = [];
  const previous = document.activeElement;
  let focusables = [];
  try {
    focusables = Array.from(
      document.querySelectorAll('a[href], button, input, select, textarea')
    ).slice(0, MAX_FOCUS);
  } catch (e) { focusables = []; }
  for (const el of focusables) {
    try {
      el.focus({ preventScroll: true });
      const cs = getComputedStyle(el);
      focus.push({
        outlineWidth: r2(num(cs.outlineWidth)),
        outlineStyle: cs.outlineStyle || null,
        outlineColor: opaque(cs.outlineColor),
        outlineOffset: r2(num(cs.outlineOffset)),
        shadow: notNone(cs.boxShadow),
      });
      el.blur();
    } catch (e) { /* an element that refuses focus simply contributes nothing */ }
  }
  try {
    if (previous && previous.focus) previous.focus({ preventScroll: true });
  } catch (e) { /* restoring focus is best-effort */ }

  // Measure the browser's initial font independently of author/inherited styles.
  // The probe runs after the frozen DOM and screenshot are collected; remove it
  // immediately so no transient measurement node becomes source material.
  let initialFontPx = null;
  const fontProbe = document.createElement('span');
  try {
    fontProbe.style.cssText = 'all:initial!important;font-size:medium!important;'
      + 'position:fixed!important;visibility:hidden!important;pointer-events:none!important';
    document.documentElement.appendChild(fontProbe);
    initialFontPx = num(getComputedStyle(fontProbe).fontSize) || null;
  } finally { fontProbe.remove(); }

  return {
    initial_font_px: initialFontPx,
    root_font_px: num(getComputedStyle(document.documentElement).fontSize),
    url: location.href,
    viewport: innerWidth,
    surfaces: surfaces,
    sections: sections,
    skipped: skipped,
    truncated: truncated,
    gaps: gaps,
    rhythm: rhythm,
    focus: focus,
  };
}
"""


def captured_font_context(raw: object) -> dict[str, float]:
    """Bounded browser measurements retained for later fragment reconstruction."""
    if not isinstance(raw, dict):
        return {}
    return {
        key: float(value)
        for key in ("initial_font_px", "root_font_px")
        if isinstance(value := raw.get(key), (int, float))
        and not isinstance(value, bool) and 0 < value <= 256
    }


@dataclass
class GeometryHarvest:
    """Everything one page's measurement pass contributes to the evidence bundle."""

    numbers: list[NumberSample] = field(default_factory=list)
    shadows: list[ShadowSample] = field(default_factory=list)
    surfaces: list[SurfaceShape] = field(default_factory=list)
    background_sequence: list[SectionBackground] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)

    @property
    def measured(self) -> bool:
        return bool(self.numbers or self.shadows or self.surfaces)

    def evidence(self) -> GeometryEvidence:
        return GeometryEvidence(
            surfaces=list(self.surfaces),
            background_sequence=list(self.background_sequence),
        )


def parse_geometry(raw: object, *, page_url: str) -> GeometryHarvest:
    """Turn one page's raw harvest into evidence. Never raises."""
    harvest = GeometryHarvest()
    if raw is None:
        return harvest
    if not isinstance(raw, dict):
        harvest.diagnostics.append(_diag("geometry harvest was not an object; skipped"))
        return harvest

    url = str(raw.get("url") or page_url or "")
    try:
        surfaces = [s for s in _list(raw.get("surfaces")) if isinstance(s, dict)]
        sections = [s for s in _list(raw.get("sections")) if isinstance(s, dict)]
        focus = [f for f in _list(raw.get("focus")) if isinstance(f, dict)]

        for entry in surfaces:
            _read_surface(entry, url, harvest)
        _read_sections(sections, _list(raw.get("gaps")), url, harvest)
        _read_rhythm(_list(raw.get("rhythm")), url, harvest)
        # Component variants first, focus rings appended after them — both are
        # shape records, and `_read_focus` extends the same list.
        harvest.surfaces.extend(_cluster_shapes(surfaces, url))
        _read_focus(focus, url, harvest)
    except Exception as error:  # noqa: BLE001 — measurement must never fail an ingest
        harvest.diagnostics.append(_diag(f"geometry harvest could not be read: {error}"))
        return GeometryHarvest(diagnostics=harvest.diagnostics)

    return harvest


# --- surfaces ------------------------------------------------------------------


def _read_surface(entry: dict, url: str, harvest: GeometryHarvest) -> None:
    cls = str(entry.get("cls") or "surface")
    pointer_for = lambda what: _pointer(url, what)  # noqa: E731 — one-line locator helper

    # Radii: distinct corner values, so a uniformly-rounded card contributes one
    # observation and an asymmetric one contributes each distinct corner.
    pill = bool(entry.get("pill"))
    for value in _distinct(_numbers(entry.get("radius"))):
        if value <= 0:
            continue
        measured = PILL_RADIUS_PX if pill else value
        harvest.numbers.append(
            NumberSample(
                kind="radius",
                value=measured,
                role_hints=_radius_hints(cls),
                pointer=pointer_for(f"{cls} border-radius"),
            )
        )

    # Border widths: only when the border is actually drawn.
    style = str(entry.get("borderStyle") or "none").lower()
    if style not in ("none", "hidden"):
        for value in _distinct(_numbers(entry.get("border"))):
            if not 0 < value <= _MAX_STROKE_PX:
                continue
            harvest.numbers.append(
                NumberSample(
                    kind="stroke_width",
                    value=value,
                    role_hints=_stroke_hints(cls),
                    pointer=pointer_for(f"{cls} border-width"),
                )
            )

    for value in _distinct(_numbers(entry.get("padding"))):
        if not _MIN_SPACING_PX <= value <= _MAX_SPACING_PX:
            continue
        harvest.numbers.append(
            NumberSample(
                kind="spacing",
                value=value,
                role_hints=_padding_hints(cls),
                pointer=pointer_for(f"{cls} padding"),
            )
        )

    for value in _distinct(_numbers(entry.get("gap"))):
        if not _MIN_SPACING_PX <= value <= _MAX_SPACING_PX:
            continue
        harvest.numbers.append(
            NumberSample(
                kind="spacing",
                value=value,
                role_hints=["gap", cls],
                pointer=pointer_for(f"{cls} gap"),
            )
        )

    for shadow in _parse_box_shadow(entry.get("shadow"), pointer_for(f"{cls} box-shadow")):
        harvest.shadows.append(shadow)


def _radius_hints(cls: str) -> list[str]:
    if cls in ("button", "card", "input", "image", "chip"):
        # `badge` is the kit's own name for the chip radius role.
        return ["badge" if cls == "chip" else cls]
    return [cls]


def _stroke_hints(cls: str) -> list[str]:
    if cls == "divider":
        return ["divider"]
    if cls in ("card", "button", "input"):
        return [cls]
    return [cls]


def _padding_hints(cls: str) -> list[str]:
    """Component padding, hinted by its surface class.

    Deliberately NOT hinted `section` or `gap` — those two are the normalizer's
    LAYOUT family (`scales._LAYOUT_HINTS`). A button's 13.5px inner padding is a
    true measurement, but it is the shape of a component, not a rung of the
    page's scale; it reaches the kit through `space.card.padding` and the shape
    records instead.
    """
    return ["padding", cls]


# --- sections ------------------------------------------------------------------


def _read_sections(
    sections: list[dict], gaps: list, url: str, harvest: GeometryHarvest
) -> None:
    for index, entry in enumerate(sections):
        padding = _numbers(entry.get("padding"))
        vertical = [padding[i] for i in (0, 2) if i < len(padding)]
        horizontal = [padding[i] for i in (1, 3) if i < len(padding)]
        for value in _distinct(vertical):
            if not _MIN_SPACING_PX <= value <= _MAX_SPACING_PX:
                continue
            harvest.numbers.append(
                NumberSample(
                    kind="spacing",
                    value=value,
                    role_hints=["section"],
                    pointer=_pointer(url, "section vertical padding"),
                )
            )
        for value in _distinct(horizontal):
            if not _MIN_SPACING_PX <= value <= _MAX_SPACING_PX:
                continue
            harvest.numbers.append(
                NumberSample(
                    kind="spacing",
                    value=value,
                    role_hints=["margin"],
                    pointer=_pointer(url, "section horizontal padding"),
                )
            )
        harvest.background_sequence.append(
            SectionBackground(
                index=index,
                background=_hex(entry.get("bg")),
                gradient=bool(entry.get("gradient")),
                has_image=bool(entry.get("bgImage")),
                height_px=_float(entry.get("height")),
                pointer=_pointer(url, f"section {index} ({entry.get('tag') or 'div'})"),
            )
        )

    for value in _numbers(gaps):
        if not _MIN_SPACING_PX <= value <= _MAX_SPACING_PX:
            continue
        harvest.numbers.append(
            NumberSample(
                kind="spacing",
                value=value,
                role_hints=["section"],
                pointer=_pointer(url, "section gap"),
            )
        )


def _read_rhythm(rhythm: list, url: str, harvest: GeometryHarvest) -> None:
    """The vertical rhythm inside the bands: block paddings + margins."""
    for row in rhythm:
        for value in _distinct(_numbers(row)):
            if not _MIN_SPACING_PX <= value <= _MAX_SPACING_PX:
                continue
            harvest.numbers.append(
                NumberSample(
                    kind="spacing",
                    value=value,
                    role_hints=["section", "rhythm"],
                    pointer=_pointer(url, "section rhythm"),
                )
            )


# --- focus rings ---------------------------------------------------------------


def _read_focus(focus: list[dict], url: str, harvest: GeometryHarvest) -> None:
    for index, entry in enumerate(focus):
        width = _float(entry.get("outlineWidth"))
        style = str(entry.get("outlineStyle") or "none").lower()
        if style in ("none", "hidden") or not 0 < width <= _MAX_STROKE_PX:
            continue
        harvest.numbers.append(
            NumberSample(
                kind="stroke_width",
                value=width,
                role_hints=["focus"],
                pointer=_pointer(url, "focus ring outline-width"),
            )
        )
        harvest.surfaces.append(
            SurfaceShape(
                surface="focus_ring",
                variant=f"outline.{index + 1}",
                fill="ghost",
                border_width_px=[width],
                border_style=style,
                border_color=_hex(entry.get("outlineColor")),
                shadow=_text(entry.get("shadow")),
                pointer=_pointer(url, "focus ring"),
            )
        )


# --- shape records (slice 3's component recipes) --------------------------------

_SHAPE_SURFACES = ("button", "card", "input", "chip", "nav", "divider", "image")


def _cluster_shapes(surfaces: list[dict], url: str) -> list[SurfaceShape]:
    """Group measured elements into visual variants.

    The grouping key is purely structural — fill kind, radius, border weight,
    shadow, background — so "primary / secondary / ghost" falls out of what the
    page actually draws rather than from a guess about intent.
    """
    groups: dict[tuple, dict] = {}
    for entry in surfaces:
        cls = str(entry.get("cls") or "")
        if cls not in _SHAPE_SURFACES:
            continue
        radius = _numbers(entry.get("radius"))
        border = _numbers(entry.get("border"))
        bg = _hex(entry.get("bg"))
        style = str(entry.get("borderStyle") or "none").lower()
        has_border = style not in ("none", "hidden") and any(v > 0 for v in border)
        fill = "solid" if bg else ("outline" if has_border else "ghost")
        key = (
            cls,
            fill,
            tuple(radius),
            bool(entry.get("pill")),
            tuple(border),
            _text(entry.get("shadow")),
            bg,
        )
        group = groups.get(key)
        if group is None:
            groups[key] = {"entry": entry, "fill": fill, "count": 1}
        else:
            group["count"] += 1

    ordered = sorted(
        groups.items(), key=lambda item: (-item[1]["count"], _order_key(item[0]))
    )
    seats: dict[tuple[str, str], int] = {}
    shapes: list[SurfaceShape] = []
    for key, group in ordered:
        cls, fill = key[0], key[1]
        seat = seats.get((cls, fill), 0) + 1
        seats[(cls, fill)] = seat
        entry = group["entry"]
        shapes.append(
            SurfaceShape(
                surface=cls,  # type: ignore[arg-type]
                variant=f"{fill}.{seat}",
                count=int(group["count"]),
                fill=fill,  # type: ignore[arg-type]
                radius_px=_numbers(entry.get("radius")),
                pill=bool(entry.get("pill")),
                padding_px=_numbers(entry.get("padding")),
                border_width_px=_numbers(entry.get("border")),
                border_style=_text(entry.get("borderStyle")),
                border_color=_hex(entry.get("borderColor")),
                shadow=_text(entry.get("shadow")),
                background=_hex(entry.get("bg")),
                text_color=_hex(entry.get("color")),
                font=_text(entry.get("font")),
                pointer=_pointer(url, f"{cls} {fill} variant"),
            )
        )
    return shapes


def _order_key(key: tuple) -> str:
    return "|".join(str(part) for part in key)


# --- box-shadow -----------------------------------------------------------------


def _parse_box_shadow(raw: object, pointer: EvidencePointer) -> list[ShadowSample]:
    """Split a computed ``box-shadow`` into per-layer samples.

    Chrome serializes computed box-shadows color-first (``rgba(…) 0px 4px 6px
    -1px``); an author-order string (``0 4px 6px rgba(…)``) parses the same way
    because the color token is located by shape, not by position. ``inset``
    layers are skipped: an inner shadow is a surface treatment, not the brand's
    elevation language.
    """
    if not isinstance(raw, str) or not raw.strip():
        return []
    samples: list[ShadowSample] = []
    for layer in _split_layers(raw):
        text = layer.strip()
        if not text or "inset" in text.lower():
            continue
        color_text, rest = _take_color(text)
        lengths = _lengths(rest)
        if len(lengths) < 2:
            continue
        hex_value = parse_color_value(color_text, {}) if color_text else "#000000"
        if not hex_value:
            continue
        alpha = hex_alpha(hex_value)
        if alpha <= 0.0:
            continue
        x, y = lengths[0], lengths[1]
        blur = lengths[2] if len(lengths) > 2 else 0.0
        spread = lengths[3] if len(lengths) > 3 else 0.0
        if blur <= 0.0 and abs(x) <= 0.0 and abs(y) <= 0.0 and spread <= 0.0:
            continue
        samples.append(
            ShadowSample(
                x=x,
                y=y,
                blur=blur,
                spread=spread,
                color=hex_value[:7],
                opacity=round(alpha, 4),
                pointer=pointer,
            )
        )
    return samples


def _split_layers(raw: str) -> list[str]:
    layers: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            layers.append("".join(current))
            current = []
            continue
        current.append(ch)
    layers.append("".join(current))
    return layers


def _take_color(text: str) -> tuple[str | None, str]:
    lowered = text.lower()
    for prefix in ("rgba(", "rgb(", "hsla(", "hsl("):
        start = lowered.find(prefix)
        if start < 0:
            continue
        end = text.find(")", start)
        if end < 0:
            continue
        return text[start : end + 1], text[:start] + text[end + 1 :]
    for token in text.split():
        if token.startswith("#"):
            return token, text.replace(token, " ", 1)
    return None, text


def _lengths(text: str) -> list[float]:
    values: list[float] = []
    for token in text.replace("px", " ").split():
        try:
            value = float(token)
        except ValueError:
            continue
        if math.isfinite(value):
            values.append(round(value, 2))
    return values


# --- small helpers --------------------------------------------------------------


def _pointer(url: str, what: str) -> EvidencePointer:
    """The website provenance idiom already used by the evidence fixtures:
    ``website:<page url> :: <what was measured>``."""
    return EvidencePointer(source="website", locator=f"{url} :: {what}")


def _diag(message: str) -> dict:
    return {"code": "LUMI0510", "severity": "warning", "message": message}


def _list(value: object) -> list:
    return list(value) if isinstance(value, list) else []


def _numbers(value: object) -> list[float]:
    out: list[float] = []
    for item in _list(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        number = float(item)
        if math.isfinite(number):
            out.append(round(number, 2))
    return out


def _distinct(values: list[float]) -> list[float]:
    seen: list[float] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    number = float(value)
    return round(number, 2) if math.isfinite(number) else 0.0


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:240] or None


def _hex(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return parse_color_value(value, {})
