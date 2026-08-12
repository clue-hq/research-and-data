"""Canvas image-parity fixes: content-addressed byte serving, scene-persist
asset promotion, and the engine-builtin platform kit route.

Root cause these pin (found live, run_b515): the product had two disjoint
asset registries — the SCENE's assets map (engine truth; what exports resolve
from) and the API's SQLite `assets` table (what `/assets/{id}/bytes` resolves
from). Deepagent-generated imagery lived only in the scene + byte store, so
every export carried the image while the canvas 404'd and drew a placeholder.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from clue_design.storage import SOURCE_KEY_ASSET

from conftest import make_blob_store, make_client

from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"
GENERATED_RASTER_ASSET_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/assets/generated_raster_asset.json"
)

# Smallest valid PNG (1x1, from the PNG spec) — sniffable magic bytes.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


def store_bytes(client: TestClient, data: bytes) -> str:
    """Give bytes DURABLE custody in this test's workspace; returns the digest.

    D4: the app-local content-addressed tree is gone — the durable home is platform storage, and
    the app resolves every byte read from there. Registering through the same seam the
    production producers use is what makes these fixtures exercise the real path.
    """
    make_blob_store(client.app).register(
        data, media_type="application/octet-stream", source_key=SOURCE_KEY_ASSET
    )
    return hashlib.sha256(data).hexdigest()


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def scene_with_generated_asset(digest: str, asset_id: str = "asset_img_run_test_0") -> dict:
    """A scene carrying a generated raster asset stored locally — the shape
    the deepagent's generate_image tool produces (scene record + store bytes,
    nothing registered anywhere else)."""
    scene = minimal_scene()
    record = json.loads(GENERATED_RASTER_ASSET_PATH.read_text())
    record["id"] = asset_id
    record["media"]["digest"] = {"algorithm": "sha256", "value": digest}
    # Deliberately the LEGACY provider label + ref shape: a scene written before D4 (or by the
    # engine, which still mints this shape) must keep promoting and serving.
    record["media"]["location"] = {
        "provider": "local-store",
        "opaque_ref": f"sha256/{digest[:2]}/{digest}",
        "url": None,
    }
    record["media"]["byte_length"] = len(TINY_PNG)
    scene.setdefault("assets", {})[asset_id] = record
    return scene


def create_document(client: TestClient, scene: Optional[dict] = None) -> dict:
    response = client.post(
        "/documents",
        json={"title": "Canvas parity", "scene": scene or minimal_scene()},
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


# ---------------------------------------------------------------------------
# GET /asset-store/{digest}


def test_asset_store_serves_content_addressed_bytes(client: TestClient) -> None:
    digest = store_bytes(client, TINY_PNG)
    response = client.get(f"/asset-store/{digest}")
    assert response.status_code == 200
    assert response.content == TINY_PNG
    assert response.headers["content-type"].startswith("image/png")
    # Content-addressed = immutable: aggressive caching is safe and declared.
    assert "immutable" in response.headers.get("cache-control", "")


def test_asset_store_rejects_anything_but_lowercase_sha256_hex(client: TestClient) -> None:
    digest = store_bytes(client, TINY_PNG)
    for bad in (
        digest.upper(),          # case-sensitive: the store path is lowercase
        digest[:-1],             # short
        digest[:-1] + "g",       # non-hex
        "%2e%2e%2fsecrets",      # traversal attempt
    ):
        response = client.get(f"/asset-store/{bad}")
        assert response.status_code == 404, bad


def test_asset_store_unknown_digest_is_404(client: TestClient) -> None:
    missing = hashlib.sha256(b"never stored").hexdigest()
    response = client.get(f"/asset-store/{missing}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Scene-persist promotion: scene-borne assets become registry rows


def test_scene_persist_promotes_generated_assets(client: TestClient) -> None:
    digest = store_bytes(client, TINY_PNG)
    document = create_document(client)
    scene = scene_with_generated_asset(digest)
    scene["meta"]["id"] = document["id"]

    replaced = client.put(f"/documents/{document['id']}/scene", json={"scene": scene})
    assert replaced.status_code == 200, replaced.text

    # The record is now first-class: the registry endpoint serves it...
    record = client.get("/assets/asset_img_run_test_0")
    assert record.status_code == 200, record.text
    assert record.json()["asset"]["source"]["kind"] == "generated"
    # ...including its bytes (the pre-fix 404 that blanked the canvas).
    payload = client.get("/assets/asset_img_run_test_0/bytes")
    assert payload.status_code == 200
    assert payload.content == TINY_PNG


def test_scene_persist_promotion_is_insert_only(client: TestClient) -> None:
    """A registry row accumulates curation (labels, tags, status); a later
    scene write must never clobber it."""
    digest = store_bytes(client, TINY_PNG)
    document = create_document(client)
    scene = scene_with_generated_asset(digest)
    scene["meta"]["id"] = document["id"]
    client.put(f"/documents/{document['id']}/scene", json={"scene": scene})

    original_label = client.get("/assets/asset_img_run_test_0").json()["asset"]["label"]

    mutated = scene_with_generated_asset(digest)
    mutated["meta"]["id"] = document["id"]
    mutated["assets"]["asset_img_run_test_0"]["label"] = "scene tried to rename me"
    replaced = client.put(f"/documents/{document['id']}/scene", json={"scene": mutated})
    assert replaced.status_code == 200, replaced.text

    after = client.get("/assets/asset_img_run_test_0").json()["asset"]["label"]
    assert after == original_label


def test_scene_persist_skips_records_without_local_bytes(client: TestClient) -> None:
    """A location that resolves to no DIGEST is not a servable row; the
    promotion must not fabricate registry entries for it (D4: the gate is the digest, not the
    provider label — an `opaque_asset_store` handle naming someone else's object still
    resolves to nothing)."""
    digest = store_bytes(client, TINY_PNG)
    document = create_document(client)
    scene = scene_with_generated_asset(digest, asset_id="asset_remote_ref")
    scene["meta"]["id"] = document["id"]
    scene["assets"]["asset_remote_ref"]["media"]["location"] = {
        "provider": "opaque_asset_store",
        "opaque_ref": "workspace/acme/generated/hero",
        "url": None,
    }
    replaced = client.put(f"/documents/{document['id']}/scene", json={"scene": scene})
    assert replaced.status_code == 200, replaced.text
    assert client.get("/assets/asset_remote_ref").status_code == 404


# ---------------------------------------------------------------------------
# Engine-builtin platform kit route


def test_platform_default_brand_kit_is_served(client: TestClient) -> None:
    """The editor's canvas token resolution fetches this id for kit-less
    documents to mirror server-side resolution; a 404 dropped the canvas to
    its string heuristic and token colors diverged from exports."""
    response = client.get("/brand-kits/brand_kit_platform_default")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["builtin"] is True
    colors = (payload["brand_kit_json"].get("tokens") or {}).get("colors") or {}
    assert colors, "platform kit must carry resolvable token colors"


def test_operations_path_also_promotes_assets(client: TestClient) -> None:
    """The apply-operations path (update_document_state) persists scenes too;
    an upsert_asset arriving via an operations batch must promote exactly
    like a full scene replace."""
    digest = store_bytes(client, TINY_PNG)
    document = create_document(client)
    scene = scene_with_generated_asset(digest, asset_id="asset_via_ops")
    record = scene["assets"]["asset_via_ops"]

    response = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [{"kind": "upsert_asset", "asset": record}]},
    )
    assert response.status_code == 200, response.text

    stored = client.get("/assets/asset_via_ops")
    assert stored.status_code == 200, stored.text
    payload = client.get("/assets/asset_via_ops/bytes")
    assert payload.status_code == 200
    assert payload.content == TINY_PNG


def test_regenerate_in_place_refreshes_byte_identity_not_curation(
    client: TestClient,
) -> None:
    """Same asset id, new pixels (regenerate-in-place): the registry must
    track the CURRENT bytes — a frozen row would recreate the scene-vs-
    registry divergence in the opposite direction — while curated columns
    survive untouched."""
    digest_v1 = store_bytes(client, TINY_PNG)
    document = create_document(client)
    scene = scene_with_generated_asset(digest_v1)
    scene["meta"]["id"] = document["id"]
    client.put(f"/documents/{document['id']}/scene", json={"scene": scene})
    original_label = client.get("/assets/asset_img_run_test_0").json()["asset"]["label"]

    new_bytes = TINY_PNG + b"\x00"  # different content, new digest
    digest_v2 = store_bytes(client, new_bytes)
    regenerated = scene_with_generated_asset(digest_v2)
    regenerated["meta"]["id"] = document["id"]
    regenerated["assets"]["asset_img_run_test_0"]["label"] = "scene rename attempt"
    replaced = client.put(
        f"/documents/{document['id']}/scene", json={"scene": regenerated}
    )
    assert replaced.status_code == 200, replaced.text

    stored = client.get("/assets/asset_img_run_test_0").json()["asset"]
    assert stored["media"]["digest"]["value"] == digest_v2, "byte identity refreshed"
    assert stored["label"] == original_label, "curation preserved"
    payload = client.get("/assets/asset_img_run_test_0/bytes")
    assert payload.status_code == 200
    assert payload.content == new_bytes


def test_promotion_never_fabricates_rows_for_mismatched_keys(client: TestClient) -> None:
    """scene.assets keys by the record's own id (engine invariant); a
    malformed entry keyed under a different name must not become a row."""
    digest = store_bytes(client, TINY_PNG)
    document = create_document(client)
    scene = scene_with_generated_asset(digest, asset_id="asset_real_id")
    scene["meta"]["id"] = document["id"]
    # Malform: key differs from the record's id.
    scene["assets"]["asset_wrong_key"] = scene["assets"].pop("asset_real_id")
    replaced = client.put(f"/documents/{document['id']}/scene", json={"scene": scene})
    # Whether or not scene validation rejects the malformed map, no registry
    # row may exist under either name unless the scene actually persisted a
    # coherent record.
    if replaced.status_code == 200:
        assert client.get("/assets/asset_wrong_key").status_code == 404


# --- <img src> serving: explicit digests at the DTO boundary ---------------------------------
# The editor renders asset previews as plain <img src> — a context that cannot send
# X-Workspace-Id — so it builds public content-addressed URLs (/asset-store/{digest}). The
# digest for FULL bytes is already an explicit DTO field (media.digest); the THUMBNAIL's was
# only derivable by parsing media.thumbnail.location's opaque_ref, and ref parsing is
# server-owned policy (clue_design.storage.location_digest). These pin the contract: the API
# stamps media.thumbnail.digest at the response boundary, and the digest serves headerless.


def _record_with_thumbnail(asset_id: str, full_digest: str, thumb_digest: str) -> dict:
    return {
        "id": asset_id,
        "label": "thumb fixture",
        "kind": "raster_image",
        "status": "ready",
        "tags": [],
        "media": {
            "mime_type": "image/png",
            "byte_length": len(TINY_PNG),
            "digest": {"algorithm": "sha256", "value": full_digest},
            "location": {
                "provider": "local-store",
                "opaque_ref": f"sha256/{full_digest[:2]}/{full_digest}",
                "url": None,
            },
            "thumbnail": {
                "location": {
                    "provider": "local-store",
                    "opaque_ref": f"sha256/{thumb_digest[:2]}/{thumb_digest}",
                    "url": None,
                },
                "mime_type": "image/png",
            },
        },
    }


def test_asset_dtos_carry_the_thumbnail_digest(client: TestClient) -> None:
    from lumen_api.design_store import HybridRepository

    full_digest = store_bytes(client, TINY_PNG)
    thumb_bytes = TINY_PNG + b"#thumb"
    thumb_digest = store_bytes(client, thumb_bytes)
    HybridRepository().create_asset_record(
        _record_with_thumbnail("asset_thumb_dto_1", full_digest, thumb_digest)
    )

    detail = client.get("/assets/asset_thumb_dto_1")
    assert detail.status_code == 200, detail.text
    media = detail.json()["asset"]["media"]
    assert media["thumbnail"]["digest"] == {"algorithm": "sha256", "value": thumb_digest}
    assert media["digest"]["value"] == full_digest

    listed = client.get("/assets").json()["assets"]
    row = next(a for a in listed if a["id"] == "asset_thumb_dto_1")
    assert row["media"]["thumbnail"]["digest"]["value"] == thumb_digest


def test_thumbnail_digest_serves_headerless_like_an_img_tag(client: TestClient) -> None:
    from lumen_api.design_store import HybridRepository

    full_digest = store_bytes(client, TINY_PNG)
    thumb_bytes = TINY_PNG + b"#thumb-serve"
    thumb_digest = store_bytes(client, thumb_bytes)
    HybridRepository().create_asset_record(
        _record_with_thumbnail("asset_thumb_serve_1", full_digest, thumb_digest)
    )

    served_digest = client.get("/assets/asset_thumb_serve_1").json()["asset"]["media"][
        "thumbnail"
    ]["digest"]["value"]
    headerless = TestClient(client.app)  # no X-Workspace-Id — the browser's <img> reality
    response = headerless.get(f"/asset-store/{served_digest}")
    assert response.status_code == 200
    assert response.content == thumb_bytes


def test_thumbnailless_and_foreign_provider_records_stay_unstamped(client: TestClient) -> None:
    from lumen_api.design_store import HybridRepository

    full_digest = store_bytes(client, TINY_PNG)
    bare = _record_with_thumbnail("asset_thumb_none_1", full_digest, full_digest)
    del bare["media"]["thumbnail"]
    foreign = _record_with_thumbnail("asset_thumb_foreign_1", full_digest, full_digest)
    foreign["media"]["thumbnail"]["location"]["provider"] = "https"
    foreign["media"]["thumbnail"]["location"]["opaque_ref"] = "https://cdn.example/x.png"
    repo = HybridRepository()
    repo.create_asset_record(bare)
    repo.create_asset_record(foreign)

    none_media = client.get("/assets/asset_thumb_none_1").json()["asset"]["media"]
    assert "thumbnail" not in none_media or none_media["thumbnail"] is None
    foreign_media = client.get("/assets/asset_thumb_foreign_1").json()["asset"]["media"]
    assert foreign_media["thumbnail"].get("digest") is None
