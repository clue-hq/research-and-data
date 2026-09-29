"""Frozen, explicitly selected text-role references over native preview measurements.

This compares measured facts, not aesthetic quality, complete component structure,
or whether an agent chose a semantically appropriate reference. No render or model
call happens here. A new draft cannot move a reference pinned earlier in the turn.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

WIDTHS = (1440, 768, 375)
TYPE_PROPERTIES = (
    "font_family",
    "font_size",
    "font_weight",
    "line_height",
    "letter_spacing",
    "text_align",
    "font_synthesis",
)
_FIELDS = {"role", "reference_node_id", "reference_path", "target_node_id", "target_path"}
_PATH = re.compile(r"(?::nth-child\([1-9][0-9]*\)(?: > :nth-child\([1-9][0-9]*\))*)?")
_MAX_BINDINGS = 24


class TypographyReferenceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _current(layout: dict[str, Any] | None, identity: dict[str, Any], width: int) -> bool:
    return bool(
        layout
        and layout.get("status") == "observed"
        and identity["iteration"] is not None
        and identity["preview_version"] == identity["local_document_version"]
        and all(
            layout.get(key) == identity[key]
            for key in (
                "document_id",
                "page_id",
                "local_document_version",
                "iteration",
            )
        )
        and layout.get("viewport_width") == width
    )


def _text(layout: dict[str, Any] | None, node_id: str, path: str) -> dict[str, Any] | None:
    if layout is None:
        return None
    nodes = [n for n in layout.get("nodes", []) if n.get("node_id") == node_id]
    if len(nodes) != 1 or nodes[0].get("status") != "measured":
        return None
    rows = [t for t in nodes[0].get("texts", []) if t.get("rendered_path") == path]
    return rows[0] if len(rows) == 1 else None


def _sample(row: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    if row is None:
        return {}, ["text_missing_or_ambiguous"]
    sample = {"tag": row.get("tag"), "css_visible": row.get("css_visible")}
    if not sample["tag"] or type(sample["css_visible"]) is not bool:
        return sample, ["visibility_or_tag_unmeasured"]
    if not sample["css_visible"]:
        return sample, []
    computed = row.get("computed") or {}
    sample.update({key: computed[key] for key in TYPE_PROPERTIES if key in computed})
    gaps = [key + "_unmeasured" for key in TYPE_PROPERTIES if not computed.get(key)]
    usage = row.get("font_usage") or {}
    fonts = usage.get("fonts") or []
    if (
        usage.get("status") != "observed"
        or not fonts
        or any(
            not f.get("family_name")
            or not f.get("postscript_name")
            or type(f.get("is_custom_font")) is not bool
            for f in fonts
        )
    ):
        gaps.append("glyph_faces_unmeasured")
    else:
        # Different copy changes counts, not the identity of the faces that rendered it.
        sample["glyph_faces"] = sorted(
            {(f["family_name"], f["postscript_name"], f["is_custom_font"]) for f in fonts}
        )
    return sample, gaps


class TypographyReferences:
    def __init__(self) -> None:
        self.bindings: list[dict[str, Any]] = []

    def register(
        self, raw: str, layouts: dict[int, dict[str, Any]], identity: dict[str, Any]
    ) -> None:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 32_000:
            raise TypographyReferenceError(
                "typography.bad_bindings", "Use a JSON list of 1–8 role mappings (maximum 32 KB)."
            )
        try:
            rows = json.loads(raw)
        except ValueError as exc:
            raise TypographyReferenceError(
                "typography.bad_bindings", "Invalid role mapping JSON."
            ) from exc
        if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
            raise TypographyReferenceError(
                "typography.bad_bindings", "Use a JSON list of 1–8 role mappings."
            )
        pending = copy.deepcopy(self.bindings)
        batch_targets = set()
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row) != _FIELDS
                or any(not isinstance(value, str) or len(value) > 1024 for value in row.values())
                or any(
                    not row[key].strip() for key in ("role", "reference_node_id", "target_node_id")
                )
            ):
                raise TypographyReferenceError(
                    "typography.bad_bindings",
                    "Each mapping needs role, reference_node_id, reference_path, "
                    "target_node_id and target_path strings.",
                )
            if any(_PATH.fullmatch(row[key]) is None for key in ("reference_path", "target_path")):
                raise TypographyReferenceError(
                    "typography.bad_bindings",
                    "Use exact rendered_node_relative paths from view(layout:...); "
                    "arbitrary CSS selectors are not supported.",
                )
            key = (identity["page_id"], row["target_node_id"], row["target_path"])
            if key in batch_targets:
                raise TypographyReferenceError(
                    "typography.bad_bindings", "A batch must not name the same target twice."
                )
            batch_targets.add(key)
            existing = next(
                (
                    b
                    for b in pending
                    if (b["page_id"], b["target_node_id"], b["target_path"]) == key
                ),
                None,
            )
            if existing:
                if any(existing[k] != row[k] for k in _FIELDS):
                    raise TypographyReferenceError(
                        "typography.reference_locked",
                        "This target already has a frozen reference. A later draft cannot "
                        "redefine its required typography in this turn.",
                    )
                continue
            if len(pending) >= _MAX_BINDINGS:
                raise TypographyReferenceError(
                    "typography.reference_limit",
                    "This turn already has 24 role references; "
                    "no additional mappings were registered.",
                )
            samples = {}
            for width in WIDTHS:
                layout = layouts.get(width)
                if not _current(layout, identity, width):
                    raise TypographyReferenceError(
                        "typography.reference_unavailable",
                        f"A current native measurement at {width}px is required. "
                        "Render once; inspect its layout paths.",
                    )
                sample, gaps = _sample(
                    _text(layout, row["reference_node_id"], row["reference_path"])
                )
                if gaps:
                    raise TypographyReferenceError(
                        "typography.reference_unavailable",
                        f"Reference at {width}px is incomplete: {', '.join(gaps)}. "
                        "No partial reference was registered.",
                    )
                samples[str(width)] = sample
            pending.append({**row, **identity, "samples": copy.deepcopy(samples)})
        self.bindings = pending

    def report(
        self, layouts: dict[int, dict[str, Any]], identity: dict[str, Any]
    ) -> dict[str, Any]:
        reports = []
        for binding in self.bindings:
            widths: dict[str, Any] = {}
            for width in WIDTHS:
                layout = layouts.get(width)
                if (
                    binding["document_id"] != identity["document_id"]
                    or binding["page_id"] != identity["page_id"]
                    or not _current(layout, identity, width)
                ):
                    widths[str(width)] = {
                        "status": "incomplete",
                        "gaps": ["current_target_measurement_missing"],
                    }
                    continue
                actual, gaps = _sample(
                    _text(layout, binding["target_node_id"], binding["target_path"])
                )
                expected = binding["samples"][str(width)]
                differences = {
                    key: {"expected": expected[key], "actual": actual[key]}
                    for key in expected.keys() & actual.keys()
                    if expected[key] != actual[key]
                }
                widths[str(width)] = {
                    "status": "mismatch" if differences else "incomplete" if gaps else "matched",
                    "differences": differences,
                    "gaps": gaps,
                }
            statuses = {r["status"] for r in widths.values()}
            reports.append(
                {
                    **{key: binding[key] for key in _FIELDS},
                    "page_id": binding["page_id"],
                    "reference_document_version": binding["local_document_version"],
                    "reference_render_iteration": binding["iteration"],
                    "status": "mismatch"
                    if "mismatch" in statuses
                    else "incomplete"
                    if "incomplete" in statuses
                    else "matched",
                    "widths": widths,
                }
            )
        statuses = {r["status"] for r in reports}
        status = (
            "not_declared"
            if not reports
            else "mismatch"
            if "mismatch" in statuses
            else "incomplete"
            if "incomplete" in statuses
            else "matched"
        )
        return {
            "status": status,
            "scope": "explicit_text_roles_current_turn",
            "bindings": reports,
            "quality_verdict": "not_computed",
            "persisted_revision_checked": False,
            "note": "Only explicitly mapped roles are checked. This does not verify all page text, "
            "component structure, copy fit, correct reference choice or aesthetic quality. "
            "References are immutable within this turn; current target measurements must be fresh.",
        }
