"""D2.3 acceptance tests: the brand + asset DAL port (PD contract §7).

Covers the ported semantics that matter most:

* brand kits: create → latest-vs-exact get, ``all_versions`` listing order, and the approval
  flip writing BOTH the enum column and the mirrored ``brand_kit_json.approval_status``.
* compatibility reports: round-trip through the ``from_ref``/``to_ref`` shape.
* assets: the canonical upsert (re-create refreshes, never duplicates), and
  ``register_scene_assets`` — insert-unseen, refresh-byte-identity-on-digest-change while
  PRESERVING curated columns, and the written-row counts.
* ``count_assets_with_digest`` is workspace-isolated (the same digest in two workspaces counts
  separately) — the fail-closed tenancy rule the SQLite original had no concept of.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import assets as design_assets
from clue_design import brand as design_brand
from tests.design.conftest import run_async


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_brand_{uuid4().hex[:12]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


def _kit(kit_id: str, version: int, *, approval: str = "draft") -> dict[str, Any]:
    return {
        "id": kit_id,
        "version": version,
        "name": f"{kit_id} v{version}",
        "approval_status": approval,
        "tokens": {"color": {"primary": "#123456"}},
    }


def _asset_record(asset_id: str, digest: str, *, label: str = "Logo") -> dict[str, Any]:
    return {
        "id": asset_id,
        "label": label,
        "kind": "image",
        "status": "ready",
        "tags": ["brand"],
        "media": {
            "mime_type": "image/png",
            "byte_length": 1024,
            "filename": f"{asset_id}.png",
            "digest": {"algorithm": "sha256", "value": digest},
            "location": {"provider": "local-store", "opaque_ref": f"sha256/{digest[:2]}/{digest}"},
        },
    }


def _scene(doc_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "meta": {"id": doc_id, "title": "T", "status": {"kind": "draft"}},
        "nodes": [],
        "assets": {str(record["id"]): record for record in records},
    }


def test_brand_kit_versions_latest_and_listing_order(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            kit_id = f"kit_{uuid4().hex[:10]}"
            other_id = f"kit_{uuid4().hex[:10]}"
            created = await design_brand.create_brand_kit(
                conn,
                workspace_id=ws,
                brand_kit=_kit(kit_id, 1),
                brand_summary={"product_ready": False},
                diagnostics=[],
                source="website",
            )
            assert created["version"] == 1
            assert created["source"] == "website"
            assert created["product_ready"] is False
            assert created["brand_kit"]["tokens"]["color"]["primary"] == "#123456"
            assert isinstance(created["created_at"], str)  # ISO parity with the SQLite API
            await design_brand.create_brand_kit(
                conn,
                workspace_id=ws,
                brand_kit=_kit(kit_id, 2),
                brand_summary={"product_ready": True},
                diagnostics=[{"code": "ok"}],
                source="manual",
            )
            await design_brand.create_brand_kit(
                conn,
                workspace_id=ws,
                brand_kit=_kit(other_id, 1),
                brand_summary={},
                diagnostics=[],
                source="generated",
            )
            # No version -> the latest; an explicit version -> exactly that one.
            latest = await design_brand.get_brand_kit(conn, workspace_id=ws, brand_kit_id=kit_id)
            assert latest["version"] == 2 and latest["product_ready"] is True
            assert latest["diagnostics"] == [{"code": "ok"}]
            pinned = await design_brand.get_brand_kit(
                conn, workspace_id=ws, brand_kit_id=kit_id, version=1
            )
            assert pinned["version"] == 1
            # Default listing: one row per kit (the latest), kit id ascending.
            newest = await design_brand.list_brand_kits(conn, workspace_id=ws)
            assert [(r["brand_kit_id"], r["version"]) for r in newest] == sorted(
                [(kit_id, 2), (other_id, 1)]
            )
            every = await design_brand.list_brand_kits(conn, workspace_id=ws, all_versions=True)
            assert [(r["brand_kit_id"], r["version"]) for r in every] == sorted(
                [(kit_id, 2), (kit_id, 1), (other_id, 1)],
                key=lambda pair: (pair[0], -pair[1]),
            )
            await txn.rollback()

    run_async(_check())


def test_update_brand_kit_approval_writes_column_and_mirrored_json(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            kit_id = f"kit_{uuid4().hex[:10]}"
            await design_brand.create_brand_kit(
                conn,
                workspace_id=ws,
                brand_kit=_kit(kit_id, 1),
                brand_summary={},
                diagnostics=[],
                source="manual",
            )
            # The flip targets the LATEST version only.
            await design_brand.create_brand_kit(
                conn,
                workspace_id=ws,
                brand_kit=_kit(kit_id, 2),
                brand_summary={},
                diagnostics=[],
                source="manual",
            )
            updated = await design_brand.update_brand_kit_approval(
                conn, workspace_id=ws, brand_kit_id=kit_id, approval_status="approved"
            )
            assert updated["version"] == 2
            assert updated["approval_status"] == "approved"
            assert updated["brand_kit"]["approval_status"] == "approved"  # mirrored JSON
            older = await design_brand.get_brand_kit(
                conn, workspace_id=ws, brand_kit_id=kit_id, version=1
            )
            assert older["approval_status"] == "draft"
            assert older["brand_kit"]["approval_status"] == "draft"
            await txn.rollback()

    run_async(_check())


def test_brand_compat_report_round_trip(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            kit_id = f"kit_{uuid4().hex[:10]}"
            from_kit = _kit(kit_id, 1)
            to_kit = _kit(kit_id, 2)
            for kit in (from_kit, to_kit):
                await design_brand.create_brand_kit(
                    conn,
                    workspace_id=ws,
                    brand_kit=kit,
                    brand_summary={},
                    diagnostics=[],
                    source="manual",
                )
            report_id = f"brand_report_{uuid4().hex[:10]}"
            stored = await design_brand.create_brand_compat_report(
                conn,
                workspace_id=ws,
                report_id=report_id,
                from_brand_kit=from_kit,
                to_brand_kit=to_kit,
                report={"breaking_changes": []},
                diagnostics=[{"code": "compat"}],
            )
            assert stored["from_ref"] == {"id": kit_id, "version": 1}
            assert stored["to_ref"] == {"id": kit_id, "version": 2}
            fetched = await design_brand.get_brand_compat_report(
                conn, workspace_id=ws, report_id=report_id
            )
            assert fetched["report"] == {"breaking_changes": []}
            assert fetched["diagnostics"] == [{"code": "compat"}]
            await txn.rollback()

    run_async(_check())


def test_create_asset_record_upserts_rather_than_duplicating(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            asset_id = f"asset_{uuid4().hex[:12]}"
            first = await design_assets.create_asset_record(
                conn, workspace_id=ws, record=_asset_record(asset_id, "a" * 64)
            )
            assert first["asset"]["label"] == "Logo"
            second = await design_assets.create_asset_record(
                conn,
                workspace_id=ws,
                record=_asset_record(asset_id, "b" * 64, label="Logo (revised)"),
            )
            assert second["asset"]["label"] == "Logo (revised)"
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM design_asset"
                        " WHERE asset_id = :a AND workspace_id = :w"
                    ),
                    {"a": asset_id, "w": ws},
                )
            ).scalar_one()
            assert count == 1  # upsert, never a second row
            listed = await design_assets.list_asset_records(conn, workspace_id=ws)
            assert [row["asset"]["id"] for row in listed] == [asset_id]
            archived = await design_assets.update_asset_status(
                conn, workspace_id=ws, asset_id=asset_id, status="archived"
            )
            assert archived["asset"]["status"] == "archived"
            assert await design_assets.list_asset_records(conn, workspace_id=ws) == []
            assert (
                len(
                    await design_assets.list_asset_records(
                        conn, workspace_id=ws, include_archived=True
                    )
                )
                == 1
            )
            await txn.rollback()

    run_async(_check())


def test_register_scene_assets_inserts_unseen_and_refreshes_byte_identity(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex[:12]}"
            promoted_id = f"asset_{uuid4().hex[:12]}"
            curated_id = f"asset_{uuid4().hex[:12]}"
            old_digest, new_digest = "c" * 64, "d" * 64
            # A curated library row the scene will later carry with NEW bytes.
            await design_assets.create_asset_record(
                conn,
                workspace_id=ws,
                record=_asset_record(curated_id, old_digest, label="Curated hero"),
            )
            scene = _scene(
                doc_id,
                [
                    _asset_record(promoted_id, "e" * 64),
                    _asset_record(curated_id, old_digest, label="scene-side label"),
                ],
            )
            # Only the unseen id is written; the byte-identical existing row is untouched.
            assert (
                await design_assets.register_scene_assets(conn, workspace_id=ws, scene=scene) == 1
            )
            assert (
                await design_assets.get_asset_record(conn, workspace_id=ws, asset_id=promoted_id)
            )["asset"]["id"] == promoted_id
            curated = await design_assets.get_asset_record(
                conn, workspace_id=ws, asset_id=curated_id
            )
            assert curated["asset"]["label"] == "Curated hero"  # curation not clobbered
            # Re-run unchanged: nothing to write.
            assert (
                await design_assets.register_scene_assets(conn, workspace_id=ws, scene=scene) == 0
            )
            # Regenerate-in-place: the digest moved, so byte identity refreshes — and ONLY it.
            regenerated = _asset_record(curated_id, new_digest, label="scene-side label")
            regenerated["tags"] = ["scene-side"]
            assert (
                await design_assets.register_scene_assets(
                    conn,
                    workspace_id=ws,
                    scene=_scene(doc_id, [_asset_record(promoted_id, "e" * 64), regenerated]),
                )
                == 1
            )
            refreshed = await design_assets.get_asset_record(
                conn, workspace_id=ws, asset_id=curated_id
            )
            assert refreshed["asset"]["media"]["digest"]["value"] == new_digest
            assert refreshed["asset"]["label"] == "Curated hero"  # curated: preserved
            assert refreshed["asset"]["tags"] == ["brand"]  # curated: preserved
            row = (
                await conn.execute(
                    text(
                        "SELECT digest_value, label, tags_json FROM design_asset"
                        " WHERE asset_id = :a AND workspace_id = :w"
                    ),
                    {"a": curated_id, "w": ws},
                )
            ).first()
            assert row is not None
            assert row.digest_value == new_digest
            assert row.label == "Curated hero"
            await txn.rollback()

    run_async(_check())


def test_register_scene_assets_skips_non_local_and_mismatched_records(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            remote = _asset_record(f"asset_{uuid4().hex[:12]}", "f" * 64)
            remote["media"]["location"] = {"provider": "https", "url": "https://x.example/a.png"}
            mismatched = _asset_record(f"asset_{uuid4().hex[:12]}", "0" * 64)
            scene = {
                "meta": {"id": f"doc_{uuid4().hex[:12]}", "title": "T"},
                "assets": {
                    str(remote["id"]): remote,
                    # Key that disagrees with the record's own id: malformed, never promoted.
                    "asset_not_the_records_id": mismatched,
                },
            }
            assert (
                await design_assets.register_scene_assets(conn, workspace_id=ws, scene=scene) == 0
            )
            assert await design_assets.list_asset_records(conn, workspace_id=ws) == []
            await txn.rollback()

    run_async(_check())


def test_count_assets_with_digest_is_workspace_isolated(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws_a = await _seed_ws(conn)
            ws_b = await _seed_ws(conn)
            digest = "1" * 64
            # The SAME content-derived asset id + digest in two workspaces (the shape that
            # forced the workspace-local asset key).
            asset_id = f"asset_ing_{uuid4().hex[:16]}"
            for ws in (ws_a, ws_b):
                await design_assets.create_asset_record(
                    conn, workspace_id=ws, record=_asset_record(asset_id, digest)
                )
            assert (
                await design_assets.count_assets_with_digest(
                    conn, workspace_id=ws_a, digest_value=digest
                )
                == 1
            )
            assert (
                await design_assets.count_assets_with_digest(
                    conn, workspace_id=ws_b, digest_value=digest
                )
                == 1
            )
            assert (
                await design_assets.count_assets_with_digest(
                    conn,
                    workspace_id=ws_a,
                    digest_value=digest,
                    exclude_asset_id=asset_id,
                )
                == 0
            )
            # Deleting one tenant's row leaves the other's intact.
            await design_assets.delete_asset_record(conn, workspace_id=ws_a, asset_id=asset_id)
            assert (
                await design_assets.count_assets_with_digest(
                    conn, workspace_id=ws_a, digest_value=digest
                )
                == 0
            )
            assert (
                await design_assets.count_assets_with_digest(
                    conn, workspace_id=ws_b, digest_value=digest
                )
                == 1
            )
            await txn.rollback()

    run_async(_check())


def test_the_brand_mark_is_the_favicon_default_only_when_unambiguous(
    require_design_db: None,
) -> None:
    """The page origin's default `/favicon.ico` (2026-09-30): the approved kit's
    `assets.logos.mark` — the icon website ingestion took from the client's own site — for a
    one-brand workspace; None for a draft kit, a kit with no mark, or a second brand."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            brand_id = f"brd_{uuid4().hex[:12]}"
            await conn.execute(
                text("INSERT INTO brand (brand_id, workspace_id, name) VALUES (:b, :w, :n)"),
                {"b": brand_id, "w": ws, "n": "Acme"},
            )
            digest = uuid4().hex + uuid4().hex
            await design_assets.create_asset_record(
                conn, workspace_id=ws, record=_asset_record("asset_mark", digest)
            )
            kit_id = f"kit_{uuid4().hex[:10]}"
            kit = _kit(kit_id, 1, approval="draft")
            kit["assets"] = {"logos": {"mark": {"variants": [{"asset_id": "asset_mark"}]}}}

            async def _publish(payload: dict[str, Any]) -> None:
                await design_brand.create_brand_kit(
                    conn,
                    workspace_id=ws,
                    brand_kit=payload,
                    brand_summary={},
                    diagnostics=[],
                    source="website",
                    brand_id=brand_id,
                )

            await _publish(kit)
            mark = design_brand.approved_brand_mark_sha256
            assert await mark(conn, workspace_id=ws) is None, "a draft kit is not the brand yet"

            await design_brand.update_brand_kit_approval(
                conn, workspace_id=ws, brand_kit_id=kit_id, approval_status="approved"
            )
            assert await mark(conn, workspace_id=ws) == digest

            unmarked = _kit(kit_id, 2, approval="approved")
            await _publish(unmarked)
            assert await mark(conn, workspace_id=ws) is None, "the newest approved kit has no mark"

            await _publish({**kit, "version": 3, "approval_status": "approved"})
            assert await mark(conn, workspace_id=ws) == digest
            await conn.execute(
                text("INSERT INTO brand (brand_id, workspace_id, name) VALUES (:b, :w, :n)"),
                {"b": f"brd_{uuid4().hex[:12]}", "w": ws, "n": "Second brand"},
            )
            assert await mark(conn, workspace_id=ws) is None, "two brands: never a guess"
            await txn.rollback()

    run_async(_check())
