"""Shared curated faces are readable without exposing another tenant's assets."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lumen_api import font_library
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.main import create_app

from clue_design.storage import SOURCE_KEY_FONT

FONT_BYTES = (Path(__file__).resolve().parents[3] / "fonts/Inter-Regular.ttf").read_bytes()
FONT_DIGEST = hashlib.sha256(FONT_BYTES).hexdigest()
FONT_ID = f"asset_font_lib_inter_w400_{FONT_DIGEST[:12]}"


def seed_asset(storage, workspace_id, asset_id=FONT_ID, data=FONT_BYTES, kind="font"):
    digest = hashlib.sha256(data).hexdigest()
    key = DesignBlobStore(storage, workspace_id).register(
        data, media_type="font/ttf", source_key=SOURCE_KEY_FONT
    )
    record = {
        "id": asset_id,
        "label": "Font fixture",
        "kind": kind,
        "status": "ready",
        "media": {
            "mime_type": "font/ttf",
            "digest": {"algorithm": "sha256", "value": digest},
            "byte_length": len(data),
            "filename": "Inter-Regular.ttf",
            "location": {"provider": "clue-storage", "opaque_ref": key, "url": None},
        },
    }
    HybridRepository(workspace_id).create_asset_record(record)
    return record


@pytest.fixture()
def shared_font_client(tmp_path, monkeypatch, design_storage, workspace_id):
    manifest_path = tmp_path / "font-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "families": [
                    {
                        "family": "Inter",
                        "faces": [
                            {
                                "asset_id": FONT_ID,
                                "digest": FONT_DIGEST,
                                "weight": 400,
                                "style": "normal",
                            }
                        ],
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(font_library.settings, "lumen_font_library_manifest_path", manifest_path)
    monkeypatch.setattr(font_library, "_cache", {"path": None, "mtime": None, "manifest": None})
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    # Read routes need no fleet lifespan. Use a different caller from the library workspace.
    return TestClient(app, headers={"X-Workspace-Id": workspace_id + "_caller"})


def test_shared_curated_font_bytes_are_available_from_another_workspace(
    shared_font_client, design_storage, workspace_id
):
    seed_asset(design_storage, workspace_id)

    response = shared_font_client.get(f"/assets/{FONT_ID}/bytes")

    assert response.status_code == 200, response.text
    assert response.content == FONT_BYTES
    assert response.headers["content-type"] == "font/ttf"


@pytest.mark.parametrize(
    "asset_id",
    [
        "asset_font_lib_inter_w400_not_in_manifest",
        "asset_user_private_font",
        "asset_private_image",
    ],
)
def test_shared_font_read_refuses_assets_outside_the_manifest(
    shared_font_client, design_storage, workspace_id, asset_id
):
    seed_asset(design_storage, workspace_id, asset_id=asset_id)

    assert shared_font_client.get(f"/assets/{asset_id}/bytes").status_code == 404


def test_shared_font_read_refuses_a_nonfont_record_even_when_allowlisted(
    shared_font_client, design_storage, workspace_id
):
    seed_asset(design_storage, workspace_id, kind="image")

    assert shared_font_client.get(f"/assets/{FONT_ID}/bytes").status_code == 404


def test_shared_font_read_refuses_an_unprovisioned_face(shared_font_client):
    assert shared_font_client.get(f"/assets/{FONT_ID}/bytes").status_code == 404
    assert shared_font_client.get("/assets/unknown/bytes").status_code == 404


def test_shared_font_read_does_not_search_other_tenant_workspaces(
    shared_font_client, design_storage, workspace_id
):
    seed_asset(design_storage, workspace_id + "_private")

    assert shared_font_client.get(f"/assets/{FONT_ID}/bytes").status_code == 404


def test_shared_font_read_refuses_missing_durable_bytes(
    shared_font_client, design_storage, workspace_id
):
    record = seed_asset(design_storage, workspace_id)
    asyncio.run(design_storage.delete(record["media"]["location"]["opaque_ref"]))

    assert shared_font_client.get(f"/assets/{FONT_ID}/bytes").status_code == 404


@pytest.mark.parametrize("corruption", ["record_digest", "location_digest", "stored_bytes"])
def test_shared_font_read_requires_the_manifest_digest_at_each_boundary(
    shared_font_client, design_storage, workspace_id, corruption
):
    record = seed_asset(design_storage, workspace_id)
    if corruption == "record_digest":
        record["media"]["digest"]["value"] = "a" * 64
        HybridRepository(workspace_id).create_asset_record(record)
    elif corruption == "location_digest":
        record["media"]["location"]["opaque_ref"] = f"{workspace_id}/design/{'a' * 64}"
        HybridRepository(workspace_id).create_asset_record(record)
    else:
        asyncio.run(
            design_storage.put(
                record["media"]["location"]["opaque_ref"],
                b"corrupt font bytes",
                media_type="font/ttf",
            )
        )

    assert shared_font_client.get(f"/assets/{FONT_ID}/bytes").status_code == 404


def test_shared_font_read_preserves_the_callers_own_asset(
    shared_font_client, design_storage, workspace_id
):
    seed_asset(design_storage, workspace_id)
    seed_asset(design_storage, workspace_id + "_caller", data=b"caller-owned bytes")

    response = shared_font_client.get(f"/assets/{FONT_ID}/bytes")

    assert response.status_code == 200, response.text
    assert response.content == b"caller-owned bytes"


def test_shared_font_read_still_requires_a_workspace(
    shared_font_client, design_storage, workspace_id
):
    seed_asset(design_storage, workspace_id)
    shared_font_client.headers.clear()

    assert shared_font_client.get(f"/assets/{FONT_ID}/bytes").status_code == 401
