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
import time
from typing import Any

from .geometry import FREEZE_MOTION_FN, normalize_transform, state_targets

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
    background: cut(cs.backgroundColor),
    color: cut(cs.color),
    label_color: host === el ? null : cut(hs.color),
    border_color: cut(cs.borderTopColor),
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
    outline_color: cut(cs.outlineColor),
    outline_width: num(cs.outlineWidth),
    outline_offset: num(cs.outlineOffset),
  };
  if (icon) {
    const is = getComputedStyle(icon);
    look.icon_transform = is.transform === 'none' ? null : cut(is.transform);
    look.icon_color = cut(is.color);
    look.icon_opacity = num(is.opacity);
  }
  return look;
}
"""

#: The element's transitions (its own, its words' and its icon's) and its icon.
MOTION_JS = r"""
(el) => {
""" + _TRANSITIONS_FN + r"""
  const host = (() => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) { if (node.textContent.trim()) return node.parentElement; }
    return el;
  })();
  const icon = el.querySelector('svg, img');
  // A sprite icon (<use href="#id">) is read from a CLONE with each in-page reference replaced
  // by what it points at; an external sprite file (/sprite.svg#id) is left for the cleaner to drop.
  const iconMarkup = (svg) => {
    const copy = svg.cloneNode(true);
    for (const use of Array.from(copy.querySelectorAll('use'))) {
      const ref = use.getAttribute('href') || use.getAttribute('xlink:href') || '';
      const target = ref.startsWith('#') ? document.getElementById(ref.slice(1)) : null;
      if (!target) continue;
      const symbol = target.tagName.toLowerCase() === 'symbol';
      const drawn = symbol
        ? document.createElementNS('http://www.w3.org/2000/svg', 'g') : target.cloneNode(true);
      if (symbol) {
        for (const child of Array.from(target.childNodes)) drawn.appendChild(child.cloneNode(true));
        if (!copy.hasAttribute('viewBox') && target.hasAttribute('viewBox')) {
          copy.setAttribute('viewBox', target.getAttribute('viewBox'));
        }
      }
      use.replaceWith(drawn);
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


async def _force(cdp: Any, root: int, idx: int, classes: list[str]) -> None:
    node = await cdp.send("DOM.querySelector", {"nodeId": root, "selector": f'[data-lumen-probe="{idx}"]'})
    await cdp.send("CSS.forcePseudoState", {"nodeId": node["nodeId"], "forcedPseudoClasses": classes})


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


async def _probe_one(page: Any, cdp: Any, root: int | None, idx: int, deadline: float) -> dict:
    _in_time(deadline)
    handle = await page.locator(f'[data-lumen-probe="{idx}"]').element_handle(timeout=HOVER_TIMEOUT_MS)
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
            await _force(cdp, root, idx, ["hover"])
            hover = await _look(handle)
            await _force(cdp, root, idx, [])
            record["how"] = "forced"
        record["hover"] = look_delta(rest, hover)
        if cdp is not None:
            _in_time(deadline)
            await _force(cdp, root, idx, ["hover", "active"])
            record["pressed"] = look_delta(rest, await _look(handle))
            await _force(cdp, root, idx, [])
            await _pointer_away(page, handle)
            _in_time(deadline)
            await _force(cdp, root, idx, ["focus", "focus-visible"])
            record["focus"] = look_delta(rest, await _look(handle))
            await _force(cdp, root, idx, [])
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
        out.append({
            "kind": "css" if transitions else "scripted",
            "where": str(now.get("where") or "")[:120],
            "from_opacity": prior.get("opacity"),
            "from_transform": prior.get("transform") if prior.get("transform") not in (None, "none") else None,
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
    root: int | None = None
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("DOM.enable")
        await cdp.send("CSS.enable")
        root = (await cdp.send("DOM.getDocument", {"depth": 0}))["root"]["nodeId"]
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
                    result["styles"].append(await _probe_one(page, cdp, root, idx, deadline))
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
