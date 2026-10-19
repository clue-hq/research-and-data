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


def typography_inventory(
    layouts: dict[int, dict[str, Any]], identity: dict[str, Any], node_id: str, offset: int = 0
) -> dict[str, Any]:
    """Join current native measurements by exact rendered path, without choosing roles.

    These are observations at three widths, not a stylesheet or inferred breakpoints.
    Reuse the same freshness and sample rules as frozen role references so the read
    cannot present a weaker measurement as a usable reference.
    """
    nodes = {}
    for width in WIDTHS:
        layout = layouts.get(width)
        if not _current(layout, identity, width):
            raise TypographyReferenceError(
                "typography.measurements_unavailable",
                f"Current native measurements at {width}px are missing, stale or unavailable.",
            )
        assert layout is not None
        matches = [n for n in layout.get("nodes", []) if n.get("node_id") == node_id]
        if len(matches) != 1 or matches[0].get("status") != "measured":
            raise TypographyReferenceError(
                "typography.node_not_measured",
                f"No unique measured node {node_id!r} at {width}px; inspect the layout index.",
            )
        nodes[width] = matches[0]

    paths = list(dict.fromkeys(
        text.get("rendered_path") for node in nodes.values() for text in node.get("texts", [])
        if isinstance(text.get("rendered_path"), str)
        and _PATH.fullmatch(text["rendered_path"]) is not None
    ))
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= len(paths):
        raise TypographyReferenceError(
            "typography.bad_offset", f"Use a text offset from zero through {len(paths)}.",
        )
    coverage = {
        str(width): {
            "complete": node.get("complete") is True,
            "omitted": copy.deepcopy(node.get("omitted") or {}),
            "invalid_paths": sum(
                not isinstance(t.get("rendered_path"), str)
                or _PATH.fullmatch(t["rendered_path"]) is None
                for t in node.get("texts", [])
            ),
        } for width, node in nodes.items()
    }
    rows = []
    for path in paths:
        widths = {}
        for width in WIDTHS:
            text = _text(layouts[width], node_id, path)
            sample, gaps = _sample(text)
            widths[str(width)] = {
                "status": "incomplete" if gaps else "hidden" if not sample["css_visible"]
                else "observed",
                "text_excerpt": str((text or {}).get("text") or "")[:160],
                "sample": sample,
                "gaps": gaps,
            }
        rows.append({"reference_path": path, "widths": widths})
    next_offset = offset + 8 if offset + 8 < len(paths) else None
    measurements_complete = all(
        c["complete"] and not c["invalid_paths"] and not any(c["omitted"].values())
        for c in coverage.values()
    ) and all(not w["gaps"] for row in rows for w in row["widths"].values())
    return {
        "status": "observed",
        "scope": "current_native_render_text_measurements",
        **identity,
        "reference_node_id": node_id,
        "kind": nodes[1440].get("kind"),
        "fragment_id": nodes[1440].get("fragment_id"),
        "path_space": "rendered_node_relative",
        "total_captured_paths": len(paths),
        "offset": offset,
        "next_target": None if next_offset is None else
        f"typography:node:{node_id}:offset:{next_offset}",
        "measurements_complete": measurements_complete,
        "complete": offset == 0 and next_offset is None and measurements_complete,
        "capture_coverage": coverage,
        "texts": rows[offset:offset + 8],
        "quality_verdict": "not_computed",
        "note": "Choose equivalent source and target roles deliberately, then freeze them with "
        "set_web_typography_reference. This view does not register references, alter CSS, infer "
        "breakpoints or prove this node is an original source. Verify fragment provenance. "
        "Rendered paths are not stored text-edit paths. Excerpts are limited to 160 characters. "
        "measurements_complete describes the saved inventory, not what the agent has read. "
        "complete is true only when this response includes that entire complete inventory.",
    }


def typography_coverage(
    layouts: dict[int, dict[str, Any]],
    identity: dict[str, Any],
    targets: list[dict[str, Any]],
    provenance: dict[str, dict[str, Any]],
    bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Require source mappings for each observed style in an authored fragment.

    Identical styles may share a representative within one node, across ALL
    widths. A bound heading never covers an unbound body style or another node.
    Only current reachable pins count; unknown provenance is not a captured pin.
    This does not judge whether the chosen source role is semantically suitable.
    """
    fragments = [target for target in targets if target.get("kind") == "fragment"]
    captured = {
        target["node_id"] for target in fragments
        if "composed" in provenance.get(target.get("fragment_id"), {})
        and not provenance[target["fragment_id"]]["composed"]
    }
    reports = []
    gaps = []
    required_count = uncovered_count = 0
    for target in fragments:
        node_id, fragment_id = target["node_id"], target.get("fragment_id")
        meta = provenance.get(fragment_id, {})
        if "composed" not in meta:
            gaps.append({
                "node_id": node_id, "code": "fragment_provenance_unavailable",
                "next_step": f"search_cloned_sections(q={fragment_id!r}) to inspect its provenance",
            })
            continue
        if not meta["composed"]:
            continue
        node_gaps = []
        rows_by_width = {}
        for width in WIDTHS:
            layout = layouts.get(width)
            nodes = [n for n in (layout or {}).get("nodes", []) if n.get("node_id") == node_id]
            if (
                not _current(layout, identity, width) or len(nodes) != 1
                or nodes[0].get("status") != "measured"
            ):
                node_gaps.append({"width": width, "code": "current_measurement_missing"})
                continue
            node = nodes[0]
            omitted = node.get("omitted") or {}
            if (
                node.get("complete") is not True
                and not all(
                    key in omitted and omitted[key] == 0 for key in ("texts", "descendants")
                )
            ):
                node_gaps.append({"width": width, "code": "text_inventory_incomplete"})
            rows = {}
            for text in node.get("texts", []):
                path = text.get("rendered_path")
                if not isinstance(path, str) or _PATH.fullmatch(path) is None or path in rows:
                    node_gaps.append({"width": width, "code": "text_path_invalid_or_ambiguous"})
                    continue
                rows[path] = text
            rows_by_width[width] = rows
        paths = list(dict.fromkeys(path for rows in rows_by_width.values() for path in rows))
        groups = {}
        glyphs = {}
        for path in paths:
            samples = {}
            visible = False
            path_gaps = []
            for width in WIDTHS:
                text = rows_by_width.get(width, {}).get(path)
                observed, missing = _sample(text)
                visible = visible or observed.get("css_visible") is True
                glyphs[(path, width)] = observed.pop("glyph_faces", None)
                samples[str(width)] = {**observed, "role": (text or {}).get("role")}
                # Coverage compares every CSS role; bounded glyph probes compare
                # representatives through the frozen reference tool separately.
                path_gaps.extend(
                    {"width": width, "code": gap} for gap in missing
                    if gap != "glyph_faces_unmeasured"
                )
            if path_gaps:
                node_gaps.append({
                    "path": path, "code": "text_measurement_incomplete", "gaps": path_gaps,
                })
                continue
            if not visible:
                continue
            signature = json.dumps(samples, sort_keys=True)
            groups.setdefault(signature, []).append(path)
        roles = []
        for paths in groups.values():
            declared = [b for b in bindings if (
                b.get("page_id") == identity["page_id"]
                and b["target_node_id"] == node_id and b["target_path"] in paths
            )]
            valid = [b for b in declared if b["reference_node_id"] in captured]
            variation = []
            for width in WIDTHS:
                compared = [glyphs.get((b["target_path"], width)) for b in valid]
                variation.extend(
                    {"path": path, "width": width} for path in paths
                    if valid and glyphs.get((path, width))
                    and glyphs[(path, width)] not in compared
                )
            covered = bool(valid) and not variation
            required_count += 1
            uncovered_count += not covered
            unmeasured = [path for path in paths if any(
                rows_by_width[w][path].get("css_visible") is True and not glyphs.get((path, w))
                for w in WIDTHS
            )]
            roles.append({
                "representative_path": next((p for p in paths if p not in unmeasured), paths[0]),
                "equivalent_paths": paths, "glyph_unmeasured_paths": unmeasured,
                "unmapped_glyph_variations": variation,
                "status": "covered" if covered else "unmapped",
                "gap": None if covered else "glyph_variation_unmapped" if variation
                else "captured_reference_required" if declared
                else "reference_not_declared",
            })
        reports.append({
            "node_id": node_id, "fragment_id": fragment_id, "roles": roles,
            "gaps": node_gaps, "inspect_target": f"typography:node:{node_id}",
        })
    incomplete = bool(gaps or uncovered_count or any(row["gaps"] for row in reports))
    return {
        "status": "incomplete" if incomplete else "covered" if reports else "not_applicable",
        "scope": "reachable_authored_fragment_text_current_page",
        "required_role_count": required_count, "uncovered_role_count": uncovered_count,
        "nodes": reports, "gaps": gaps,
        "note": "Map each distinct authored CSS text style to a captured fragment role. "
        "One representative covers only identical styles within that same node at all widths. "
        "Use a fragment node as the source; a composed draft cannot verify itself. "
        "Covered means mapped, not matched: inspect the reference comparison separately. "
        "Glyphs are checked on mapped representatives; unsampled glyph paths remain listed, "
        "not certified. Any observed font variation needs its own mapping. "
        "This does not qualify copy, structure, reference choice or aesthetic quality.",
    }


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
            frozen_source = next((b for b in pending if all(
                b[k] == identity[k] for k in ("document_id", "page_id")
            ) and all(b[k] == row[k] for k in ("reference_node_id", "reference_path"))), None)
            if frozen_source is not None:
                # A raw target gets its real node ID only after mint/pin. Reuse the
                # source frozen before that mutation, never the latest changed draft.
                samples = frozen_source["samples"]
                reference_identity = {k: frozen_source[k] for k in identity}
            else:
                samples = {}
                reference_identity = identity
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
            pending.append({**row, **reference_identity, "samples": copy.deepcopy(samples)})
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
