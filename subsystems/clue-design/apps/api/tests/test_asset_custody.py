"""Asset custody across the Python/Rust seam — Part II D4 Round B (ruling R-D4-1).

The one property every test here defends: **platform storage is the durable home of every
design byte, and the engine's per-workspace tree is a cache nothing depends on.** So each test
either destroys the cache and demands the product still works, or produces bytes that only
exist in the cache and demands they be given custody before anything durable references them.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clue_design.storage import SOURCE_KEY_ASSET
from clue_storage import StorageError

from conftest import make_blob_store, make_client

from lumen_api.asset_custody import cache_blob_path, write_cache_blob
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"
GENERATED_RASTER_ASSET_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/assets/generated_raster_asset.json"
)
LOGO_PNG_PATH = REPO_ROOT / "crates/lumen-export/fixtures/assets/acme-logo-8x8-red.png"

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


def workspace_cache_dir(client: TestClient) -> Path:
    return Path(client.app.state.engine_cache_root) / os.environ["LUMEN_DEV_WORKSPACE_ID"]


def upload_logo(client: TestClient) -> dict:
    response = client.post(
        "/assets",
        files={"file": ("acme-logo.png", LOGO_PNG_PATH.read_bytes(), "image/png")},
        data={"label": "Custody logo", "kind": "logo"},
    )
    assert response.status_code == 200, response.text
    return response.json()["asset"]


def scene_with_asset(document_id: str, record: dict) -> dict:
    scene = json.loads(MINIMAL_SCENE_PATH.read_text())
    scene["meta"]["id"] = document_id
    scene.setdefault("assets", {})[record["id"]] = record
    return scene


def create_document(client: TestClient) -> dict:
    response = client.post(
        "/documents",
        json={"title": "Custody", "scene": json.loads(MINIMAL_SCENE_PATH.read_text())},
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


# ---------------------------------------------------------------------------
# (1) Wiping the cache loses nothing


def test_upload_gives_durable_custody_and_repoints_the_record(client: TestClient) -> None:
    """R-D4-4: the engine wrote into its cache; what PERSISTS points at platform storage."""
    record = upload_logo(client)
    digest = record["media"]["digest"]["value"]
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]

    assert record["media"]["location"] == {
        "provider": "clue-storage",
        "opaque_ref": f"{workspace_id}/design/{digest}",
        "url": None,
    }
    assert make_blob_store(client.app).read(digest) == LOGO_PNG_PATH.read_bytes()
    # The thumbnail is a second byte object and gets the same treatment.
    thumbnail = record["media"]["thumbnail"]
    assert thumbnail["location"]["provider"] == "clue-storage"


def test_pure_python_reads_survive_a_wiped_cache(client: TestClient) -> None:
    """/assets/{id}/bytes, /thumbnail and /asset-store/{digest} never touch the cache."""
    record = upload_logo(client)
    digest = record["media"]["digest"]["value"]
    shutil.rmtree(workspace_cache_dir(client))

    served = client.get(f"/assets/{record['id']}/bytes")
    assert served.status_code == 200, served.text
    assert served.content == LOGO_PNG_PATH.read_bytes()

    thumbnail = client.get(f"/assets/{record['id']}/thumbnail")
    assert thumbnail.status_code == 200, thumbnail.text

    public = client.get(f"/asset-store/{digest}")
    assert public.status_code == 200
    assert public.content == LOGO_PNG_PATH.read_bytes()
    assert public.headers["content-type"].startswith("image/png")
    assert public.headers["Access-Control-Allow-Origin"] == "*"


def test_an_engine_read_rehydrates_the_cache_from_durable_storage(
    client: TestClient,
) -> None:
    """THE cache-wipe rehydration case (R-D4-1).

    Upload (durable custody), destroy the whole workspace cache, then drive an ENGINE read —
    the export path — over a scene naming that asset. The read-through must put the bytes back
    before the engine runs, so the request succeeds and the cache file exists again.
    """
    record = upload_logo(client)
    digest = record["media"]["digest"]["value"]
    cache_dir = workspace_cache_dir(client)
    assert cache_blob_path(cache_dir, digest).is_file(), "engine wrote its cache copy"

    shutil.rmtree(cache_dir)
    assert not cache_blob_path(cache_dir, digest).exists()

    document = create_document(client)
    response = client.post(
        "/export-preview",
        json={"scene": scene_with_asset(document["id"], record), "format": "svg"},
    )
    assert response.status_code == 200, response.text
    assert cache_blob_path(cache_dir, digest).is_file(), "materialized before the engine ran"
    assert cache_blob_path(cache_dir, digest).read_bytes() == LOGO_PNG_PATH.read_bytes()


# ---------------------------------------------------------------------------
# (2) The scene-persist backstop


def cache_only_asset(client: TestClient, asset_id: str, data: bytes) -> dict:
    """An asset record whose bytes exist ONLY in the engine cache — the shape an agent turn
    leaves behind when it generates imagery mid-run (the engine wrote them; nothing registered
    them). Deliberately carries the LEGACY `local-store` ref the engine itself mints."""
    digest = hashlib.sha256(data).hexdigest()
    write_cache_blob(workspace_cache_dir(client), digest, data)
    record = json.loads(GENERATED_RASTER_ASSET_PATH.read_text())
    record["id"] = asset_id
    record["media"]["digest"] = {"algorithm": "sha256", "value": digest}
    record["media"]["location"] = {
        "provider": "local-store",
        "opaque_ref": f"sha256/{digest[:2]}/{digest}",
        "url": None,
    }
    record["media"]["byte_length"] = len(data)
    return record


def test_scene_accept_gives_custody_to_cache_only_bytes(client: TestClient) -> None:
    """The accept seam is where mid-turn generated bytes become the workspace's."""
    document = create_document(client)
    record = cache_only_asset(client, "asset_mid_turn", TINY_PNG)
    digest = record["media"]["digest"]["value"]
    blobs = make_blob_store(client.app)
    assert not blobs.exists(digest), "precondition: cache-only, no durable custody"

    replaced = client.put(
        f"/documents/{document['id']}/scene",
        json={"scene": scene_with_asset(document["id"], record)},
    )
    assert replaced.status_code == 200, replaced.text

    assert blobs.exists(digest), "the accept seam registered the cache-only bytes"
    # And the promoted registry row can serve them even once the cache is gone.
    shutil.rmtree(workspace_cache_dir(client))
    served = client.get("/assets/asset_mid_turn/bytes")
    assert served.status_code == 200, served.text
    assert served.content == TINY_PNG


def test_the_backstop_leaves_already_durable_bytes_alone(client: TestClient) -> None:
    """Skip-if-durable: re-accepting a scene must not churn custody (and must not fail)."""
    document = create_document(client)
    record = cache_only_asset(client, "asset_mid_turn", TINY_PNG)
    scene = scene_with_asset(document["id"], record)
    assert client.put(f"/documents/{document['id']}/scene", json={"scene": scene}).status_code == 200
    assert client.put(f"/documents/{document['id']}/scene", json={"scene": scene}).status_code == 200
    assert make_blob_store(client.app).read(record["media"]["digest"]["value"]) == TINY_PNG


def test_the_backstop_heals_custody_whose_bytes_went_missing(client: TestClient) -> None:
    """Custody is a claim about BYTES, so the skip probe has to be about bytes.

    The genad2 walk (2026-08-23) found the row and the blob apart: the persisting process and
    the serving one resolved the relative default blob root against different working
    directories, so the ``artifact`` row (shared database) said custody and the design API's
    backend could not produce a thing. That divergence is recoverable — the engine cache still
    held the bytes — but under the old row-only probe (``exists``, "no blob I/O") it was
    PERMANENT, because every later accept skipped the digest on the strength of the row.

    This drives the NON-leg seam (``PUT /scene``) on purpose: the backstop is one shared
    function, so the leg persist and the MVP editor's accept heal identically, and pinning it
    here is what keeps the editor path from regressing when only the leg tests are read.
    """
    from clue_design.storage import design_storage_key

    document = create_document(client)
    record = cache_only_asset(client, "asset_mid_turn", TINY_PNG)
    scene = scene_with_asset(document["id"], record)
    digest = record["media"]["digest"]["value"]
    assert client.put(f"/documents/{document['id']}/scene", json={"scene": scene}).status_code == 200

    key = design_storage_key(os.environ["LUMEN_DEV_WORKSPACE_ID"], digest)
    Path(client.app.state.storage._root).joinpath(*key.split("/")).unlink()
    assert make_blob_store(client.app).exists(digest), "the row still claims custody"
    # Workspace-scoped byte route rather than /asset-store/{digest}: the public route resolves
    # a digest across EVERY tenant's rows, and TINY_PNG's hash is held by half this suite.
    assert client.get("/assets/asset_mid_turn/bytes").status_code == 404

    assert client.put(f"/documents/{document['id']}/scene", json={"scene": scene}).status_code == 200

    served = client.get("/assets/asset_mid_turn/bytes")
    assert served.status_code == 200, served.text
    assert served.content == TINY_PNG


class FlakyBackend:
    """A storage backend one digest can be made to fail on, the way a sick backend fails.

    Not "the blob is missing" (that is `ArtifactNotFound` and a normal answer) — this is the
    backend itself refusing: unreachable, misconfigured, credentials expired. Switchable at
    runtime because the interesting sequence is *healthy, then sick*, and `create_app` fixes the
    backend for the life of the app.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.fail_on: str | None = None

    def _guard(self, key: str) -> None:
        if self.fail_on is not None and self.fail_on in key:
            raise StorageError(f"backend unreachable for {key!r}")

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self._guard(key)
        await self._inner.put(key, data, media_type=media_type)

    async def get(self, key: str) -> bytes:
        self._guard(key)
        return await self._inner.get(key)

    async def exists(self, key: str) -> bool:
        self._guard(key)
        return await self._inner.exists(key)

    async def delete(self, key: str) -> None:
        self._guard(key)
        await self._inner.delete(key)

    def list_blobs(self):
        return self._inner.list_blobs()

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        self._guard(key)
        return await self._inner.presign(key, expires_in=expires_in)


@pytest.fixture()
def flaky_client(tmp_path: Path, design_storage) -> TestClient:
    """A client whose backend can be made sick mid-test (`client.app.state.storage.fail_on`)."""
    app = create_app(tmp_path / "engine-cache", storage=FlakyBackend(design_storage))
    return make_client(app)


def test_a_failed_custody_REPAIR_does_not_destroy_the_write(flaky_client: TestClient) -> None:
    """A backstop that cannot repair must leave the persist alone.

    Probing for bytes means the backstop now talks to the backend on scenes it used to skip
    without a single call — so a backend outage must not turn an accept that used to succeed
    into a 500. A repair it cannot perform is logged and skipped: the asset stays exactly as
    broken as it already was, and the next persist tries again.
    """
    document = create_document(flaky_client)
    record = cache_only_asset(flaky_client, "asset_mid_turn", TINY_PNG)
    scene = scene_with_asset(document["id"], record)
    digest = record["media"]["digest"]["value"]
    assert client_put_scene(flaky_client, document, scene) == 200

    from clue_design.storage import design_storage_key

    key = design_storage_key(os.environ["LUMEN_DEV_WORKSPACE_ID"], digest)
    Path(flaky_client.app.state.storage._inner._root).joinpath(*key.split("/")).unlink()
    flaky_client.app.state.storage.fail_on = digest

    assert client_put_scene(flaky_client, document, scene) == 200, "the write survived"
    assert flaky_client.get("/assets/asset_mid_turn/bytes").status_code == 404, "still broken"


def test_a_failed_FIRST_registration_still_refuses_the_write(flaky_client: TestClient) -> None:
    """The asymmetry's other half, unchanged from before the backstop probed bytes.

    No row, no bytes, and a backend that will not take them: persisting the scene would commit a
    document citing imagery nothing durable holds. That has always propagated, and it stays loud
    — it is the fabrication this backstop exists to prevent, not a repair it can defer.
    """
    document = create_document(flaky_client)
    record = cache_only_asset(flaky_client, "asset_mid_turn", TINY_PNG)
    flaky_client.app.state.storage.fail_on = record["media"]["digest"]["value"]

    with pytest.raises(StorageError):
        client_put_scene(flaky_client, document, scene_with_asset(document["id"], record))


def client_put_scene(client: TestClient, document: dict, scene: dict) -> int:
    return client.put(f"/documents/{document['id']}/scene", json={"scene": scene}).status_code


def test_the_backstop_cannot_invent_custody_for_bytes_it_does_not_have(
    client: TestClient,
) -> None:
    """A scene naming a digest that is in NEITHER place is not an error — the record is
    promoted (it is a legitimate registry row) and the byte routes 404 honestly."""
    document = create_document(client)
    record = cache_only_asset(client, "asset_phantom", TINY_PNG)
    digest = record["media"]["digest"]["value"]
    cache_blob_path(workspace_cache_dir(client), digest).unlink()

    replaced = client.put(
        f"/documents/{document['id']}/scene",
        json={"scene": scene_with_asset(document["id"], record)},
    )
    assert replaced.status_code == 200, replaced.text
    assert not make_blob_store(client.app).exists(digest)
    assert client.get("/assets/asset_phantom/bytes").status_code == 404


# ---------------------------------------------------------------------------
# (3) Staged-ingest cleanup vs promotion (R-D4-5)


def test_staged_uploads_survive_cleanup_once_promoted(client: TestClient) -> None:
    """Staging and promotion are content-addressed, so they share ONE key.

    That is exactly why the cleanup cannot be unconditional: deleting the staged blob of a file
    that made it into the library would delete the live asset's bytes.
    """
    from lumen_ingestion.pipeline import _discard_staged

    blobs = make_blob_store(client.app)
    record = upload_logo(client)  # a live asset over these bytes
    digest = record["media"]["digest"]["value"]
    # The same bytes staged for an ingestion job land on the identical key.
    blobs.register(
        LOGO_PNG_PATH.read_bytes(),
        media_type="image/png",
        source_key="design_ingest_staging",
    )

    _discard_staged(HybridRepository(), blobs, [digest])

    assert blobs.exists(digest), "a promoted upload's bytes must survive job cleanup"
    assert client.get(f"/assets/{record['id']}/bytes").status_code == 200


def test_staged_uploads_are_discarded_when_nothing_kept_them(client: TestClient) -> None:
    from lumen_ingestion.pipeline import _discard_staged

    blobs = make_blob_store(client.app)
    digest = hashlib.sha256(TINY_PNG).hexdigest()
    blobs.register(TINY_PNG, media_type="image/png", source_key="design_ingest_staging")
    assert blobs.exists(digest)

    _discard_staged(HybridRepository(), blobs, [digest])

    assert not blobs.exists(digest)


# ---------------------------------------------------------------------------
# (4) The hard-delete GC destroys both copies


def test_hard_delete_destroys_durable_bytes_and_the_cache_mirror(
    client: TestClient,
) -> None:
    record = upload_logo(client)
    digest = record["media"]["digest"]["value"]
    cache_dir = workspace_cache_dir(client)
    assert cache_blob_path(cache_dir, digest).is_file()

    deleted = client.delete(f"/assets/{record['id']}")
    assert deleted.status_code == 200, deleted.text
    assert digest in deleted.json()["removed_digests"]

    assert not make_blob_store(client.app).exists(digest)
    assert not cache_blob_path(cache_dir, digest).exists()
    assert client.get(f"/asset-store/{digest}").status_code == 404


# ---------------------------------------------------------------------------
# (5) The public route's cross-tenant resolution (R-D4-7)


def test_the_public_route_serves_another_tenants_bytes_by_digest(
    client: TestClient, tmp_path: Path
) -> None:
    """Deliberately workspace-UNSCOPED. A published page and an origin-"null" preview iframe
    cannot send a workspace header, and before D4 this route served one global tree — so the
    digest resolves across tenants, exactly as it always did. Content addressing is the only
    gate; Part-IV auth owns tightening it."""
    from lumen_api.design_store import DesignBlobStore

    other = DesignBlobStore(client.app.state.storage, "ws_other_tenant_d4")
    payload = b"another tenant's font bytes"
    digest = hashlib.sha256(payload).hexdigest()
    other.register(payload, media_type="font/woff2", source_key=SOURCE_KEY_ASSET)

    response = client.get(f"/asset-store/{digest}")
    assert response.status_code == 200
    assert response.content == payload
    # The artifact ROW's media type wins over sniffing.
    assert response.headers["content-type"].startswith("font/woff2")


def test_the_public_route_falls_back_to_sniffing_for_octet_stream_rows(
    client: TestClient,
) -> None:
    """A producer with nothing better to say stamps application/octet-stream; the route then
    sniffs, which is what it always did."""
    make_blob_store(client.app).register(
        TINY_PNG, media_type="application/octet-stream", source_key=SOURCE_KEY_ASSET
    )
    response = client.get(f"/asset-store/{hashlib.sha256(TINY_PNG).hexdigest()}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
