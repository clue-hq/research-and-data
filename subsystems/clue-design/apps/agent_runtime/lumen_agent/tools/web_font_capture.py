"""Bounded Chromium glyph-font evidence for already measured preview text.

CDP reports the fonts used for child TextNodes, not the CSS family alias. This
does not identify the source file, prove weight/variation fidelity, or judge pixels.
No navigation, network fetch, DOM/style mutation or extra rendering is performed.
"""

import json
import time
from contextlib import suppress
from itertools import zip_longest
from typing import Any

MAX_FONT_TEXTS = 48
MAX_FONTS_PER_OWNER = 4
FONT_CAPTURE_SECONDS = 2.0  # Stop between protocol calls; not a transport timeout.

_FONT_OWNER = r"""
({node_id, path, text, text_complete, tag, computed}) => {
  const roots=document.querySelectorAll('[data-node-id="'+CSS.escape(node_id)+'"]');
  if(roots.length!==1) return null;
  const el=path ? roots[0].querySelector(':scope > '+path) : roots[0];
  if(!el || el.tagName.toLowerCase()!==tag) return null;
  const current=Array.from(el.childNodes).filter(n=>n.nodeType===3)
    .map(n=>n.textContent).join('').replace(/\s+/g,' ').trim();
  if((text_complete ? current : current.slice(0,240))!==text) return null;
  const s=getComputedStyle(el);
  if(s.fontFamily!==computed.font_family || s.fontSize!==computed.font_size ||
     s.fontWeight!==computed.font_weight) return null;
  return el;
}
"""


def capture_glyph_fonts(page: Any, nodes: list[dict]) -> dict:
    """Add per-owner receipts. Protocol failure leaves geometry evidence intact."""
    groups = []
    owners = {}
    aliases = []
    hidden = 0
    for node in nodes:
        group = []
        for text in node.get("texts", []):
            key = text.get("text_owner_id") or id(text)
            if key in owners:
                aliases.append((text, owners[key]))
                continue
            owners[key] = text
            if text.get("css_visible") is False:
                text["font_usage"] = {"status": "not_measured", "reason": "css_hidden"}
                hidden += 1
            else:
                text["font_usage"] = {"status": "not_measured", "reason": "owner_cap"}
                group.append((node, text))
        if group:
            groups.append(group)
    # A long opening must not consume the entire budget before later sections.
    candidates = [item for row in zip_longest(*groups) for item in row if item is not None]
    selected = candidates[:MAX_FONT_TEXTS]
    summary = {
        "status": "observed",
        "basis": "chromium_platform_fonts_for_child_text_nodes",
        "max_text_owners": MAX_FONT_TEXTS,
        "measured_text_owners": 0,
        "failed_text_owners": 0,
        "omitted_text_owners": max(0, len(candidates) - len(selected)),
        "css_hidden_text_owners": hidden,
        "duplicate_owner_records": len(aliases),
        "font_entries_omitted": 0,
        "asset_file_identity": "not_measured",
        "weight_and_variation_fidelity": "not_certified",
    }
    if not selected:
        for text, original in aliases:
            text["font_usage"] = original["font_usage"]
        return summary
    session = None
    started = time.monotonic()
    deadline = started + FONT_CAPTURE_SECONDS
    try:
        session = page.context.new_cdp_session(page)
        session.send("DOM.enable")
        session.send("CSS.enable")
        session.send("DOM.getDocument", {"depth": 0})
        for index, (node, text) in enumerate(selected):
            if time.monotonic() >= deadline:
                for _, skipped in selected[index:]:
                    skipped["font_usage"] = {"status": "not_measured", "reason": "time_budget"}
                summary["omitted_text_owners"] += len(selected) - index
                break
            object_id = None
            try:
                args = {
                    "node_id": node["node_id"], "path": text["rendered_path"],
                    "text": text["text"], "text_complete": text["text_complete"],
                    "tag": text["tag"], "computed": text["computed"],
                }
                result = session.send("Runtime.evaluate", {
                    "expression": f"({_FONT_OWNER})({json.dumps(args)})",
                    "returnByValue": False,
                })
                object_id = result.get("result", {}).get("objectId")
                if not object_id or result.get("exceptionDetails"):
                    text["font_usage"] = {
                        "status": "unavailable", "reason": "owner_changed_or_missing",
                    }
                    summary["failed_text_owners"] += 1
                    continue
                node_id = session.send("DOM.requestNode", {"objectId": object_id})["nodeId"]
                fonts = session.send("CSS.getPlatformFontsForNode", {"nodeId": node_id})["fonts"]
                if not isinstance(fonts, list) or not fonts:
                    text["font_usage"] = {"status": "unavailable", "reason": "no_glyphs_reported"}
                    summary["failed_text_owners"] += 1
                    continue
                omitted = max(0, len(fonts) - MAX_FONTS_PER_OWNER)
                text["font_usage"] = {
                    "status": "observed", "fonts_omitted": omitted,
                    "fonts": [
                        {
                            "family_name": str(f["familyName"])[:160],
                            "postscript_name": str(f.get("postScriptName", ""))[:160],
                            "is_custom_font": f["isCustomFont"], "glyph_count": f["glyphCount"],
                        }
                        for f in fonts[:MAX_FONTS_PER_OWNER]
                    ],
                }
                summary["font_entries_omitted"] += omitted
                summary["measured_text_owners"] += 1
            except Exception as error:
                text["font_usage"] = {
                    "status": "unavailable", "reason": "font_probe_failed",
                    "error_type": type(error).__name__,
                }
                summary["failed_text_owners"] += 1
            finally:
                if object_id:
                    # A closed debugging target must not erase layout observations.
                    with suppress(Exception):
                        session.send("Runtime.releaseObject", {"objectId": object_id})
    except Exception as error:
        summary["error_type"] = type(error).__name__
        for _, text in selected:
            text["font_usage"] = {"status": "unavailable", "reason": "font_protocol_unavailable"}
        summary["failed_text_owners"] = len(selected)
    finally:
        if session is not None:
            with suppress(Exception):
                session.detach()
    summary["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    for text, original in aliases:
        text["font_usage"] = original["font_usage"]
    if any(summary[key] for key in (
        "failed_text_owners", "omitted_text_owners", "font_entries_omitted",
    )):
        summary["status"] = "partial" if summary["measured_text_owners"] else "unavailable"
    return summary
