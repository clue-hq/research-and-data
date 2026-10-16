"""Per-style interaction states, motion and behaviour, measured on the live page (Wave 2 A9).

The geometry probe (`geometry.py`) reads each measured element at REST. A brand's buttons, links and
cards are also what they do: the colour a button takes under the pointer, the press, the keyboard
focus ring, the disabled look, the transition that carries them, an arrow that slides. This pass
measures those after the screenshot, the captured HTML and the rest harvest, so it can never change
a captured pixel.

How each state is reached (offline probe, 2026-10-12, Playwright 1.61 and patchright 1.61.2,
recorded in docs/superpowers/plans/2026-10-12-lane-a-a9-brand-fidelity-rewrite.md):

* hover — a real pointer move (`locator.hover`), so CSS `:hover` and script-driven hovers (a
  mouseenter handler toggling a class) both show; when the element is covered or cannot take the
  pointer, CDP `CSS.forcePseudoState(['hover'])` reads the CSS hover, and the record says "forced";
* pressed — `CSS.forcePseudoState(['hover', 'active'])`: the real `:active` cascade with no click,
  so no link is followed and no handler runs;
* focus — `CSS.forcePseudoState(['focus', 'focus-visible'])` with the pointer moved away; a browser
  default ring (`outline-style: auto`) is recorded as that, never as a brand value;
* disabled — the element's own `disabled` (form controls) or `aria-disabled="true"`, set and
  restored, so the site's `:disabled` / `[aria-disabled]` rules show.

The element and its descendants are held still first, by the one motion rule the geometry probe
also reads with (`geometry.FREEZE_MOTION_FN`), through the CSSOM and the Web Animations API (a page
CSP blocks neither): transitions are switched off, so each read is the state's end look; an animation
that ends, CSS or script-made, is held one millisecond before its end, so an entrance still running
(or still in its delay) is read where it ends, never from its authored start, and the page's end
handlers do not run; one that never ends is switched off (CSS) or cancelled (script), so no frame of
it (a pulsing CTA's halo, a wiggling icon) is read as a state and the rest look is the authored static
look (the animation is page motion, captured by the geometry probe). The rest look is read after
that. A script-driven hover is read every 50 ms until two reads agree. Inline styles and animations
are given back afterwards.

Bounded like the geometry probe, for the same reason (an ingestion is one job among many): at most
`STATE_TARGET_CAPS` styles, an 8-second wall clock for the whole pass (checked before each style and
each state; a style it cuts short is dropped whole), a 1.2-second pointer attempt, a 0.6-second
settle, 240 characters per value, 8 transitions per element. Each element is resolved once, and read
through that handle: a handle never waits, so an element the page replaced after it was marked (a
carousel, a re-hydrating framework, a menu re-rendering on hover) fails at once instead of holding
the pass for the page's default timeout. Fail-soft: a target that throws is skipped; without a CDP
session the pointer hovers are still measured; nothing here can fail a capture.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

from .geometry import COLOR_FN, FREEZE_MOTION_FN, normalize_transform, state_targets

#: The whole pass's wall clock. Ten buttons and a dozen other styles take about 2.5 s at the
#: measured 100-140 ms each; the rest is headroom for covered elements (1.2 s each).
STATE_PASS_DEADLINE_S = 8.0
HOVER_TIMEOUT_MS = 1200
SETTLE_LIMIT_S = 0.6
SETTLE_STEP_S = 0.05

_TRANSITIONS_FN = r"""
  const transitionsOf = (node) => {
    if (!node) return [];
    const cs = getComputedStyle(node);
    const split = (value) => {
      const out = []; let depth = 0; let current = '';
      for (const ch of String(value || '')) {
        if (ch === '(') depth += 1;
        if (ch === ')') depth -= 1;
        if (ch === ',' && depth === 0) { out.push(current.trim()); current = ''; } else current += ch;
      }
      if (current.trim()) out.push(current.trim());
      return out;
    };
    const ms = (v) => String(v).trim().endsWith('ms') ? parseFloat(v) : parseFloat(v) * 1000;
    const props = split(cs.transitionProperty), durs = split(cs.transitionDuration);
    const eases = split(cs.transitionTimingFunction), delays = split(cs.transitionDelay);
    const out = [];
    props.forEach((property, i) => {
      const duration = ms(durs[i % durs.length] || '0s');
      if (!(duration > 0)) return;
      out.push({ property: property.slice(0, 60), duration_ms: Math.round(duration),
        easing: (eases[i % eases.length] || 'ease').slice(0, 120), delay_ms: Math.round(ms(delays[i % delays.length] || '0s')) });
    });
    return out.slice(0, 8);
  };
"""

#: One element's look: its box, the element that paints its words, and its icon. An element that has
#: left the page throws: a handle evaluates a detached element without complaint, and every value it
#: computes there is empty.
LOOK_JS = r"""
(el) => {
  if (!el.isConnected) throw new Error('the element has left the page');
""" + COLOR_FN + r"""
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? Math.round(n * 100) / 100 : null; };
  const cut = (v) => (v === undefined || v === null || v === '') ? null : String(v).slice(0, 240);
  const host = (() => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) { if (node.textContent.trim()) return node.parentElement; }
    return el;
  })();
  const icon = el.querySelector('svg, img');
  const cs = getComputedStyle(el);
  const hs = getComputedStyle(host);
  const look = {
    background: hexOf(cs.backgroundColor),
    color: hexOf(cs.color),
    label_color: host === el ? null : hexOf(hs.color),
    border_color: hexOf(cs.borderTopColor),
    border_width: [cs.borderTopWidth, cs.borderRightWidth, cs.borderBottomWidth, cs.borderLeftWidth].map(num),
    border_style: cut(cs.borderTopStyle),
    radius: [cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomRightRadius, cs.borderBottomLeftRadius].map(num),
    padding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].map(num),
    height: num(el.getBoundingClientRect().height),
    gap: cs.columnGap === 'normal' ? null : num(cs.columnGap),
    font_family: cut(hs.fontFamily), font_size: num(hs.fontSize), font_weight: num(hs.fontWeight),
    line_height: hs.lineHeight === 'normal' ? null : num(hs.lineHeight),
    letter_spacing: hs.letterSpacing === 'normal' ? 0 : num(hs.letterSpacing),
    text_transform: cut(hs.textTransform),
    decoration_line: cut(hs.textDecorationLine),
    decoration_thickness: cut(hs.textDecorationThickness),
    underline_offset: cut(hs.textUnderlineOffset),
    box_shadow: cs.boxShadow === 'none' ? null : cut(cs.boxShadow),
    opacity: num(cs.opacity),
    transform: cs.transform === 'none' ? null : cut(cs.transform),
    filter: cs.filter === 'none' ? null : cut(cs.filter),
    cursor: cut(cs.cursor),
    outline_style: cut(cs.outlineStyle),
    outline_color: hexOf(cs.outlineColor),
    outline_width: num(cs.outlineWidth),
    outline_offset: num(cs.outlineOffset),
  };
  if (icon) {
    const is = getComputedStyle(icon);
    look.icon_transform = is.transform === 'none' ? null : cut(is.transform);
    look.icon_color = hexOf(is.color);
    look.icon_opacity = num(is.opacity);
  }
  return look;
}
"""

#: The element's transitions (its own, its words' and its icon's) and its icon.
MOTION_JS = r"""
(el) => {
""" + _TRANSITIONS_FN + COLOR_FN + r"""
  const host = (() => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) { if (node.textContent.trim()) return node.parentElement; }
    return el;
  })();
  const icon = el.querySelector('svg, img');
  // The icon as the page drew it (S6-2, S6-10). The cleaner keeps drawing attributes only — never
  // `class` or `style` — so the paint CSS gave the icon is written onto a copy as attributes: on each
  // element where it differs from its parent's, on the root where it differs from the initial value.
  // A fill or stroke equal to the icon's text colour is written `currentColor`, so the icon keeps
  // following the label's colour in every state and on every surface. A paint through `url(…)` is
  // left out (the cleaner refuses it). A sprite `<use>` becomes a group carrying the use's own paint,
  // scaled from the symbol's viewBox into the box the use drew (preserveAspectRatio honoured), so the
  // drawing keeps its size and place; the symbol's children keep their own attributes.
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const PAINT = ['fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit',
    'fill-rule', 'clip-rule', 'opacity', 'fill-opacity', 'stroke-opacity'];
  const INITIAL = { stroke: 'none', 'stroke-width': '1', 'stroke-linecap': 'butt', 'stroke-linejoin': 'miter',
    'stroke-miterlimit': '4', 'fill-rule': 'nonzero', 'clip-rule': 'nonzero', opacity: '1', 'fill-opacity': '1',
    'stroke-opacity': '1' };
  const r3 = (n) => Math.round(n * 1000) / 1000;
  const paintValue = (prop, raw, textColor) => {
    const v = String(raw || '').trim();
    if (!v) return null;
    if (prop === 'fill' || prop === 'stroke') {
      if (v === 'none') return 'none';
      if (v.indexOf('url(') >= 0) return null;
      const hex = hexOf(v);
      if (!hex) return null;
      return hex === textColor ? 'currentColor' : hex;
    }
    if (prop === 'stroke-width' || prop === 'stroke-miterlimit' || prop.endsWith('opacity')) {
      const n = parseFloat(v);
      return Number.isFinite(n) ? String(r3(n)) : null;
    }
    return v;
  };
  const writePaint = (src, dst, parentSrc, textColor) => {
    const cs = getComputedStyle(src);
    const ps = parentSrc ? getComputedStyle(parentSrc) : null;
    for (const prop of PAINT) {
      const value = paintValue(prop, cs.getPropertyValue(prop), textColor);
      if (value === null) continue;
      if (ps ? paintValue(prop, ps.getPropertyValue(prop), textColor) === value : INITIAL[prop] === value) continue;
      dst.setAttribute(prop, value);
    }
  };
  const lengthOf = (el, name, ref) => {
    const raw = el.getAttribute(name);
    if (raw === null || String(raw).trim() === '') return null;
    const n = parseFloat(raw);
    if (!Number.isFinite(n)) return null;
    return String(raw).trim().endsWith('%') ? (n / 100) * ref : n;
  };
  const viewBoxOf = (el) => {
    const vb = String(el.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
    return vb.length === 4 && vb.every(Number.isFinite) && vb[2] > 0 && vb[3] > 0 ? vb : null;
  };
  const useTransform = (use, target, symbol, outer) => {
    const x = lengthOf(use, 'x', outer.w) || 0, y = lengthOf(use, 'y', outer.h) || 0;
    const vb = symbol ? viewBoxOf(target) : null;
    if (!vb) return (x || y) ? `translate(${r3(x)} ${r3(y)})` : null;
    const w = lengthOf(use, 'width', outer.w), h = lengthOf(use, 'height', outer.h);
    const W = w === null ? outer.w : w, H = h === null ? outer.h : h;
    const par = String(target.getAttribute('preserveAspectRatio') || 'xMidYMid meet').trim().split(/\s+/);
    let sx = W / vb[2], sy = H / vb[3], tx = x - vb[0] * sx, ty = y - vb[1] * sy;
    if (par[0] !== 'none') {
      const s = par[1] === 'slice' ? Math.max(sx, sy) : Math.min(sx, sy);
      const fx = par[0].indexOf('xMid') >= 0 ? 0.5 : par[0].indexOf('xMax') >= 0 ? 1 : 0;
      const fy = par[0].indexOf('YMid') >= 0 ? 0.5 : par[0].indexOf('YMax') >= 0 ? 1 : 0;
      sx = sy = s;
      tx = x + (W - vb[2] * s) * fx - vb[0] * s;
      ty = y + (H - vb[3] * s) * fy - vb[1] * s;
    }
    if (r3(sx) === 1 && r3(sy) === 1 && r3(tx) === 0 && r3(ty) === 0) return null;
    return `translate(${r3(tx)} ${r3(ty)}) scale(${r3(sx)} ${r3(sy)})`;
  };
  const iconMarkup = (svg) => {
    const copy = svg.cloneNode(true);
    const textColor = hexOf(getComputedStyle(svg).color);
    const sources = [svg, ...Array.from(svg.querySelectorAll('*'))];
    const copies = [copy, ...Array.from(copy.querySelectorAll('*'))];
    sources.forEach((src, i) => { if (copies[i]) writePaint(src, copies[i], i === 0 ? null : src.parentElement, textColor); });
    const root = svg.getRootNode();
    const byId = (id) => (root && root.getElementById ? root.getElementById(id) : null) || svg.ownerDocument.getElementById(id);
    for (const use of Array.from(copy.querySelectorAll('use'))) {
      const ref = use.getAttribute('href') || use.getAttribute('xlink:href') || '';
      const target = ref.startsWith('#') ? byId(ref.slice(1)) : null;
      if (!target) continue;
      const symbol = target.tagName.toLowerCase() === 'symbol';
      if (symbol && !copy.hasAttribute('viewBox') && target.hasAttribute('viewBox')) {
        copy.setAttribute('viewBox', target.getAttribute('viewBox'));
      }
      const box = svg.getBoundingClientRect();
      const vb = viewBoxOf(copy);
      const outer = vb ? { w: vb[2], h: vb[3] }
        : { w: lengthOf(svg, 'width', box.width) || box.width, h: lengthOf(svg, 'height', box.height) || box.height };
      const group = document.createElementNS(SVG_NS, 'g');
      for (const prop of PAINT) if (use.hasAttribute(prop)) group.setAttribute(prop, use.getAttribute(prop));
      const transform = useTransform(use, target, symbol, outer);
      if (transform) group.setAttribute('transform', transform);
      const drawn = symbol ? Array.from(target.childNodes).map((child) => child.cloneNode(true)) : [target.cloneNode(true)];
      for (const child of drawn) group.appendChild(child);
      use.replaceWith(group);
    }
    return copy.outerHTML.slice(0, 8192);
  };
  const glyphs = /[→›»↗➔⟶←‹«↘]/;
  const text = (el.textContent || '').trim();
  let info = null;
  if (icon) {
    const r = icon.getBoundingClientRect(), b = el.getBoundingClientRect();
    const svg = icon.tagName.toLowerCase() === 'svg';
    info = { kind: svg ? 'svg' : 'img', position: (r.left - b.left) < (b.right - r.right) ? 'start' : 'end',
      width: Math.round(r.width * 100) / 100, height: Math.round(r.height * 100) / 100,
      svg: svg ? iconMarkup(icon) : null };
  } else if (text && glyphs.test(text.slice(-1))) {
    info = { kind: 'glyph', position: 'end', glyph: text.slice(-1) };
  } else if (text && glyphs.test(text.slice(0, 1))) {
    info = { kind: 'glyph', position: 'start', glyph: text.slice(0, 1) };
  }
  return { transitions: transitionsOf(el), label_transitions: host === el ? [] : transitionsOf(host),
    icon_transitions: transitionsOf(icon), icon: info };
}
"""

#: The element held still by the motion rule the geometry probe shares (`FREEZE_MOTION_FN`): an
#: animation that ends is held at its end frame, one that never ends is switched off or cancelled,
#: transitions are off. Returns each node's prior inline values and the animations it held or
#: cancelled, kept in the page (`evaluate_handle`) for `THAW_JS`, which gives them back.
FREEZE_JS = r"""
(el) => {
""" + FREEZE_MOTION_FN + r"""
  return freezeMotion(el);
}
"""

THAW_JS = r"""
(el, priors) => {
""" + FREEZE_MOTION_FN + r"""
  thawMotion(el, priors);
}
"""

DISABLE_JS = r"""
(el) => {
  const formish = ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'FIELDSET'].includes(el.tagName);
  if (formish) { const was = el.disabled; el.disabled = true; return { formish, was }; }
  const was = el.getAttribute('aria-disabled');
  el.setAttribute('aria-disabled', 'true');
  return { formish, was };
}
"""

ENABLE_JS = r"""
(el, prior) => {
  if (prior.formish) { el.disabled = prior.was; return; }
  if (prior.was === null) el.removeAttribute('aria-disabled'); else el.setAttribute('aria-disabled', prior.was);
}
"""

#: Read BEFORE the page is scrolled (rendered.py): elements that start hidden or shifted and carry
#: motion — the candidates for an entrance reveal. Read-only; elements are re-found by child path.
REVEAL_BEFORE_JS = r"""
() => {
  const out = [];
  const body = document.body;
  if (!body) return out;
  const els = Array.from(body.querySelectorAll('*')).slice(0, 6000);
  const pathOf = (el) => {
    const parts = []; let node = el;
    while (node && node !== body) { const p = node.parentElement; if (!p) return null; parts.unshift(Array.prototype.indexOf.call(p.children, node)); node = p; }
    return parts;
  };
  const ms = (v) => String(v).trim().endsWith('ms') ? parseFloat(v) : parseFloat(v) * 1000;
  for (const el of els) {
    if (out.length >= 24) break;
    const r = el.getBoundingClientRect();
    if (r.width * r.height < 1000) continue;
    if (!(el.textContent || '').trim() && !el.querySelector('img, svg, picture, video')) continue;
    const cs = getComputedStyle(el);
    const moving = String(cs.transitionDuration).split(',').some((d) => ms(d) > 0) || (cs.animationName && cs.animationName !== 'none');
    const hidden = parseFloat(cs.opacity) < 0.05;
    const shifted = cs.transform !== 'none' && moving;
    if (!hidden && !shifted) continue;
    if (out.some((o) => o.el.contains(el))) continue;
    const path = pathOf(el);
    if (!path) continue;
    out.push({ el, path, tag: el.tagName.toLowerCase(), opacity: parseFloat(cs.opacity), transform: cs.transform,
      classes: (el.getAttribute('class') || '').slice(0, 240) });
  }
  return out.map(({ el, ...rest }) => rest);
}
"""

REVEAL_AFTER_JS = r"""
(items) => {
""" + _TRANSITIONS_FN + r"""
  return items.map((item) => {
    let node = document.body;
    for (const i of item.path) { node = node && node.children[i]; }
    if (!node) return null;
    const cs = getComputedStyle(node);
    const cls = node.getAttribute('class');
    return { tag: node.tagName.toLowerCase(), opacity: parseFloat(cs.opacity), transform: cs.transform,
      classes: (cls || '').slice(0, 240), transitions: transitionsOf(node),
      where: (node.tagName.toLowerCase() + (node.id ? '#' + node.id : '') + (cls ? '.' + String(cls).trim().split(/\s+/)[0] : '')).slice(0, 120) };
  });
}
"""

#: Motion a published page cannot carry: canvases, playing videos, and inline styles a script keeps
#: rewriting. Recorded as notes (what and where), never reproduced.
SCRIPTED_JS = r"""
async () => {
  const describe = (el) => {
    const cls = el.getAttribute('class');
    return (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (cls ? '.' + String(cls).trim().split(/\s+/)[0] : '')).slice(0, 120);
  };
  const notes = [];
  for (const el of Array.from(document.querySelectorAll('canvas'))) {
    const r = el.getBoundingClientRect();
    if (r.width * r.height >= 10000 && notes.length < 4) notes.push({ kind: 'canvas', where: describe(el) });
  }
  for (const el of Array.from(document.querySelectorAll('video'))) {
    if ((el.autoplay || !el.paused) && notes.length < 8) notes.push({ kind: 'video', where: describe(el) });
  }
  const els = Array.from(document.querySelectorAll('body *')).slice(0, 4000);
  const before = els.map((el) => el.getAttribute('style') || '');
  await new Promise((resolve) => setTimeout(resolve, 300));
  let moved = 0;
  els.forEach((el, i) => {
    if (moved >= 4) return;
    const now = el.getAttribute('style') || '';
    if (now !== before[i] && /transform|opacity|translate|scale|rotate/.test(now)) { notes.push({ kind: 'scripted', where: describe(el) }); moved += 1; }
  });
  return notes.slice(0, 12);
}
"""

_STRING_REMOVALS = ("box_shadow", "transform", "filter")
_OUTLINE = ("outline_style", "outline_color", "outline_width", "outline_offset")


def look_delta(rest: dict, other: dict) -> dict:
    """Only what changed from rest. Values that are not brand choices are dropped."""
    out = {key: value for key, value in other.items() if rest.get(key) != value}
    # A value the state removes is recorded as "none", so "no shadow on hover" survives storage.
    for key in _STRING_REMOVALS:
        if key in out and out[key] is None and rest.get(key) is not None:
            out[key] = "none"
    # A border colour with no drawn border is the text colour leaking through `currentColor`.
    if not any((width or 0) > 0 for width in (other.get("border_width") or [])):
        out.pop("border_color", None)
    style = other.get("outline_style")
    if style in (None, "none") or style == "auto":
        for key in _OUTLINE:
            out.pop(key, None)
        if style == "auto" and rest.get("outline_style") != "auto":
            out["browser_focus_ring"] = True
    elif rest.get("outline_style") in (None, "none", "auto"):
        # A ring this state draws is recorded whole: an undrawn outline still computes a width
        # (Chromium reports `medium`, 3px) and a colour (`currentColor`), so a ring that matches
        # either would otherwise lose it to the comparison above.
        out.update({key: other.get(key) for key in _OUTLINE})
    out.pop("height", None)  # layout, not a state
    return out


async def _look(handle: Any) -> dict:
    """One read of the element's look (LOOK_JS) with its transforms as evidence (`normalize_transform`):
    a sub-pixel leftover is no transform, and no transform is `None`, the way LOOK_JS reports a computed
    `none`. Every rest and state read goes through here, so `look_delta` compares the values the
    evidence keeps (a state that differs from rest only by a leftover has no transform delta)."""
    look = await handle.evaluate(LOOK_JS)
    for key in ("transform", "icon_transform"):
        if look.get(key) is not None:
            value = normalize_transform(look[key])
            look[key] = None if value == "none" else value
    return look


async def _settled(handle: Any) -> dict:
    deadline = time.monotonic() + SETTLE_LIMIT_S
    previous = await _look(handle)
    while time.monotonic() < deadline:
        await asyncio.sleep(SETTLE_STEP_S)
        current = await _look(handle)
        if current == previous:
            return current
        previous = current
    return previous


#: Finds a probed element wherever GEOMETRY_JS found it — the document, an open shadow root, a
#: same-origin iframe — for CDP, whose DOM.querySelector stops at shadow and frame boundaries.
_DEEP_FIND_JS = r"""
(() => {
  const selector = %s;
  const roots = [document];
  for (let i = 0; i < roots.length && roots.length < 64; i++) {
    const hit = roots[i].querySelector(selector);
    if (hit) return hit;
    for (const el of roots[i].querySelectorAll('*')) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      if (el.tagName === 'IFRAME') { try { const d = el.contentDocument; if (d) roots.push(d); } catch (e) {} }
    }
  }
  return null;
})()
"""


async def _probe_handle(page: Any, idx: int) -> Any:
    """The probed element's handle, in whichever frame holds it (Playwright's CSS engine pierces open
    shadow roots within a frame)."""
    selector = f'[data-lumen-probe="{idx}"]'
    for frame in page.frames:
        handle = await frame.query_selector(selector)
        if handle is not None:
            return handle
    return await page.locator(selector).element_handle(timeout=HOVER_TIMEOUT_MS)


async def _node_id(cdp: Any, idx: int) -> int:
    found = await cdp.send("Runtime.evaluate", {"expression": _DEEP_FIND_JS % json.dumps(f'[data-lumen-probe="{idx}"]')})
    object_id = (found.get("result") or {}).get("objectId")
    if not object_id:
        raise LookupError(f"probe {idx} not found for a forced state")
    return (await cdp.send("DOM.requestNode", {"objectId": object_id}))["nodeId"]


async def _force(cdp: Any, idx: int, classes: list[str]) -> None:
    await cdp.send("CSS.forcePseudoState", {"nodeId": await _node_id(cdp, idx), "forcedPseudoClasses": classes})


async def _pointer_away(page: Any, handle: Any) -> None:
    box = await handle.bounding_box()
    viewport = page.viewport_size or {"width": 1440, "height": 900}
    point = (0, 0)
    if box and box["x"] <= 0 <= box["x"] + box["width"] and box["y"] <= 0 <= box["y"] + box["height"]:
        point = (viewport["width"] - 1, viewport["height"] - 1)
    await page.mouse.move(*point)


class _PastDeadline(Exception):
    """The pass's wall clock ran out inside a style: the style is dropped whole, never half-measured."""


def _in_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise _PastDeadline


async def _restore(handle: Any, script: str, prior: Any) -> None:
    """Undo a change to the element. An element that has left the page needs no restoring, and a failed
    restore must not replace the error that ended the read."""
    try:
        await handle.evaluate(script, prior)
    except Exception:  # noqa: BLE001
        pass


async def _probe_one(page: Any, cdp: Any, idx: int, deadline: float) -> dict:
    _in_time(deadline)
    handle = await _probe_handle(page, idx)
    motion = await handle.evaluate(MOTION_JS)  # reads the transitions, so before they are frozen
    priors = await handle.evaluate_handle(FREEZE_JS)  # the animations themselves, so the thaw finds them
    try:
        rest = await _look(handle)
        record: dict[str, Any] = {"idx": idx, "motion": motion, "rest": rest}
        _in_time(deadline)
        try:
            await handle.hover(timeout=HOVER_TIMEOUT_MS)
            hover = await _settled(handle)
            record["how"] = "pointer"
        except Exception:  # noqa: BLE001 — covered or pointer-proof: read the CSS hover
            if cdp is None:
                raise
            await _force(cdp, idx, ["hover"])
            hover = await _look(handle)
            await _force(cdp, idx, [])
            record["how"] = "forced"
        record["hover"] = look_delta(rest, hover)
        if cdp is not None:
            try:
                _in_time(deadline)
                await _force(cdp, idx, ["hover", "active"])
                record["pressed"] = look_delta(rest, await _look(handle))
                await _force(cdp, idx, [])
                await _pointer_away(page, handle)
                _in_time(deadline)
                await _force(cdp, idx, ["focus", "focus-visible"])
                record["focus"] = look_delta(rest, await _look(handle))
                await _force(cdp, idx, [])
            except LookupError:
                pass  # a probe CDP cannot reach keeps its rest and hover reads
        await _pointer_away(page, handle)
        _in_time(deadline)
        prior = await handle.evaluate(DISABLE_JS)
        try:
            record["disabled"] = look_delta(rest, await _look(handle))
        finally:
            await _restore(handle, ENABLE_JS, prior)
    finally:
        await _restore(handle, THAW_JS, priors)
        with contextlib.suppress(Exception):
            await priors.dispose()
    return record


def _reveals(before: list, after: list) -> list[dict]:
    out: list[dict] = []
    for prior, now in zip(before, after):
        if not isinstance(prior, dict) or not isinstance(now, dict) or now.get("tag") != prior.get("tag"):
            continue
        settled = (now.get("opacity") or 0) >= 0.95 and normalize_transform(now.get("transform")) in (None, "none")
        if not settled:
            continue
        transitions = [
            t for t in now.get("transitions") or []
            if t.get("property") in ("all", "opacity", "transform", "translate")
        ]
        added = sorted(set(str(now.get("classes") or "").split()) - set(str(prior.get("classes") or "").split()))
        start = normalize_transform(prior.get("transform"))  # rounded like every transform the evidence keeps
        out.append({
            "kind": "css" if transitions else "scripted",
            "where": str(now.get("where") or "")[:120],
            "from_opacity": prior.get("opacity"),
            "from_transform": start if start not in (None, "none") else None,
            "transitions": transitions,
            "trigger": [name[:40] for name in added[:3]],
        })
    return out


def _diag(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}


async def probe_states(page: Any, geometry: dict, *, reveal_before: list | None, diagnostics: list[dict]) -> dict:
    """Measure every targeted style's states, the page's reveals and its scripted motion. Never raises."""
    result: dict[str, Any] = {"styles": [], "reveals": [], "scripted": [], "truncated": False}
    surfaces = geometry.get("surfaces") if isinstance(geometry, dict) else None
    targets = state_targets(surfaces if isinstance(surfaces, list) else [])
    cdp = None
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("DOM.enable")
        await cdp.send("CSS.enable")
        # DOM.requestNode needs the document requested; depth 0 is enough (it pushes the path to the node itself).
        await cdp.send("DOM.getDocument", {"depth": 0})
    except Exception as error:  # noqa: BLE001
        cdp = None
        diagnostics.append(_diag("LUMI0543", "warning", f"pressed and focus states not measured (no CDP session): {error}"))
    deadline = time.monotonic() + STATE_PASS_DEADLINE_S
    try:
        for _key, candidates in targets:
            if time.monotonic() >= deadline:
                result["truncated"] = True
                break
            for idx in candidates:
                try:
                    result["styles"].append(await _probe_one(page, cdp, idx, deadline))
                    break
                except _PastDeadline:  # the style is dropped whole; the check above ends the pass
                    result["truncated"] = True
                    break
                except Exception:  # noqa: BLE001 — try the style's next element
                    continue
        if reveal_before:
            try:
                result["reveals"] = _reveals(reveal_before, await page.evaluate(REVEAL_AFTER_JS, reveal_before))
            except Exception:  # noqa: BLE001
                pass
        try:
            result["scripted"] = await page.evaluate(SCRIPTED_JS)
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await page.mouse.move(0, 0)
        except Exception:  # noqa: BLE001
            pass
        if cdp is not None:
            try:
                await cdp.detach()
            except Exception:  # noqa: BLE001
                pass
    if result["truncated"]:
        diagnostics.append(_diag(
            "LUMI0544", "info",
            f"interaction states measured for {len(result['styles'])} of {len(targets)} styles before the "
            f"{STATE_PASS_DEADLINE_S:.0f}s limit",
        ))
    return result
