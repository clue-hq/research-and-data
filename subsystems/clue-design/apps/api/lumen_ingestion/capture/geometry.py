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

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from ..colorspace import hex_alpha
from ..evidence import (
    EvidencePointer,
    GeometryEvidence,
    MeasuredAnimation,
    MeasuredReveal,
    MeasuredStyle,
    MotionEvidence,
    NumberSample,
    ScriptedMotion,
    SectionBackground,
    ShadowSample,
    StyleIcon,
    StyleLook,
    StyleTransition,
    SurfaceShape,
)
from .motion import clean_icon_svg
from .parse import parse_color_value

# Surfaces above this radius are read as "pill / fully round", never as a scale
# step (a 9999px chip must not become the brand's radius.xl).
PILL_RADIUS_PX = 9999.0
# Border widths above this are decorative slabs, not stroke weights.
_MAX_STROKE_PX = 12.0
# Spacing values outside this band are page-layout accidents, not rhythm.
_MIN_SPACING_PX = 2.0
_MAX_SPACING_PX = 320.0
#: Text links and navigation items (Wave 2 A9). Measured for their states and motion only: they add
#: no number samples (the kit's scales stay what they were) and no shape records (the brief agent's
#: evidence stays what it was).
STYLE_ONLY_SURFACES = ("link", "nav_link")
#: The classes whose styles the state pass measures, and how many styles of each it tries. Buttons
#: carry the looks the agent chooses from, so they get the most; the rest are drawn by the kit.
STATE_TARGET_CAPS = {"button": 10, "link": 2, "nav_link": 2, "card": 4, "chip": 2, "input": 2, "image": 2}
#: Elements of one style tried before its states are given up (the first may be covered).
_CANDIDATES_PER_STYLE = 3


#: One motion rule for every look read, shared by this probe's `record` and the state pass's
#: FREEZE_JS / THAW_JS (states.py), over an element and its first 15 descendants in document order.
#: Each running animation the element carries (`getAnimations()`) is one of three kinds:
#: - a transition: switched off with `transition: none`, so a running one reads its end value;
#: - a CSS animation (it has an `animationName`): one that ends is HELD at its end frame, so a CTA
#:   fading in from an authored `opacity: 0` is read opaque and in place, even while its entrance or its
#:   delay is still running; one that never ends is switched off with `animation: none` on its node, so
#:   the read is the authored static look and no frame of it (a pulse's halo, a wiggle) is taken for the
#:   element's own;
#: - any other animation, made by a script through the Web Animations API (`el.animate`, what Framer
#:   Motion and similar libraries produce): one that ends is held at its end frame; one that never ends
#:   is cancelled for the read (its effect is removed, so the read is the static look).
#: Holding is `pause()` at one millisecond from the end the animation is heading to (`endTime - 1`, or
#: `1` for one playing backwards, which ends on its time-0 frame): the end frame, without reaching the
#: end, so the page's `animationend` / `finish` handlers never run during a capture (a
#: handler that swaps a class would otherwise change the look between this probe, which names the
#: style, and the state pass, which reads its states). An animation that has already finished shows its
#: end frame and is left alone. An animation that cannot be held falls back: a CSS one is switched off
#: with its node, a script one is cancelled.
#: `thawMotion` gives back what the freeze changed: the inline values (and a `style` attribute the
#: freeze created), and each held or cancelled animation at the time it was at, running again unless it
#: was paused. The freeze returns the animations themselves, so the thaw touches exactly those, and a
#: held one the page has cancelled in the meantime stays cancelled.
FREEZE_MOTION_FN = r"""
  const motionNodes = (el) => {
    const nodes = [el];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT);
    while (nodes.length < 16 && walker.nextNode()) nodes.push(walker.currentNode);
    return nodes;
  };
  const endOf = (animation) => (animation.effect ? animation.effect.getComputedTiming().endTime : Infinity);
  const freezeMotion = (el) => motionNodes(el).map((node) => {
    const prior = { attribute: node.hasAttribute('style'), values: {}, held: [], cancelled: [] };
    const moving = node.getAnimations().filter((animation) => !(animation instanceof CSSTransition)
      && animation.transitionProperty === undefined && animation.playState !== 'finished');
    let off = moving.some((animation) => animation.animationName !== undefined && endOf(animation) === Infinity);
    for (const animation of moving) {
      const css = animation.animationName !== undefined;
      if (css && off) continue;  // switched off below, with the node's other CSS animations
      const was = [animation, animation.currentTime, animation.playState === 'paused'];
      if (endOf(animation) !== Infinity) {
        prior.held.push(was);
        try {  // one millisecond from the end it is heading to: time 0 when it plays backwards
          animation.pause(); animation.currentTime = animation.playbackRate < 0 ? 1 : endOf(animation) - 1; continue;
        } catch (e) {
          if (css) { off = true; continue; }
        }
      }
      animation.cancel();
      prior.cancelled.push(was);
    }
    for (const name of off ? ['transition', 'animation'] : ['transition']) {
      prior.values[name] = [node.style.getPropertyValue(name), node.style.getPropertyPriority(name)];
      node.style.setProperty(name, 'none', 'important');
    }
    return prior;
  });
  const resume = ([animation, time, paused]) => {
    if (time !== null) animation.currentTime = time;
    if (!paused) animation.play();
  };
  const thawMotion = (el, priors) => motionNodes(el).forEach((node, i) => {
    const prior = priors[i];
    if (!prior) return;
    for (const [name, [value, priority]] of Object.entries(prior.values)) {
      if (value) node.style.setProperty(name, value, priority); else node.style.removeProperty(name);
    }
    // A style attribute the freeze created goes again once it is empty (an icon's markup is read later).
    if (!prior.attribute && node.getAttribute('style') === '') node.removeAttribute('style');
    prior.held.forEach((was) => { if (was[0].playState !== 'idle') resume(was); });
    prior.cancelled.forEach(resume);
  });
"""


#: The in-page colour reader every probe shares (review finding S6-3): each colour is drawn on a 1×1
#: canvas and read back, so oklch(), lab(), color(display-p3 …) and any later CSS colour syntax arrive
#: as the sRGB hex the page actually paints (Chromium clips out-of-gamut channels; so does this).
#: `behindOf` composites every background from an element up to the first opaque one — through slots,
#: shadow roots and same-origin iframes — onto the canvas default (white), and is null when a
#: background image sits in between: text on a photo or a gradient has no one colour behind it.
#: A hostile page can redefine canvas methods; it can only mislead its own capture.
COLOR_FN = r"""
  const __colorCanvas = document.createElement('canvas');
  __colorCanvas.width = 1; __colorCanvas.height = 1;
  const __colorCtx = __colorCanvas.getContext('2d', { willReadFrequently: true });
  const __colorCache = new Map();
  const __hex2 = (n) => n.toString(16).padStart(2, '0').toUpperCase();
  const hexOf = (value) => {
    if (value === undefined || value === null) return null;
    const text = String(value).trim();
    if (!text || text === 'none' || /^currentcolor$/i.test(text)) return null;
    if (__colorCache.has(text)) return __colorCache.get(text);
    let out = null;
    if (CSS.supports('color', text)) {
      __colorCtx.clearRect(0, 0, 1, 1);
      __colorCtx.fillStyle = '#000';
      __colorCtx.fillStyle = text;
      __colorCtx.fillRect(0, 0, 1, 1);
      const d = __colorCtx.getImageData(0, 0, 1, 1).data;
      out = d[3] === 0 ? '#00000000' : '#' + __hex2(d[0]) + __hex2(d[1]) + __hex2(d[2]) + (d[3] === 255 ? '' : __hex2(d[3]));
    }
    __colorCache.set(text, out);
    return out;
  };
  const alphaOf = (hex) => (!hex ? 0 : hex.length === 9 ? parseInt(hex.slice(7, 9), 16) / 255 : 1);
  const paints = (hex) => alphaOf(hex) > 0;
  const over = (top, bottom) => {
    const a = alphaOf(top);
    const ch = (i) => Math.round(parseInt(top.slice(i, i + 2), 16) * a + parseInt(bottom.slice(i, i + 2), 16) * (1 - a));
    return '#' + __hex2(ch(1)) + __hex2(ch(3)) + __hex2(ch(5));
  };
  const composedParent = (node) => {
    if (node.assignedSlot) return node.assignedSlot;
    if (node.parentElement) return node.parentElement;
    const root = node.getRootNode ? node.getRootNode() : null;
    if (root && root.host) return root.host;
    try {
      const view = node.ownerDocument && node.ownerDocument.defaultView;
      return view && view.frameElement ? view.frameElement : null;
    } catch (e) { return null; }
  };
  const behindOf = (el) => {
    const layers = [];
    for (let node = el; node; node = composedParent(node)) {
      if (node.nodeType !== 1) continue;
      const ncs = getComputedStyle(node);
      if (ncs.backgroundImage && ncs.backgroundImage !== 'none') return null;
      const fill = hexOf(ncs.backgroundColor);
      if (paints(fill)) { layers.push(fill); if (alphaOf(fill) >= 1) break; }
    }
    let base = '#FFFFFF';
    if (layers.length && alphaOf(layers[layers.length - 1]) >= 1) base = layers.pop();
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base;
  };
"""


# The browser-side probe. One expression, evaluated in the page; every number it
# returns is a *used* value read from getComputedStyle, so nothing here needs a
# CSS parser. Bounded on purpose (a 10k-node marketing page must not ship a
# multi-megabyte harvest through the job row).
GEOMETRY_JS = r"""
() => {
""" + FREEZE_MOTION_FN + COLOR_FN + r"""
  const MAX_PER_CLASS = 60;
  const MAX_SURFACES = 320;
  const MAX_SECTIONS = 40;
  const MAX_FOCUS = 5;

  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
  const r2 = (n) => Math.round(n * 100) / 100;
  // A colour that paints, as hex; null for none or fully transparent (S6-7: `rgba(255, 255, 255, 0)`
  // is no fill, whatever its channels say).
  const opaque = (v) => { const h = hexOf(v); return paints(h) ? h : null; };
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

  // A candidate's look is read with its motion held still (FREEZE_MOTION_FN), and its inline styles
  // and animations are given back right after the read.
  const record = (el, cls) => {
    const priors = freezeMotion(el);
    try { return look(el, cls); } finally { thawMotion(el, priors); }
  };
  const look = (el, cls) => {
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
      color: hexOf(cs.color),
      font: cs.fontWeight + ' ' + cs.fontSize + '/' + cs.lineHeight + ' ' + cs.fontFamily,
      disabled: el.matches(':disabled, [aria-disabled="true"]'),
    };
  };

  const BUTTON = 'button, [role="button"], input[type="submit"], input[type="button"],'
    + ' a[class*="btn"], a[class*="Btn"], a[class*="button"], a[class*="Button"],'
    + ' .btn, .button';
  const CTA_CONTENT = 'img, picture, video, h1, h2, h3, h4, h5, h6, p, ul, ol, table, article';
  // An anchor holding block content or taller than a control (a card wrapped in <a>, a menu entry
  // with a heading and a line of text) is neither a button nor a text link.
  const blockAnchor = (el) => !!el.querySelector(CTA_CONTENT) || el.getBoundingClientRect().height > 80;
  // Tailwind-style CTAs carry no button class; a short padded anchor with a visible box — a fill
  // that stands out or a full border — is a button.
  const ctaAnchor = (el) => {
    const cs = getComputedStyle(el);
    if (num(cs.paddingLeft) + num(cs.paddingRight) < 12) return false;
    const text = (el.textContent || '').trim();
    const h = el.getBoundingClientRect().height;
    if (text.length < 1 || text.length > 40 || h < 20) return false;
    if (blockAnchor(el)) return false;
    const fill = opaque(cs.backgroundColor);
    const behind = behindOf(el.parentElement) || '#FFFFFF';  // the canvas default
    if (fill && over(fill, behind) !== behind) return true;
    if ((cs.backgroundImage || '').indexOf('gradient(') >= 0) return true;
    return ['Top', 'Right', 'Bottom', 'Left'].every((side) => (
      num(cs['border' + side + 'Width']) >= 1 && !!opaque(cs['border' + side + 'Color'])
      && !['none', 'hidden'].includes(cs['border' + side + 'Style'])));
  };

  // Order is specificity order: the first class that claims an element keeps it,
  // so a <button class="card-cta"> is a button, not a card.
  const CLASSES = [
    ['button', BUTTON + ', a[href]'],
    ['input', 'input:not([type="submit"]):not([type="button"]):not([type="hidden"])'
      + ':not([type="checkbox"]):not([type="radio"]), textarea, select'],
    ['chip', '[class*="badge"], [class*="Badge"], [class*="chip"], [class*="Chip"],'
      + ' [class*="pill"], [class*="Pill"], [class*="tag"], [class*="Tag"]'],
    ['card', 'article, [class*="card"], [class*="Card"], [class*="tile"], [class*="Tile"],'
      + ' [class*="panel"], [class*="Panel"]'],
    ['nav', 'nav, header, footer'],
    ['divider', 'hr, [role="separator"], [class*="divider"], [class*="Divider"]'],
    ['image', 'img, picture, figure'],
    ['nav_link', 'nav a[href], header a[href]'],
    ['link', 'a[href]'],
  ];
  // Text links and navigation items (Wave 2 A9): a link is an inline anchor with words outside the
  // page chrome; a nav item is one inside it. Both are measured for their states and motion only.
  const FILTERS = {
    button: (el) => el.matches(BUTTON) || ctaAnchor(el),
    nav_link: (el) => !!(el.textContent || '').trim() && !blockAnchor(el),
    link: (el) => !!(el.textContent || '').trim() && !el.closest('nav, header, footer') && !blockAnchor(el),
  };

  const seen = new Set();
  const surfaces = [];
  for (const [cls, selector] of CLASSES) {
    let taken = 0;
    let nodes = [];
    try { nodes = Array.from(document.querySelectorAll(selector)); } catch (e) { nodes = []; }
    for (const el of nodes) {
      if (taken >= MAX_PER_CLASS || surfaces.length >= MAX_SURFACES) break;
      if (seen.has(el)) continue;
      if (FILTERS[cls] && !FILTERS[cls](el)) continue;
      seen.add(el);
      const entry = record(el, cls);
      if (!entry) continue;
      entry.idx = surfaces.length;
      surfaces.push(entry);
      // Marked for the state pass (capture/states.py). This probe runs after the screenshot and the
      // captured HTML, so the mark is never part of what was captured.
      try { el.setAttribute('data-lumen-probe', String(entry.idx)); } catch (e) { /* an element that refuses attributes */ }
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

  // The text colour a band carries (Wave 2 A9): its first visible heading or paragraph, so a minted
  // band surface can say what text the seller put on it.
  const inkOf = (el) => {
    const nodes = Array.from(el.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li, blockquote')).slice(0, 40);
    for (const node of nodes) {
      const r = node.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0 || !(node.textContent || '').trim()) continue;
      return opaque(getComputedStyle(node).color);
    }
    return null;
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
      bg: behindOf(el),
      bgImage: bgImage,
      ink: inkOf(el),
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

  // CSS animations running on the page (Wave 2 A9): one entry per distinct animation, bounded. The
  // @keyframes bodies are read from the captured stylesheets in Python (capture/motion.py), which
  // also holds the cross-origin sheets the CSSOM will not show.
  const MAX_ANIMATIONS = 12;
  const animations = new Map();
  for (const el of Array.from(document.querySelectorAll('body *')).slice(0, 6000)) {
    if (animations.size >= MAX_ANIMATIONS) break;
    const cs = getComputedStyle(el);
    if (!cs.animationName || cs.animationName === 'none') continue;
    const key = [cs.animationName, cs.animationDuration, cs.animationTimingFunction,
      cs.animationIterationCount, cs.animationDirection].join('|');
    const found = animations.get(key);
    if (found) { found.count += 1; continue; }
    const cls = el.getAttribute('class');
    animations.set(key, {
      name: cs.animationName.slice(0, 120), duration: cs.animationDuration,
      easing: cs.animationTimingFunction.slice(0, 120), delay: cs.animationDelay,
      iterations: cs.animationIterationCount, direction: cs.animationDirection, fill: cs.animationFillMode,
      where: (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
        + (cls ? '.' + String(cls).trim().split(/\s+/)[0] : '')).slice(0, 120),
      count: 1,
    });
  }

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
    animations: Array.from(animations.values()),
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
    styles: list[MeasuredStyle] = field(default_factory=list)
    motion: MotionEvidence = field(default_factory=MotionEvidence)
    diagnostics: list[dict] = field(default_factory=list)

    @property
    def measured(self) -> bool:
        return bool(self.numbers or self.shadows or self.surfaces)

    def evidence(self) -> GeometryEvidence:
        return GeometryEvidence(
            surfaces=list(self.surfaces),
            background_sequence=list(self.background_sequence),
            styles=list(self.styles),
            motion=self.motion,
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

    # Measured styles and motion (Wave 2 A9) in their own guard: a malformed state record costs
    # these, never the shapes and scales above.
    try:
        states = raw.get("states") if isinstance(raw.get("states"), dict) else None
        harvest.styles = measured_styles(surfaces, states, url)
        harvest.motion = measured_motion(raw, url)
    except Exception as error:  # noqa: BLE001 — measurement must never fail an ingest
        harvest.styles, harvest.motion = [], MotionEvidence()
        harvest.diagnostics.append(_diag(f"measured styles could not be read: {error}"))

    return harvest


# --- surfaces ------------------------------------------------------------------


def _read_surface(entry: dict, url: str, harvest: GeometryHarvest) -> None:
    cls = str(entry.get("cls") or "surface")
    if cls in STYLE_ONLY_SURFACES:
        return
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
                ink=_opaque_hex(entry.get("ink")),
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
    rings: dict[tuple, tuple[float, str, str | None, str | None]] = {}
    for entry in focus:
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
        colour, shadow = _hex(entry.get("outlineColor")), _text(entry.get("shadow"))
        # One record per distinct ring (two focusable elements with the same ring were two records
        # with two numbers before; one name now means one look — founder Q-A9-6).
        rings.setdefault(("focus_ring", "outline", width, style, shadow, colour), (width, style, colour, shadow))
    names = look_names(list(rings))
    for key, (width, style, colour, shadow) in rings.items():
        harvest.surfaces.append(
            SurfaceShape(
                surface="focus_ring",
                variant=names[key],
                fill="ghost",
                border_width_px=[width],
                border_style=style,
                border_color=colour,
                shadow=shadow,
                pointer=_pointer(url, "focus ring"),
            )
        )


# --- shape records (slice 3's component recipes) --------------------------------

_SHAPE_SURFACES = ("button", "card", "input", "chip", "nav", "divider", "image")


def _identity_colour(entry: dict, fill: str) -> str | None:
    """The colour a look is told by: a filled look's fill, an outline's border, a text-only look's text."""
    if fill == "solid":
        return _hex(entry.get("bg"))
    if fill == "outline":
        return _hex(entry.get("borderColor"))
    return _hex(entry.get("color"))


def shape_key(entry: dict) -> tuple:
    """The one grouping key: fill kind, corners, border weight, shadow, background, and the colour the
    look is told by (founder Q-A9-6: an outline's border colour and a text-only look's text colour
    make it another look). A border that paints nothing (Bootstrap's `1px solid transparent`) is no
    border, as in `_rest_look` and the minting."""
    radius = _numbers(entry.get("radius"))
    border = _numbers(entry.get("border"))
    bg = _opaque_hex(entry.get("bg"))
    style = str(entry.get("borderStyle") or "none").lower()
    has_border = (
        style not in ("none", "hidden") and any(v > 0 for v in border) and bool(_opaque_hex(entry.get("borderColor")))
    )
    fill = "solid" if bg else ("outline" if has_border else "ghost")
    return (
        str(entry.get("cls") or ""), fill, tuple(radius), bool(entry.get("pill")), tuple(border),
        _text(entry.get("shadow")), bg, _identity_colour(entry, fill),
    )


def variant_base(fill: str, colour: str | None) -> str:
    """`<fill>.<hex>`: a look's name from the colour it is told by (`solid.047464`)."""
    return f"{fill}.{colour.lstrip('#').lower() if colour else 'none'}"


def _key_digest(key: tuple, width: int) -> str:
    return hashlib.sha1(_order_key(key).encode()).hexdigest()[:width]


def look_names(keys: list[tuple]) -> dict[tuple, str]:
    """Each look's stable name, by its grouping key (`(cls, fill, …, colour)`; founder Q-A9-6).

    `<fill>.<hex>`, plus `.<4 hex>` of the whole key when two looks of one class share it (12 hex in
    the 1-in-65,536 case where two 4-hex suffixes collide). Never a rank, a count or a page order.
    """
    bases = {key: variant_base(key[1], key[-1]) for key in keys}
    shared = Counter((key[0], base) for key, base in bases.items())
    names = {
        key: base if shared[(key[0], base)] == 1 else f"{base}.{_key_digest(key, 4)}"
        for key, base in bases.items()
    }
    taken = Counter((key[0], name) for key, name in names.items())
    return {
        key: f"{bases[key]}.{_key_digest(key, 12)}" if taken[(key[0], name)] > 1 else name
        for key, name in names.items()
    }


def shape_groups(surfaces: list[dict], classes: tuple[str, ...]) -> list[tuple[str, list[dict]]]:
    """`(variant, members)` per look of `classes`, most used first (ties in key order).

    The variant is the look's stable name (`look_names`) — the name the brief's recipes, the
    measured styles and the minted tokens use. The order decides only which styles the state pass
    tries first and the order of the brief's evidence, never a name. `members[0]` is the first element
    measured with that look.
    """
    groups: dict[tuple, list[dict]] = {}
    for entry in surfaces:
        if str(entry.get("cls") or "") in classes:
            groups.setdefault(shape_key(entry), []).append(entry)
    names = look_names(list(groups))
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), _order_key(item[0])))
    return [(names[key], members) for key, members in ordered]


def state_targets(surfaces: list[dict]) -> list[tuple[tuple[str, str], list[int]]]:
    """The styles the state pass measures, buttons first, and the elements to try for each."""
    taken: dict[str, int] = {}
    targets: list[tuple[tuple[str, str], list[int]]] = []
    for variant, members in shape_groups(surfaces, tuple(STATE_TARGET_CAPS)):
        cls = str(members[0].get("cls") or "")
        if taken.get(cls, 0) >= STATE_TARGET_CAPS[cls]:
            continue
        usable = [m for m in members if isinstance(m.get("idx"), int)]
        usable.sort(key=lambda m: bool(m.get("disabled")))  # an enabled element first
        candidates = [int(m["idx"]) for m in usable][:_CANDIDATES_PER_STYLE]
        if candidates:
            taken[cls] = taken.get(cls, 0) + 1
            targets.append(((cls, variant), candidates))
    order = list(STATE_TARGET_CAPS)
    targets.sort(key=lambda item: order.index(item[0][0]))
    return targets


def _cluster_shapes(surfaces: list[dict], url: str) -> list[SurfaceShape]:
    """Group measured elements into visual variants.

    The grouping key is purely structural — fill kind, radius, border weight,
    shadow, background — so "primary / secondary / ghost" falls out of what the
    page actually draws rather than from a guess about intent.
    """
    shapes: list[SurfaceShape] = []
    for variant, members in shape_groups(surfaces, _SHAPE_SURFACES):
        entry = members[0]
        cls = str(entry.get("cls") or "")
        fill = variant.split(".", 1)[0]
        shapes.append(
            SurfaceShape(
                surface=cls,  # type: ignore[arg-type]
                variant=variant,
                count=len(members),
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


#: Bounds the evidence: a real page has 15-25 style variants across these classes.
_MAX_MEASURED_STYLES = 40
_MAX_REVEALS = 6
_LOOK_COLORS = ("background", "color", "label_color", "border_color", "outline_color", "icon_color")
_LOOK_TEXTS = (
    "border_style", "text_transform", "decoration_line", "decoration_thickness", "underline_offset",
    "box_shadow", "transform", "filter", "cursor", "outline_style", "icon_transform",
)
_LOOK_NUMBERS = (
    "height", "gap", "font_size", "font_weight", "line_height", "letter_spacing", "opacity",
    "outline_width", "outline_offset", "icon_opacity",
)
_LOOK_LISTS = ("border_width", "radius", "padding")
#: A colour a state clears (fully transparent), recorded as itself the way a removed shadow is "none".
_CLEARED = "#00000000"
_FONT = re.compile(r"^(\d+)\s+([\d.]+)px/(\S+)\s+(.+)$")


_MATRIX_FUNCTION = re.compile(r"^(matrix|matrix3d)\((.*)\)$")
#: Where each matrix keeps its translation (px, rounded to 2 decimals); every other component is a
#: ratio (rounded to 4).
_TRANSLATION = {"matrix": (4, 5), "matrix3d": (12, 13, 14)}
_IDENTITY = {"matrix": (1, 0, 0, 1, 0, 0), "matrix3d": (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)}


def normalize_transform(value: object) -> object:
    """A computed transform as evidence: a `matrix(…)` / `matrix3d(…)` rounded (ratios to 4 decimals,
    the translation to 2 px) and written as the browser writes numbers (`1`, `0.98`, `-2`), and the
    identity written `none`. Reads that differ only below that precision — an entrance held one
    millisecond before its end leaves `matrix(1, 0, 0, 1, 0, 1.88911e-06)` — are the same value, and an
    identity is no transform. Anything else is returned unchanged."""
    match = _MATRIX_FUNCTION.match(value) if isinstance(value, str) else None
    if not match:
        return value
    kind = match.group(1)
    try:
        numbers = [float(part) for part in match.group(2).split(",")]
    except ValueError:
        return value
    if len(numbers) != len(_IDENTITY[kind]) or not all(math.isfinite(n) for n in numbers):
        return value
    rounded = [round(n, 2 if i in _TRANSLATION[kind] else 4) + 0.0 for i, n in enumerate(numbers)]  # + 0.0: no -0
    if tuple(rounded) == _IDENTITY[kind]:
        return "none"
    return f"{kind}({', '.join(f'{n:.4f}'.rstrip('0').rstrip('.') for n in rounded)})"


def _opaque_hex(value: object) -> str | None:
    """A measured colour, or None when it paints nothing (fully transparent)."""
    hex_value = _hex(value)
    return hex_value if hex_value and hex_alpha(hex_value) > 0 else None


def _family(value: object) -> str | None:
    text = _text(value)
    return text.split(",", 1)[0].strip().strip("\"'") or None if text else None


def _look_fields(look: dict, *, clears: bool = False) -> dict:
    """A probe look (or state delta) as `StyleLook` fields; absent and empty values left out.

    `clears` is for a state's delta: a colour the state makes fully transparent is `#00000000`
    rather than left out, which would read as "unchanged from rest".
    """
    out: dict = {}
    for key in _LOOK_COLORS:
        if key in look:
            out[key] = _opaque_hex(look.get(key))
            if out[key] is None and clears and _hex(look.get(key)):
                out[key] = _CLEARED
    for key in _LOOK_TEXTS:
        if key in look:
            out[key] = _text(look.get(key))
    for key in _LOOK_NUMBERS:
        value = look.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            out[key] = round(float(value), 2)
    for key in _LOOK_LISTS:
        if key in look:
            out[key] = _numbers(look.get(key))
    if "font_family" in look:
        out["font_family"] = _family(look.get("font_family"))
    if look.get("browser_focus_ring"):
        out["browser_focus_ring"] = True
    return {key: value for key, value in out.items() if value is not None and value != []}


def _rest_look(entry: dict, probe: dict | None) -> StyleLook:
    font = _FONT.match(str(entry.get("font") or ""))
    drawn = str(entry.get("borderStyle") or "none").lower() not in ("none", "hidden") and any(
        v > 0 for v in _numbers(entry.get("border"))
    )
    gaps = _numbers(entry.get("gap"))
    data: dict = {
        "background": _opaque_hex(entry.get("bg")),
        "color": _opaque_hex(entry.get("color")),
        "border_color": _opaque_hex(entry.get("borderColor")) if drawn else None,
        "border_width": _numbers(entry.get("border")),
        "border_style": _text(entry.get("borderStyle")),
        "radius": _numbers(entry.get("radius")),
        "pill": bool(entry.get("pill")),
        "padding": _numbers(entry.get("padding")),
        "height": _float(entry.get("h")) or None,
        "gap": gaps[-1] if gaps else None,
    }
    if font:
        data.update({
            "font_weight": float(font.group(1)),
            "font_size": float(font.group(2)),
            "line_height": float(font.group(3)[:-2]) if font.group(3).endswith("px") else None,
            "font_family": _family(font.group(4)),
        })
    if probe:
        extra = _look_fields(probe)
        # Geometry comes from the rest harvest (it knows pills); the probe adds everything else.
        for key in ("background", "border_color", "border_width", "border_style", "radius", "padding", "height", "gap"):
            extra.pop(key, None)
        data.update(extra)
    return StyleLook(**{key: value for key, value in data.items() if value is not None})


def _state_look(record: dict | None, state: str) -> StyleLook | None:
    look = record.get(state) if record else None
    fields = _look_fields(look, clears=True) if isinstance(look, dict) else {}
    return StyleLook(**fields) if fields else None


def _transitions(motion: dict | None) -> list[StyleTransition]:
    out: list[StyleTransition] = []
    for target, key in (("self", "transitions"), ("label", "label_transitions"), ("icon", "icon_transitions")):
        for item in _list((motion or {}).get(key)):
            if not isinstance(item, dict) or _float(item.get("duration_ms")) <= 0:
                continue
            out.append(StyleTransition(
                target=target, property=str(item.get("property") or "all")[:60],
                duration_ms=_float(item.get("duration_ms")), easing=str(item.get("easing") or "ease")[:120],
                delay_ms=_float(item.get("delay_ms")),
            ))
    return out


def _icon(motion: dict | None) -> StyleIcon | None:
    info = (motion or {}).get("icon")
    if not isinstance(info, dict):
        return None
    position = "start" if info.get("position") == "start" else "end"
    if info.get("kind") == "glyph" and isinstance(info.get("glyph"), str):
        return StyleIcon(kind="glyph", position=position, glyph=info["glyph"][:4])
    if info.get("kind") == "svg":
        svg = clean_icon_svg(info.get("svg"))
        if svg:
            return StyleIcon(kind="svg", position=position, svg=svg,
                             width=_float(info.get("width")) or None, height=_float(info.get("height")) or None)
    if info.get("kind") == "img":
        return StyleIcon(kind="img", position=position)
    return None


def measured_styles(surfaces: list[dict], states: dict | None, url: str) -> list[MeasuredStyle]:
    """One `MeasuredStyle` per variant of the state classes, buttons first, most frequent first."""
    records = {
        record["idx"]: record
        for record in _list((states or {}).get("styles"))
        if isinstance(record, dict) and isinstance(record.get("idx"), int)
    }
    order = list(STATE_TARGET_CAPS)
    groups = sorted(shape_groups(surfaces, tuple(STATE_TARGET_CAPS)), key=lambda g: order.index(str(g[1][0].get("cls"))))
    out: list[MeasuredStyle] = []
    for variant, members in groups[:_MAX_MEASURED_STYLES]:
        cls = str(members[0].get("cls") or "")
        record = next((records[m["idx"]] for m in members if m.get("idx") in records), None)
        entry = next((m for m in members if record is not None and m.get("idx") == record["idx"]), members[0])
        motion = record.get("motion") if record else None
        out.append(MeasuredStyle(
            surface=cls,  # type: ignore[arg-type]
            variant=variant,
            count=len(members),
            probed=str(record.get("how")) if record and record.get("how") in ("pointer", "forced") else "rest-only",  # type: ignore[arg-type]
            rest=_rest_look(entry, record.get("rest") if record else None),
            hover=_state_look(record, "hover"),
            pressed=_state_look(record, "pressed"),
            focus=_state_look(record, "focus"),
            disabled=_state_look(record, "disabled"),
            transitions=_transitions(motion),
            icon=_icon(motion),
            pointer=_pointer(url, f"{cls} {variant}"),
        ))
    return out


def _first(value: object) -> str:
    """The first entry of a computed comma list (`"pulse, spin"` → `"pulse"`), parentheses kept."""
    text, depth = str(value or ""), 0
    for index, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            return text[:index].strip()
    return text.strip()


def _ms(value: object) -> float:
    text = _first(value)
    try:
        return round(float(text[:-2]) if text.endswith("ms") else float(text.rstrip("s")) * 1000, 2)
    except ValueError:
        return 0.0


def measured_motion(raw: dict, url: str) -> MotionEvidence:
    """The page's CSS animations, its CSS reveals (deduplicated) and its scripted-motion notes."""
    animations: list[MeasuredAnimation] = []
    for entry in _list(raw.get("animations")):
        if not isinstance(entry, dict):
            continue
        name = _first(entry.get("name"))[:120]
        if not name or name == "none":
            continue
        animations.append(MeasuredAnimation(
            name=name, duration_ms=_ms(entry.get("duration")), easing=_first(entry.get("easing")) or "ease",
            delay_ms=_ms(entry.get("delay")), iterations=_first(entry.get("iterations")) or "1",
            direction=_first(entry.get("direction")) or "normal", fill_mode=_first(entry.get("fill")) or "none",
            count=max(1, int(_float(entry.get("count")) or 1)), where=str(entry.get("where") or "")[:120],
            pointer=_pointer(url, f"animation {name}"),
        ))
    states = raw.get("states") if isinstance(raw.get("states"), dict) else {}
    reveals: dict[tuple, MeasuredReveal] = {}
    scripted: list[ScriptedMotion] = []
    for entry in _list(states.get("reveals")):
        if not isinstance(entry, dict):
            continue
        where = str(entry.get("where") or "")[:120]
        if entry.get("kind") != "css":
            scripted.append(ScriptedMotion(kind="scripted", where=where, pointer=_pointer(url, f"reveal {where}")))
            continue
        main = max(
            (t for t in _list(entry.get("transitions")) if isinstance(t, dict)),
            key=lambda t: _float(t.get("duration_ms")), default={},
        )
        opacity = entry.get("from_opacity")
        opacity = float(opacity) if isinstance(opacity, (int, float)) and not isinstance(opacity, bool) else None
        key = (opacity, _text(entry.get("from_transform")), _float(main.get("duration_ms")), main.get("easing"))
        if key in reveals:
            reveals[key].count += 1
            continue
        reveals[key] = MeasuredReveal(
            where=where, from_opacity=opacity, from_transform=_text(entry.get("from_transform")),
            duration_ms=_float(main.get("duration_ms")), easing=str(main.get("easing") or "ease")[:120],
            delay_ms=_float(main.get("delay_ms")), trigger=[str(t)[:40] for t in _list(entry.get("trigger"))][:3],
            pointer=_pointer(url, f"reveal {where}"),
        )
    for entry in _list(states.get("scripted")):
        if isinstance(entry, dict) and entry.get("kind") in ("scripted", "canvas", "video"):
            where = str(entry.get("where") or "")[:120]
            scripted.append(ScriptedMotion(kind=entry["kind"], where=where, pointer=_pointer(url, f"{entry['kind']} {where}")))
    return MotionEvidence(animations=animations, reveals=list(reveals.values())[:_MAX_REVEALS], scripted=scripted[:12])


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


_COLOR_CALL = re.compile(
    r"(?<![a-z-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.IGNORECASE
)


def _take_color(text: str) -> tuple[str | None, str]:
    match = _COLOR_CALL.search(text)
    if match:
        end = text.find(")", match.start())
        if end >= 0:
            return text[match.start() : end + 1], text[: match.start()] + text[end + 1 :]
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
