"""Recover a design document's scene as it stood BEFORE a given edit batch.

Why this exists
---------------
On 2026-09-20 the founder opened three real LinkedIn ads in the editor and clicked a
node in each. That first click ran the freeze bake, which rewrote every ``fill`` /
``hug`` size in the tree to the solved pixel extent and stamped
``layout.layout_mode = "free"``. The bug the freeze-bake-fill-parity plan fixes is in
that bake, so the tests need the trees as the AGENT authored them — fills and hugs
intact — not as the editor left them.

Nothing snapshots a pre-edit scene, but every batch is journalled with its own
inverse: ``design_edit_envelope.inverse_operations_json``. So the recovery is a walk
backwards. Start from ``design_document.current_scene_json`` (the newest state) and
apply every envelope's inverse, newest ``seq`` first, down to and including the batch
you want to land in front of. Undo/redo rows are walked like any other row — each one
is a real batch with a real inverse, so walking ALL of them backwards reconstructs the
state before the lowest seq regardless of what the rows meant.

Each inverse is applied through the same Rust engine that produced it
(``lumen_api.core.CoreClient.apply_operations``), never by hand-patching JSON: the
inverse ops are engine-shaped patches and only the engine knows how to land them.

The output is FIXTURE bytes, so the script also strips every node's ``computed``
block (a fixture carries authored state; the solver fills ``computed`` itself) and
asserts the recovered tree really is pre-freeze — no ``auto_layout`` node may carry
``layout.layout_mode = "free"``.

This is READ-ONLY against the database. It opens one connection, runs two SELECTs,
and writes a file.

Setup
-----
    set -a; source .env; set +a          # CLUE_DATABASE_URL + LUMEN_CORE_HELPER
    uv run python scripts/design_prefreeze_scene.py \
        doc_9f772c46411751fba2fa59bb5f86a69e \
        --before-seq 3 \
        --out subsystems/clue-design/crates/lumen-core/fixtures/scenes/\
freeze/capital_digestive_care_ad.json

``--before-seq`` is the seq of the first batch you want undone — for the three
2026-09-20 ads that is the first ``actor_kind='editor'`` row (seq 3 in all three), the
batch the founder's click produced. Find it with::

    select seq, base_revision, actor_kind, intent
    from design_edit_envelope where document_id = '<doc>' order by seq;

``--out -`` prints the scene to stdout instead of writing a file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan

__all__ = ["recover_scene", "strip_computed", "check_prefreeze"]

JsonObject = dict[str, Any]

_DOCUMENT_SQL = text(
    "SELECT title, current_version, current_scene_json FROM design_document WHERE id = :document_id"
)

_ENVELOPE_SQL = text(
    "SELECT seq, base_revision, actor_kind, source, intent, "
    "       reverts_batch_id, reapplies_batch_id, operations_json, inverse_operations_json "
    "FROM design_edit_envelope "
    "WHERE document_id = :document_id AND seq >= :before_seq "
    "ORDER BY seq DESC"
)


def _as_json(raw: Any) -> Any:
    """jsonb comes back parsed on one driver and as text on another — accept both."""
    if isinstance(raw, str | bytes | bytearray):
        return json.loads(raw)
    return raw


def strip_computed(value: Any) -> Any:
    """Null out every ``computed`` block in the tree.

    A fixture is AUTHORED state: the solver computes geometry from the authored
    sizes, so a committed ``computed`` block would let a test pass against stale
    solved numbers instead of the engine's own answer. The engine's own scene shape
    keeps the key and nulls it, so that is what we write (a missing key would be a
    shape this repo never emits).
    """
    if isinstance(value, dict):
        return {
            key: (None if key == "computed" else strip_computed(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [strip_computed(item) for item in value]
    return value


def _node_kind(node: JsonObject) -> str | None:
    kind = node.get("kind")
    if isinstance(kind, dict):
        inner = kind.get("kind")
        return inner if isinstance(inner, str) else None
    return kind if isinstance(kind, str) else None


def check_prefreeze(scene: JsonObject, document_id: str) -> JsonObject:
    """Assert the recovered scene is the pre-freeze tree, and report what it holds.

    Raises ``AssertionError`` on anything that would make the fixture a lie: a scene
    that belongs to another document, a surviving ``computed`` block, or an
    ``auto_layout`` node still carrying the bake's ``layout_mode = "free"``.
    """
    meta_id = (scene.get("meta") or {}).get("id")
    assert meta_id == document_id, f"scene meta.id is {meta_id!r}, expected {document_id!r}"

    nodes = scene.get("nodes") or {}
    assert isinstance(nodes, dict) and nodes, "recovered scene carries no nodes"

    containers: list[str] = []
    fill_width: list[str] = []
    fill_height: list[str] = []
    hug: list[str] = []
    frozen: list[str] = []

    for node_id, node in sorted(nodes.items()):
        assert node.get("computed") is None, f"node {node_id} still carries a computed block"
        size = node.get("size") or {}
        width_kind = (size.get("width") or {}).get("kind")
        height_kind = (size.get("height") or {}).get("kind")
        if width_kind == "fill":
            fill_width.append(node_id)
        if height_kind == "fill":
            fill_height.append(node_id)
        if "hug" in {width_kind, height_kind}:
            hug.append(node_id)
        if _node_kind(node) != "auto_layout":
            continue
        containers.append(node_id)
        layout_mode = (node.get("layout") or {}).get("layout_mode")
        if layout_mode not in (None, "stack"):
            frozen.append(f"{node_id}={layout_mode}")

    assert not frozen, (
        "auto_layout nodes still carry a baked layout_mode — this scene is NOT "
        f"pre-freeze: {', '.join(frozen)}"
    )

    return {
        "node_count": len(nodes),
        "containers": containers,
        "fill_width": fill_width,
        "fill_height": fill_height,
        "hug": hug,
    }


async def _load_document(conn: AsyncConnection, document_id: str) -> tuple[str, int, JsonObject]:
    row = (await conn.execute(_DOCUMENT_SQL, {"document_id": document_id})).mappings().first()
    if row is None:
        raise SystemExit(f"no design_document with id {document_id!r}")
    scene = _as_json(row["current_scene_json"])
    if not isinstance(scene, dict):
        raise SystemExit(f"document {document_id!r} has no scene json")
    return str(row["title"]), int(row["current_version"]), scene


async def _load_envelopes(
    conn: AsyncConnection, document_id: str, before_seq: int
) -> list[JsonObject]:
    rows = (
        (await conn.execute(_ENVELOPE_SQL, {"document_id": document_id, "before_seq": before_seq}))
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def _apply_inverses(
    scene: JsonObject, envelopes: list[JsonObject], *, verbose: bool = True
) -> JsonObject:
    """Walk the journal backwards, landing each batch's inverse through the engine."""
    from lumen_api.core import CoreClient  # design app import; needs `uv run` at the repo root

    client = CoreClient()
    for envelope in envelopes:
        operations = _as_json(envelope["inverse_operations_json"])
        if not isinstance(operations, list):
            raise SystemExit(
                f"seq {envelope['seq']} has no inverse operations — the walk cannot pass it"
            )
        response = client.apply_operations(scene, operations)
        diagnostics = response.get("diagnostics") or []
        errors = [d for d in diagnostics if isinstance(d, dict) and d.get("severity") == "error"]
        if errors:
            raise SystemExit(f"seq {envelope['seq']} inverse produced errors: {json.dumps(errors)}")
        next_scene = response.get("scene")
        if not isinstance(next_scene, dict):
            raise SystemExit(f"seq {envelope['seq']} inverse returned no scene")
        scene = next_scene
        if verbose:
            kind = (
                "undo"
                if envelope["reverts_batch_id"]
                else ("redo" if envelope["reapplies_batch_id"] else "edit")
            )
            print(
                f"  seq {envelope['seq']:>3}  base_revision {envelope['base_revision']:>4}  "
                f"{envelope['actor_kind']:<6} {kind:<4}  "
                f"{len(operations):>3} inverse ops  <- {envelope['intent']!r}"
            )
    return scene


def _assert_no_layout_errors(scene: JsonObject) -> list[JsonObject]:
    """Solve the recovered scene with the real Rust layout; a fixture must lay out cleanly.

    ``layout_geometry`` is ``lumen_core::layout_scene`` behind the helper, so this is
    the same pass the tests will run. Warnings are fine and expected — the fixtures
    name brand families (``Aeonik``) that a bare checkout's font store does not carry,
    which shapes with a fallback face and emits ``LUMS0100``. An error-level
    diagnostic is not fine: it would mean the recovered tree is not a scene the
    engine accepts.
    """
    from lumen_api.core import CoreClient

    response = CoreClient().layout_geometry(scene)
    diagnostics = [d for d in response.get("diagnostics") or [] if isinstance(d, dict)]
    errors = [d for d in diagnostics if d.get("severity") == "error"]
    if errors:
        raise SystemExit(f"recovered scene fails to lay out: {json.dumps(errors, indent=2)}")
    return diagnostics


def _check_revision_chain(
    envelopes: list[JsonObject], current_version: int, before_seq: int
) -> None:
    """Refuse to walk a journal that does not describe the scene we start from.

    The walk assumes ``current_scene_json`` is exactly the head the newest envelope
    produced, and that no revision between ``before_seq`` and that head is missing.
    If either is false the recovered tree is a state that never existed, and nothing
    downstream would notice. So: each row's ``base_revision`` plus its operation count
    must equal the next row's ``base_revision``, and the newest row's result must equal
    ``current_version``.
    """
    ascending = list(reversed(envelopes))
    revision = int(ascending[0]["base_revision"])
    for envelope in ascending:
        base = int(envelope["base_revision"])
        if base != revision:
            raise SystemExit(
                f"journal hole before seq {envelope['seq']}: expected base_revision "
                f"{revision}, found {base}"
            )
        operations = _as_json(envelope["operations_json"])
        if not isinstance(operations, list):
            raise SystemExit(f"seq {envelope['seq']} has no forward operations")
        revision = base + len(operations)
    if revision != current_version:
        raise SystemExit(
            f"the journal ends at revision {revision} but the document is at "
            f"{current_version} — current_scene_json is not the head this walk assumes"
        )
    if int(ascending[0]["seq"]) != before_seq:
        raise SystemExit(
            f"lowest walked seq is {ascending[0]['seq']}, not {before_seq} — the journal has a hole"
        )


async def recover_scene(document_id: str, before_seq: int) -> tuple[JsonObject, JsonObject]:
    """Return ``(scene, report)`` for ``document_id`` as it stood before ``before_seq``."""
    async with db_lifespan() as engine, engine.connect() as conn:
        title, current_version, scene = await _load_document(conn, document_id)
        envelopes = await _load_envelopes(conn, document_id, before_seq)

    if not envelopes:
        raise SystemExit(f"no design_edit_envelope rows with seq >= {before_seq} for {document_id}")
    _check_revision_chain(envelopes, current_version, before_seq)
    lowest = envelopes[-1]

    print(f"{document_id}  {title!r}  current_version {current_version}")
    print(f"walking {len(envelopes)} envelope(s) backwards from seq {envelopes[0]['seq']}:")
    scene = _apply_inverses(scene, envelopes)
    landed_on = int(lowest["base_revision"])
    print(f"landed on revision {landed_on} (base_revision of seq {before_seq})")

    scene = strip_computed(scene)
    report = check_prefreeze(scene, document_id)
    diagnostics = _assert_no_layout_errors(scene)
    report["landed_on_revision"] = landed_on
    report["title"] = title
    report["diagnostics"] = diagnostics
    return scene, report


def _print_report(report: JsonObject) -> None:
    print(f"  nodes                 {report['node_count']}")
    print(f"  auto_layout containers {len(report['containers'])}: {report['containers']}")
    print(f"  fill width             {report['fill_width']}")
    print(f"  fill height            {report['fill_height']}")
    print(f"  hug width or height    {report['hug']}")
    codes = sorted({str(d.get("code")) for d in report["diagnostics"]})
    print(f"  layout diagnostics     {len(report['diagnostics'])} (no errors) {codes}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("document_id", help="design_document.id to recover")
    parser.add_argument(
        "--before-seq",
        type=int,
        required=True,
        help="recover the scene as it stood BEFORE this design_edit_envelope seq",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="file to write the recovered scene to, or '-' for stdout",
    )
    args = parser.parse_args()

    scene, report = asyncio.run(recover_scene(args.document_id, args.before_seq))
    _print_report(report)

    payload = json.dumps(scene, indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        print(payload)
        return
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload, encoding="utf-8")
    print(f"wrote {out} ({len(payload.encode('utf-8'))} bytes)")


if __name__ == "__main__":
    main()
