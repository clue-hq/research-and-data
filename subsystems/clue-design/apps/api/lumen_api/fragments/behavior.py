"""Bounded observations of a sanitized snapshot, never a behavior test or JS replay.

Foreign state attributes survive sanitization; their JavaScript controllers do not.
Expose that distinction without mutating the fragment or guessing control/image pairs.
CSS-native disclosure, popover and command controls are deliberately not classified.
"""

from __future__ import annotations

import re
from typing import Any

import tinycss2
from selectolax.lexbor import LexborHTMLParser
from .native import validate_native_dependencies

_MAX_ITEMS = 12
_MAX_ASSETS = 24
_MAX_TEXT = 96
_ASSET = re.compile(r"/asset-store/([0-9a-f]{64})(?=$|[\s\"'?#)])")


def _short(value: str | None) -> str:
    return " ".join((value or "").split())[:_MAX_TEXT]


def _hidden_markers(attrs: dict) -> list[str]:
    markers = []
    if "hidden" in attrs:
        markers.append("hidden_attribute")
    classes = set((attrs.get("class") or "").split())
    for name in ("opacity-0", "hidden", "invisible"):
        if name in classes:
            markers.append(f"class_{name}")
    for declaration in tinycss2.parse_declaration_list(attrs.get("style") or ""):
        if declaration.type != "declaration":
            continue
        value = tinycss2.serialize(declaration.value).strip().lower()
        if declaration.lower_name == "opacity" and value in {"0", "0.0", "0%"}:
            markers.append("inline_opacity_zero")
        elif declaration.lower_name == "display" and value == "none":
            markers.append("inline_display_none")
        elif declaration.lower_name == "visibility" and value == "hidden":
            markers.append("inline_visibility_hidden")
    return sorted(set(markers))


def inspect_fragment_behavior(html: str, native_dependencies: Any = None) -> dict[str, Any]:
    """Read already-sanitized HTML. Marker counts are not computed visibility or linkage."""
    dom = LexborHTMLParser(html)
    native_ids = set()
    if native_dependencies is not None:
        declared = validate_native_dependencies(html, native_dependencies)
        native_ids = {item["tab_id"] for group in declared["tabs"] for item in group["items"]}
    controls: list[dict] = []
    hidden_states: list[dict] = []
    control_count = hidden_count = 0
    declared_count = 0
    assets: set[str] = set()
    primary_assets: dict[str, None] = {}
    for node in dom.css("*"):
        attrs = node.attributes
        tag = node.tag.lower()
        role = (attrs.get("role") or "").lower()
        state = {
            name: _short(attrs[name])
            for name in ("aria-pressed", "aria-selected", "aria-expanded")
            if name in attrs
        }
        native = tag == "summary" or "popovertarget" in attrs or "commandfor" in attrs
        if not native and (tag == "button" or role in {"button", "tab"}) and (
            state or "aria-controls" in attrs or role == "tab"
        ):
            control_count += 1
            declared_count += attrs.get("id") in native_ids
            if len(controls) < _MAX_ITEMS:
                heading = node.css_first("h1,h2,h3,h4,h5,h6")
                controls.append({
                    "tag": tag,
                    "role": _short(role),
                    "element_id": _short(attrs.get("id")),
                    "label": _short(attrs.get("aria-label") or (
                        heading.text(separator=" ") if heading else node.text(separator=" ")
                    )),
                    "state": state,
                    "target_id": _short(attrs.get("aria-controls")),
                })
        markers = _hidden_markers(attrs)
        if markers:
            hidden_count += 1
            if len(hidden_states) < _MAX_ITEMS:
                hidden_states.append({
                    "tag": tag,
                    "element_id": _short(attrs.get("id")),
                    "alt": _short(attrs.get("alt")),
                    "markers": markers,
                })
        # Media attributes only: a matching string in source text/script is not a dependency.
        if tag in {"img", "video", "source", "image"}:
            for name in ("src", "srcset", "poster", "href", "xlink:href"):
                found = _ASSET.findall(attrs.get(name) or "")
                assets.update(found)
                if name != "srcset":
                    primary_assets.update(dict.fromkeys(found))
    return {
        "basis": "sanitized_html_snapshot",
        "controller_status": (
            "mixed_native_and_unretained" if declared_count and control_count > declared_count
            else "declared_native_runtime" if declared_count
            else "controller_not_retained" if control_count else "not_assessed"
        ),
        "behavior_test": "not_performed",
        "relationships": "not_inferred",
        "stateful_control_count": control_count,
        "declared_native_control_count": declared_count,
        "hidden_state_candidate_count": hidden_count,
        "controls": controls,
        "hidden_states": hidden_states,
        "asset_digests": [*primary_assets, *sorted(assets - primary_assets.keys())][:_MAX_ASSETS],
        "truncated": control_count > _MAX_ITEMS or hidden_count > _MAX_ITEMS
        or len(assets) > _MAX_ASSETS,
        "note": (
            "This artifact declares approved platform tab dependencies. That declaration is not "
            "a behavior test: render the pin and inspect click, keyboard, media and responsive "
            "states. Any controls outside the declaration still have no retained controller."
            if declared_count else
            "This snapshot retains stateful controls but no source JavaScript controller. "
            "Hidden markers are candidates, not computed visibility; media/control relationships "
            "and actual behavior were not tested. Reconstruct and test the linked states with a "
            "supported component, or replace the controls with visible static content."
            if control_count else
            "No foreign stateful control was identified by this bounded marker inspection; "
            "this is not a behavior or motion pass."
        ),
    }
