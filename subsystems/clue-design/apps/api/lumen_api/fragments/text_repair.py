"""Bounded plain-text variants of held HTML; no visual reconstruction or source execution."""

import re
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from .paths import resolve_structural_node, structural_children
from .refs import FragmentRefused
from .slots import SLOT_MARKER_ATTR

_EXCLUDED = {
    "svg",
    "math",
    "script",
    "style",
    "noscript",
    "template",
    "textarea",
    "select",
    "option",
}
# Accept only coordinates actually emitted by this inventory. Narrow the legacy
# path reader's grammar; do not admit aliases/zero indices as distinct targets.
_TEXT_PATH_RE = re.compile(r":nth-child\([1-9]\d*\)(?: > :nth-child\([1-9]\d*\))*")


def text_leaves(node: Any) -> list:
    if node.tag in _EXCLUDED or node.attributes.get("aria-hidden") == "true":
        return []
    if node.tag == "-text":
        return [node] if node.text().strip() else []
    return [leaf for child in node.iter(include_text=True) for leaf in text_leaves(child)]


def _eligibility(node: Any, manifest: dict) -> tuple[Any, str | None]:
    leaves = text_leaves(node)
    # Address the immediate text owner, never its ancestor wrapper. This keeps
    # each inventory entry unique and prevents two paths editing one leaf.
    if len(leaves) != 1 or leaves[0].parent != node:
        return None, "split_or_nested_text"
    current = node
    while current is not None:
        if current.tag in _EXCLUDED or current.attributes.get("aria-hidden") == "true":
            return None, "unsupported_text_context"
        key = current.attributes.get(SLOT_MARKER_ATTR)
        if key and manifest.get(key, {}).get("kind", "text") == "text":
            return None, "existing_text_slot"
        if current.tag == "a":
            return None, "use_anchor_label_repair"
        # Attribute changes are outside this leaf-only contract. Refuse rather
        # than leave an obsolete accessible name/tooltip on a naming ancestor.
        if any(current.attributes.get(name) for name in ("aria-label", "aria-labelledby", "title")):
            return None, "accessible_name_conflict"
        current = current.parent
    return leaves[0], None


def inspect_text_targets(
    html: str, *, manifest: dict | None = None, offset: int = 0, limit: int = 16
) -> dict:
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 16
    ):
        raise FragmentRefused(
            "repair.bad_text_offset", "text offset must be nonnegative; limit is 1-16"
        )
    tree = LexborHTMLParser(html)
    rows = []
    pending = [(tree.body, "")] if tree.body else []
    while pending:
        node, path = pending.pop()
        if node.tag in _EXCLUDED:
            continue
        direct = [
            child
            for child in node.iter(include_text=True)
            if child.tag == "-text" and child.text().strip()
        ]
        if direct:
            leaf, reason = _eligibility(node, manifest or {})
            # Expected text must address the exact editable leaf. SVG titles and
            # hidden decorative descendants are not part of that text target.
            text = " ".join((leaf.text() if leaf is not None else node.text(separator=" ")).split())
            if len(text) > 2048:
                reason = "text_too_long"
            if not path or len(path) > 1024:
                reason = "unaddressable_text"
            rows.append(
                {
                    "path": path,
                    "tag": node.tag,
                    "text": text[:2048],
                    "text_complete": len(text) <= 2048,
                    "editable": reason is None,
                    "reason": reason,
                }
            )
        children = structural_children(node)
        pending.extend(
            (child, f"{path} > :nth-child({i})" if path else f":nth-child({i})")
            for i, child in reversed(list(enumerate(children, 1)))
        )
    if offset > len(rows):
        raise FragmentRefused("repair.bad_text_offset", "text offset exceeds target count")
    end = min(offset + limit, len(rows))
    return {
        "coordinate_space": "stored_fragment_html",
        "rendered_visibility": "unverified",
        "targets": rows[offset:end],
        "total": len(rows),
        "offset": offset,
        "next_offset": end if end < len(rows) else None,
    }


def validate_text_edits(edits: Any) -> list[dict]:
    if not isinstance(edits, list) or not 1 <= len(edits) <= 8:
        raise FragmentRefused("repair.bad_text_edits", "provide 1-8 exact text edits")
    paths = set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"path", "expected", "replacement"}:
            raise FragmentRefused(
                "repair.bad_text_edits", "each edit requires path, expected, replacement"
            )
        path = edit["path"]
        if (
            not isinstance(path, str)
            or len(path) > 1024
            or not _TEXT_PATH_RE.fullmatch(path)
            or path in paths
        ):
            raise FragmentRefused(
                "repair.bad_text_edits", "text paths must be distinct structural paths"
            )
        paths.add(path)
        for value in (edit["expected"], edit["replacement"]):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 2048
                or any(ord(c) < 32 for c in value)
            ):
                raise FragmentRefused(
                    "repair.bad_text_edits", "text must be nonempty plain text <=2048 chars"
                )
        if (
            edit["expected"] != " ".join(edit["expected"].split())
            or edit["expected"] == edit["replacement"]
        ):
            raise FragmentRefused(
                "repair.bad_text_edits",
                "expected text must be normalized and replacement different",
            )
    return edits


def replace_text_targets(body: Any, edits: Any, manifest: dict) -> list[str]:
    planned = []
    for edit in validate_text_edits(edits):
        node = resolve_structural_node(body, edit["path"])
        if node is None:
            raise FragmentRefused(
                "repair.text_unmatched", "stored structural path no longer resolves"
            )
        leaf, reason = _eligibility(node, manifest)
        if reason:
            raise FragmentRefused("repair.text_ineligible", reason)
        if " ".join(leaf.text().split()) != edit["expected"]:
            raise FragmentRefused("repair.text_stale", "expected text differs from the held source")
        if any(leaf == entry[0] for entry in planned):
            raise FragmentRefused(
                "repair.text_overlap", "multiple paths address the same text leaf"
            )
        planned.append((leaf, edit))
    # Whole-batch validation precedes changes, and replacement strings are TEXT.
    for leaf, edit in planned:
        text = leaf.text()
        prefix, suffix = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()) :]
        leaf.replace_with(prefix + edit["replacement"] + suffix)
    return [edit["path"] for _, edit in planned]
