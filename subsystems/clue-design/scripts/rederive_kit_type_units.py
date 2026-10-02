#!/usr/bin/env python
"""Re-derive stored brand kits' type units after the px/16 fix (Editor Quality Plan 1, item A).

Before 2026-09-04 the harvester stored every px line-height and letter-spacing divided by the
ROOT size (16) instead of the element's. The kit's `type.*` roles inherited that: Apollo's
headline carried line_height 4.5. This script recomputes ONLY `line_height` and
`letter_spacing` of `tokens.typography.type.*` from the kit's stored ingestion evidence
(corrected in memory the same way the fixed parser would have produced it), publishes the
result as the kit's NEXT version (kit versions are immutable), and — with --repin-documents —
moves the documents pinned to the old version onto the new one.

Dry run by default: prints what would change and writes nothing.

    CLUE_DATABASE_URL=... python scripts/rederive_kit_type_units.py [--workspace WS] [--kit KIT]
    CLUE_DATABASE_URL=... python scripts/rederive_kit_type_units.py --apply --repin-documents
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Optional

import psycopg
from pydantic import ValidationError

from lumen_api.design_store import HybridRepository
from lumen_ingestion.evidence import BrandEvidence
from lumen_ingestion.normalizer.typography import (
    LINE_HEIGHT_RATIO_RANGE,
    build_type_styles,
    custodied_weights,
    resolve_anchors,
)

ROOT_PX = 16.0


class UnusableEvidence(Exception):
    """A job row's stored ``evidence_json`` is not a usable ``BrandEvidence`` document.

    Seen in the wild on the colombo database: a job that never got past its stub carries
    ``{"schema_version": 1}``. That is not a re-derivation FAILURE for the kit — there is simply
    nothing to re-derive from — so it is skipped like a missing evidence row, and it must never
    abort the sweep for the kits that come after it.
    """


@dataclass
class Summary:
    examined: int = 0
    changed: int = 0
    published: int = 0
    repinned_documents: int = 0
    skipped_no_evidence: int = 0
    failed: int = 0


def correct_type_units(evidence: BrandEvidence) -> BrandEvidence:
    """Undo px/16 on the samples that were px-derived.

    Rendered samples (`locator` starts with "rendered ::") are ALWAYS computed px values, so both
    fields are re-based on the sample's own size. Declared-CSS samples are ambiguous (an `em`
    value was stored correctly), so only a line-height outside the sane band — which can only
    have been px — is re-based; their letter-spacing is left alone.
    """
    low, high = LINE_HEIGHT_RATIO_RANGE
    samples = []
    for sample in evidence.type_samples:
        update: dict = {}
        size = sample.size_px
        rendered = sample.pointer.locator.startswith("rendered ::")
        if size:
            if sample.line_height and (rendered or not (low <= sample.line_height <= high)):
                update["line_height"] = round(sample.line_height * ROOT_PX / size, 4)
            if rendered and sample.letter_spacing is not None:
                update["letter_spacing"] = round(sample.letter_spacing * ROOT_PX / size, 4)
        samples.append(sample.model_copy(update=update) if update else sample)
    return evidence.model_copy(update={"type_samples": samples})


def recomputed_units(kit: dict, evidence: BrandEvidence) -> dict[str, dict[str, float]]:
    """{ "type.<role>": {"line_height": x, "letter_spacing": y} } for roles whose values move."""
    typography = kit.get("tokens", {}).get("typography", {})
    cta = (
        typography.get("type.cta", {})
        .get("value", {})
        .get("default", {})
        .get("color", "text.inverse")
    )
    styles, _ = build_type_styles(
        resolve_anchors(evidence), cta_color=cta, custodied=custodied_weights(evidence)
    )
    changes: dict[str, dict[str, float]] = {}
    for path, style in styles.items():
        current = typography.get(path, {}).get("value", {}).get("default")
        if not current:
            continue
        delta = {
            key: style[key]
            for key in ("line_height", "letter_spacing")
            if current.get(key) != style[key]
        }
        if delta:
            changes[path] = delta
    return changes


def _latest_kits(conn, workspace_id: Optional[str], brand_kit_id: Optional[str]):
    sql = (
        "SELECT DISTINCT ON (workspace_id, brand_kit_id) workspace_id, brand_kit_id, version"
        " FROM design_brand_kit WHERE brand_kit_id LIKE 'brand_kit_ing_%%'"
    )
    params: dict = {}
    if workspace_id:
        sql += " AND workspace_id = %(ws)s"
        params["ws"] = workspace_id
    if brand_kit_id:
        sql += " AND brand_kit_id = %(kit)s"
        params["kit"] = brand_kit_id
    sql += " ORDER BY workspace_id, brand_kit_id, version DESC"
    return conn.execute(sql, params).fetchall()


def _latest_evidence(conn, workspace_id: str, brand_kit_id: str) -> Optional[BrandEvidence]:
    row = conn.execute(
        "SELECT evidence_json FROM design_ingestion_job"
        " WHERE workspace_id = %s AND brand_kit_id = %s AND evidence_json IS NOT NULL"
        " ORDER BY created_at DESC LIMIT 1",
        (workspace_id, brand_kit_id),
    ).fetchone()
    if row is None:
        return None
    raw = row[0]
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        raise UnusableEvidence(f"evidence_json is a {type(payload).__name__}, not an object")
    # The JOB's evidence document is the BrandEvidence dump PLUS the website lane's ride-along
    # refs (`site_snapshots`, `web_fragments` — see `pipeline._evidence_dump`), and
    # `BrandEvidence` forbids extras. Keep only the evidence's own fields.
    try:
        return BrandEvidence.model_validate(
            {key: value for key, value in payload.items() if key in BrandEvidence.model_fields}
        )
    except ValidationError as error:
        raise UnusableEvidence(_one_line(error)) from error


def _one_line(error: ValidationError) -> str:
    """A pydantic ValidationError as ONE line, so a SKIP stays one grep-able row."""
    parts = [
        f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
        for item in error.errors()
    ]
    return "; ".join(parts[:3]) + (f"; (+{len(parts) - 3} more)" if len(parts) > 3 else "")


def _repin(conn, workspace_id: str, brand_kit_id: str, old: int, new: int) -> int:
    cursor = conn.execute(
        "UPDATE design_document SET effective_brand_kit_version = %s, updated_at = now()"
        " WHERE workspace_id = %s AND effective_brand_kit_id = %s"
        " AND effective_brand_kit_version = %s",
        (new, workspace_id, brand_kit_id, old),
    )
    conn.commit()
    return cursor.rowcount


def _rollback(conn) -> None:
    """Best-effort: clear an aborted transaction so the next kit's SELECT can still run."""
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001 — the sweep continues even if the connection is gone
        pass


def rederive_kit_type_units(
    conn,
    *,
    workspace_id: Optional[str] = None,
    brand_kit_id: Optional[str] = None,
    apply: bool = False,
    repin_documents: bool = False,
) -> Summary:
    summary = Summary()
    for ws, kit_id, version in _latest_kits(conn, workspace_id, brand_kit_id):
        summary.examined += 1
        # The READ phase is per-kit guarded too: one unreadable row must not cost every kit
        # after it in the sweep (a stub `evidence_json` used to abort the whole run).
        try:
            evidence = _latest_evidence(conn, ws, kit_id)
            if evidence is None:
                print(f"SKIP {ws}/{kit_id} v{version}: no stored evidence to re-derive from")
                summary.skipped_no_evidence += 1
                continue
            repo = HybridRepository(workspace_id=ws)
            row = repo.require_brand_kit(kit_id, version)
            kit = row["brand_kit"]
            changes = recomputed_units(kit, correct_type_units(evidence))
        except UnusableEvidence as error:
            print(
                f"SKIP {ws}/{kit_id} v{version}: stored evidence is not a usable BrandEvidence"
                f" ({error})"
            )
            summary.skipped_no_evidence += 1
            continue
        except Exception as error:  # noqa: BLE001 — one kit must not stop the sweep
            summary.failed += 1
            print(
                f"FAIL {ws}/{kit_id} v{version}: {type(error).__name__}: {error}",
                file=sys.stderr,
            )
            # A failed SELECT leaves psycopg's transaction aborted; without this every later
            # read would fail too, which is the abort this guard exists to prevent.
            _rollback(conn)
            continue
        if not changes:
            print(f"OK   {ws}/{kit_id} v{version}: type units already element-relative")
            continue
        summary.changed += 1
        for path, delta in changes.items():
            print(f"     {ws}/{kit_id} v{version} {path}: {delta}")
        if not apply:
            continue
        try:
            for path, delta in changes.items():
                kit["tokens"]["typography"][path]["value"]["default"].update(delta)
            diagnostics = list(row["diagnostics"] or []) + [
                {
                    "code": "LUMI0233",
                    "severity": "info",
                    "message": (
                        "type units re-derived from stored evidence on 2026-09-04 (px/16 fix): "
                        f"{', '.join(changes)}"
                    ),
                }
            ]
            published = repo.publish_next_brand_kit_version(
                kit,
                row["brand_summary"],
                diagnostics,
                row["source"],
                expected_base_version=version,
            )
            new_version = int(published["version"])
            summary.published += 1
            print(f"PUB  {ws}/{kit_id} v{version} -> v{new_version}")
            if repin_documents:
                count = _repin(conn, ws, kit_id, version, new_version)
                summary.repinned_documents += count
                print(f"PIN  {ws}/{kit_id}: {count} document(s) v{version} -> v{new_version}")
        except Exception as error:  # noqa: BLE001 — one kit must not stop the sweep
            summary.failed += 1
            print(
                f"FAIL {ws}/{kit_id} v{version}: {type(error).__name__}: {error}",
                file=sys.stderr,
            )
            _rollback(conn)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="publish new kit versions")
    parser.add_argument("--workspace", default=None, help="limit to one workspace id")
    parser.add_argument("--kit", default=None, help="limit to one brand_kit_id")
    parser.add_argument(
        "--repin-documents",
        action="store_true",
        help="move documents pinned to the old version onto the new one",
    )
    args = parser.parse_args()
    database_url = os.environ.get("CLUE_DATABASE_URL", "")
    if not database_url:
        print("CLUE_DATABASE_URL is required", file=sys.stderr)
        return 2
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    with psycopg.connect(dsn) as conn:
        summary = rederive_kit_type_units(
            conn,
            workspace_id=args.workspace,
            brand_kit_id=args.kit,
            apply=args.apply,
            repin_documents=args.repin_documents,
        )
    mode = "applied" if args.apply else "dry run — nothing written"
    print(
        f"{mode}: {summary.examined} examined, {summary.changed} needing change,"
        f" {summary.published} published, {summary.repinned_documents} documents repinned,"
        f" {summary.skipped_no_evidence} without evidence, {summary.failed} failed"
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
