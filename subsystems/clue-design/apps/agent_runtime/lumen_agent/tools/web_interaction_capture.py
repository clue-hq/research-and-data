"""Bounded observations of real switcher actions on temporary render pages.

No source script recovery, DOM state injection or aesthetic verdict. Native tabs
have a panel contract; CSS-radio image mappings are observed, not source-verified.
"""

import hashlib
import time
from pathlib import Path
from typing import Any

_MAX_GROUPS = 2
_MAX_STATES = 4
_ACTION_TIMEOUT_MS = 1200


def _attr(name: str, value: str) -> str:
    # Values come from document IDs/HTML, never interpolate them as CSS syntax.
    escaped = "".join(
        c if c.isalnum() or c in "_-" else f"\\{ord(c):x} " for c in value
    )
    return f'[{name}="{escaped}"]'


_RADIOS = r"""() => {
  const groups = [];
  for (const root of document.querySelectorAll('[data-fragment-id][data-node-id]')) {
    const inputs = [...root.querySelectorAll('input[type=radio][name]')].filter(
      el => el.closest('[data-fragment-id]') === root);
    if (root.querySelectorAll('img').length < 2) continue;
    for (const name of new Set(inputs.map(el => el.name))) {
      const members = inputs.filter(el => el.name === name);
      // Never operate form controls during this visual probe.
      if (members.length < 2) continue;
      const globalMembers = [...document.querySelectorAll('input[type=radio]')]
        .filter(el => el.name === name && !el.form);
      groups.push({kind: 'radio', node_id: root.dataset.nodeId,
        fragment_id: root.dataset.fragmentId, name, count: members.length,
        skip: members.some(el => el.form) ? 'form_controls_not_probed' : null,
        ambiguous: globalMembers.length !== members.length});
    }
  }
  return groups;
}"""

_NATIVE_FRAGMENTS = r"""() => [...document.querySelectorAll(
  '[data-lumen-fragment][data-node-id] [data-lumen-tabs][id]'
)].map(root => ({kind: 'native', root_id: root.id,
  node_id: root.closest('[data-lumen-fragment]').dataset.nodeId,
  count: root.querySelectorAll(':scope > [role=tablist] > [role=tab]').length
}))"""

_OBSERVE = r"""(root, {kind, name, index}) => {
  const visible = el => {
    if (!el || !el.getClientRects().length) return false;
    let box = el.getBoundingClientRect();
    let {left, right, top, bottom} = box;
    if (!(right > left && bottom > top)) return false;
    for (let p = el; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (p.hidden || s.display === 'none' || s.visibility === 'hidden' ||
          s.visibility === 'collapse' || Number(s.opacity) <= 0.01) return false;
      if (p === el) continue;
      const r = p.getBoundingClientRect();
      if (s.overflowX !== 'visible') {left = Math.max(left,r.left); right = Math.min(right,r.right);}
      if (s.overflowY !== 'visible') {top = Math.max(top,r.top); bottom = Math.min(bottom,r.bottom);}
      if (right <= left || bottom <= top) return false;
    }
    return true;
  };
  const controls = kind === 'native'
    ? [...root.querySelectorAll(':scope > [role=tablist] > [role=tab]')]
    : [...root.querySelectorAll('input[type=radio]')].filter(el => el.name === name);
  const control = controls[index];
  if (!control) return {reason: 'control_missing'};
  const selected = controls.filter(el => kind === 'native' ? el.getAttribute('aria-selected') === 'true' : el.checked);
  const selectedIndex = controls.indexOf(selected[0]);
  const base = {control_id: control.id, selected_index: selectedIndex,
    selection_confirmed: selected.length === 1 && selected[0] === control};
  if (root.getAnimations({subtree:true}).some(animation =>
      animation.playState === 'running' &&
      Number.isFinite(animation.effect?.getComputedTiming().endTime)))
    return {...base, reason: 'transition_in_progress'};
  if (!control.id || [...document.querySelectorAll('[id]')].filter(el => el.id === control.id).length !== 1)
    return {...base, reason: 'ambiguous_control_id'};
  let panel = root;
  if (kind === 'native') {
    const panelId = control.getAttribute('aria-controls');
    const matches = [...document.querySelectorAll('[id]')].filter(el => el.id === panelId);
    if (matches.length !== 1 || !root.contains(matches[0])) return {...base, reason: 'panel_missing_or_ambiguous'};
    panel = matches[0];
    base.panel_id = panelId;
    base.panel_visible = visible(panel);
    const siblings = [...root.querySelectorAll(':scope > [role=tabpanel]')];
    if (!base.selection_confirmed || !base.panel_visible ||
        siblings.some(el => el !== panel && visible(el)) || control.tabIndex !== 0)
      return {...base, reason: 'selection_not_observed'};
  }
  const images = [...panel.querySelectorAll('img')].filter(visible);
  base.visible_images = images.map(el => el.id || el.dataset.assetId || el.currentSrc || el.src);
  base._media_sources = images.map(el => el.currentSrc || el.src);
  base.media = images.map(el => ({id: el.id, source: (el.currentSrc || el.src).slice(0,500),
    loaded: el.complete && el.naturalWidth > 0 && el.naturalHeight > 0}));
  if (!base.selection_confirmed) return {...base, reason: 'selection_not_observed'};
  if (images.some(el => !el.complete || !el.naturalWidth || !el.naturalHeight))
    return {...base, reason: 'visible_media_unready'};
  if (kind === 'radio' && !images.length) return {...base, reason: 'no_visible_media'};
  return {...base, reason: null};
}"""


def _observe(root: Any, group: dict, index: int, *, settle: bool = True) -> dict:
    deadline = time.monotonic() + (_ACTION_TIMEOUT_MS / 1000 if settle else 0)
    while True:
        result = root.evaluate(
            _OBSERVE, {"kind": group["kind"], "name": group.get("name"), "index": index}
        )
        # Source identities, not image-byte hashes or a pixel-difference score.
        result["media_sources_sha256"] = sorted(
            {
                hashlib.sha256(source.encode()).hexdigest()
                for source in result.pop("_media_sources", [])
            }
        )
        if not result.get("reason") or time.monotonic() >= deadline:
            return result
        root.page.wait_for_timeout(50)


def _controls(root: Any, group: dict) -> Any:
    if group["kind"] == "native":
        return root.locator(':scope > [role="tablist"] > [role="tab"]')
    return root.locator('input[type="radio"]' + _attr("name", group["name"]))


def _keyboard_entry(page: Any, controls: Any) -> bool:
    # Start from the browser's real sequential focus order, never force-focus
    # clipped source controls. A bound reports missing evidence on a large page.
    for _ in range(64):
        page.keyboard.press("Tab")
        if controls.evaluate_all("els => els.includes(document.activeElement)"):
            return True
    return False


def capture_switchers(
    browser: Any,
    html: str,
    directory: Path,
    native_groups: list[dict],
    widths: tuple[int, ...],
) -> dict:
    """Click and inspect a bounded set; every skipped/failed state is explicit.

    Both viewport classes run in reduced-motion mode for deterministic inspection.
    Normal-motion timing, semantic image mapping and focus styling remain unverified.
    """
    captures: list[dict] = []
    failures: list[dict] = []
    omitted: list[dict] = []
    for width in widths:
        page = browser.new_page(
            viewport={"width": width, "height": 1200}, reduced_motion="reduce"
        )
        try:
            page.set_default_timeout(_ACTION_TIMEOUT_MS)
            page.set_content(html, wait_until="load", timeout=10000)
            groups = [{"kind": "native", **group} for group in native_groups]
            groups += page.evaluate(_NATIVE_FRAGMENTS)
            groups += page.evaluate(_RADIOS)
            attempted_groups = 0
            for group_index, group in enumerate(groups):
                identity = {
                    "implementation": group["kind"],
                    "node_id": group["node_id"],
                    "width": width,
                }
                if group.get("name"):
                    identity["group_name"] = group["name"]
                if group.get("root_id"):
                    identity["root_id"] = group["root_id"]
                if group.get("skip"):
                    omitted.append({**identity, "reason": group["skip"]})
                    continue
                if attempted_groups >= _MAX_GROUPS:
                    omitted.append({**identity, "reason": "component_cap"})
                    continue
                attempted_groups += 1
                selector = _attr("data-node-id", group["node_id"])
                if group.get("root_id"):
                    selector += " " + _attr("id", group["root_id"]) + "[data-lumen-tabs]"
                elif group["kind"] == "radio":
                    selector += "[data-fragment-id]"
                else:
                    selector += ".lumen-tabs"
                root = page.locator(selector)
                if root.count() != 1:
                    failures.append(
                        {
                            **identity,
                            "reason": "component_missing"
                            if not root.count()
                            else "ambiguous_component",
                        }
                    )
                    continue
                if group.get("ambiguous"):
                    failures.append(
                        {**identity, "reason": "cross_component_radio_group"}
                    )
                    continue
                controls = _controls(root, group)
                count = controls.count()
                if group["kind"] == "native" and count != group["count"]:
                    failures.append(
                        {
                            **identity,
                            "reason": "control_count_mismatch",
                            "expected": group["count"],
                            "observed": count,
                        }
                    )
                    continue
                if count < 2:
                    failures.append({**identity, "reason": "controls_missing"})
                    continue
                selected_count = min(count, _MAX_STATES)
                for index in range(selected_count, count):
                    omitted.append(
                        {**identity, "state_index": index, "reason": "state_cap"}
                    )
                keyboard_entry = _keyboard_entry(page, controls)
                # Exercise the initially selected state last: it need not be zero.
                initial = _observe(root, group, 0, settle=False).get("selected_index")
                order = [i for i in range(selected_count) if i != initial]
                if initial in range(selected_count):
                    order.append(initial)
                for index in order:
                    context = {**identity, "state_index": index}
                    try:
                        before = _observe(root, group, index, settle=False)
                        control = controls.nth(index)
                        if group["kind"] == "native":
                            control.click()
                        else:
                            control_id = control.get_attribute("id") or ""
                            labels = root.locator("label" + _attr("for", control_id))
                            if not control_id or labels.count() != 1:
                                failures.append(
                                    {**context, "reason": "label_missing_or_ambiguous"}
                                )
                                continue
                            labels.click()
                        result = _observe(root, group, index)
                        if result.get("reason"):
                            failures.append({**context, **result})
                            continue
                        if before.get("selected_index") == index:
                            failures.append(
                                {**context, "reason": "selection_unchanged"}
                            )
                            continue
                        if group["kind"] == "radio" and result[
                            "media_sources_sha256"
                        ] == before.get("media_sources_sha256"):
                            failures.append(
                                {**context, **result, "reason": "media_did_not_change"}
                            )
                            continue
                        keyboard = {
                            "status": "unverified",
                            "entry_observed": keyboard_entry,
                            "keys": ["ArrowRight", "ArrowLeft"],
                        }
                        if keyboard_entry:
                            page.keyboard.press("ArrowRight")
                            forward = _observe(root, group, (index + 1) % count)
                            forward_focus = controls.nth((index + 1) % count).evaluate(
                                "el => el === document.activeElement"
                            )
                            page.keyboard.press("ArrowLeft")
                            restored = _observe(root, group, index)
                            focused = control.evaluate(
                                "el => el === document.activeElement"
                            )
                            if (
                                not forward.get("reason")
                                and not restored.get("reason")
                                and focused
                                and forward_focus
                            ):
                                keyboard["status"] = "observed"
                            else:
                                failures.append(
                                    {
                                        **context,
                                        "reason": "keyboard_selection_not_observed",
                                    }
                                )
                                continue
                            if group["kind"] == "radio" and (
                                forward["media_sources_sha256"]
                                == result["media_sources_sha256"]
                                or restored["media_sources_sha256"]
                                != result["media_sources_sha256"]
                            ):
                                failures.append(
                                    {
                                        **context,
                                        "reason": "keyboard_media_transition_not_observed",
                                    }
                                )
                                continue
                            result = restored
                        else:
                            failures.append(
                                {**context, "reason": "keyboard_entry_unobserved"}
                            )
                        name = hashlib.sha256(
                            f"{group_index}:{group['node_id']}".encode()
                        ).hexdigest()[:12]
                        path = directory / f"state_{width}_{name}_{index}.png"
                        # A region capture is readable and avoids storing the same
                        # very tall page eight times for one four-state component.
                        root.screenshot(path=str(path), animations="allow")
                        captures.append(
                            {
                                **context,
                                **result,
                                "reason": None,
                                "kind": "tab-selected"
                                if group["kind"] == "native"
                                else "radio-selected",
                                "path": str(path),
                                "capture_scope": "component",
                                "keyboard": keyboard,
                                "reduced_motion": "reduce",
                                "normal_motion": "unverified",
                                "source_mapping": "unverified",
                            }
                        )
                    except (
                        Exception
                    ) as error:  # best effort; other controls still get a walk
                        failures.append(
                            {
                                **context,
                                "reason": "action_or_capture_failed",
                                "error": f"{type(error).__name__}: {error}"[:500],
                            }
                        )
        finally:
            page.close()
    return {"captures": captures, "failures": failures, "omitted": omitted}
