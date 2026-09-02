"""The one-time backfill that brings already-stored WOFF/WOFF2 font assets onto option A's
invariant (primary bytes are sfnt). Idempotent, dry-run by default, reversible by provenance.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from io import BytesIO
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from fontTools.ttLib import TTFont

from clue_design.storage import SOURCE_KEY_ASSET, design_location, design_storage_key
from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
SCRIPT = REPO_ROOT / "scripts" / "decode_stored_web_fonts.py"


def load_script():
    spec = importlib.util.spec_from_file_location("decode_stored_web_fonts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before exec_module (the documented importlib recipe): the script pairs
    # `from __future__ import annotations` with @dataclass, and CPython 3.12.0's
    # dataclasses._is_type resolves the string annotation via
    # `sys.modules.get(cls.__module__).__dict__` — None, and an AttributeError, for a
    # module that was never registered.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "design-storage"


@pytest.fixture()
def client(tmp_path: Path, storage_root: Path) -> TestClient:
    from clue_storage import FsStorage

    app = create_app(tmp_path / "engine-cache", storage=FsStorage(storage_root))
    return make_client(app)


@pytest.fixture()
def conn():
    dsn = (
        os.environ["CLUE_DATABASE_URL"]
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )
    with psycopg.connect(dsn) as connection:
        yield connection


def inter_as(flavor: str) -> bytes:
    font = TTFont(BytesIO(INTER.read_bytes()), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = flavor
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def seed_web_font(client: TestClient, asset_id: str, data: bytes, mime_type: str) -> str:
    """A font asset exactly as ingestion stored it before option A: WOFF2 bytes, WOFF2 record."""
    key = make_blob_store(client.app).register(
        data, media_type=mime_type, source_key=SOURCE_KEY_ASSET
    )
    digest = hashlib.sha256(data).hexdigest()
    assert key == design_storage_key(os.environ["LUMEN_DEV_WORKSPACE_ID"], digest)
    record = {
        "id": asset_id,
        "label": f"{asset_id}.woff2",
        "kind": "font",
        "status": "ready",
        "source": {"kind": "website", "url": "https://example.test/font.woff2"},
        "media": {
            "mime_type": mime_type,
            "digest": {"algorithm": "sha256", "value": digest},
            "filename": f"{asset_id}.woff2",
            "byte_length": len(data),
            "location": design_location(key),
        },
        "provenance": {"created_by": "lumen_ingestion", "notes": []},
        "tags": ["brand-ingestion", "font"],
    }
    HybridRepository().create_asset_record(record)
    return digest


def test_dry_run_changes_nothing(client: TestClient, conn, storage_root: Path) -> None:
    woff2 = inter_as("woff2")
    digest = seed_web_font(client, "asset_backfill_dry", woff2, "font/woff2")
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    summary = load_script().decode_stored_web_fonts(
        conn, storage_root, workspace_id=workspace_id, apply=False
    )
    assert summary.decoded == 1 and summary.missing == 0 and summary.failed == 0
    stored = HybridRepository().require_asset_record("asset_backfill_dry")["asset"]
    assert stored["media"]["digest"]["value"] == digest
    assert stored["media"]["mime_type"] == "font/woff2"


def test_apply_decodes_relabels_and_is_idempotent(
    client: TestClient, conn, storage_root: Path
) -> None:
    woff2 = inter_as("woff2")
    old_digest = seed_web_font(client, "asset_backfill_apply", woff2, "font/woff2")
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    script = load_script()

    first = script.decode_stored_web_fonts(
        conn, storage_root, workspace_id=workspace_id, apply=True
    )
    assert first.decoded == 1 and first.failed == 0 and first.missing == 0

    repo = HybridRepository()
    stored = repo.require_asset_record("asset_backfill_apply")["asset"]
    media = stored["media"]
    new_digest = media["digest"]["value"]
    assert new_digest != old_digest
    assert media["mime_type"] == "font/ttf"
    assert media["filename"] == "asset_backfill_apply.ttf"
    assert media["location"]["opaque_ref"] == f"{workspace_id}/design/{new_digest}"
    decoded_blob = storage_root / workspace_id / "design" / new_digest
    assert media["byte_length"] == decoded_blob.stat().st_size
    notes = stored["provenance"]["notes"]
    assert any("decoded at ingestion: woff2 -> ttf" in note for note in notes)
    assert any(f"backfill previous digest sha256:{old_digest}" in note for note in notes)

    row = conn.execute(
        "SELECT mime_type, digest_value, byte_length, filename FROM design_asset"
        " WHERE asset_id = %s AND workspace_id = %s",
        ("asset_backfill_apply", workspace_id),
    ).fetchone()
    assert row == ("font/ttf", new_digest, media["byte_length"], "asset_backfill_apply.ttf")

    # Row AND retrievable bytes — the custody question `has_readable_bytes` answers. It lives on
    # DesignBlobStore (what `make_blob_store` hands back), not on HybridRepository.
    assert make_blob_store(client.app).has_readable_bytes(new_digest)
    served = client.get("/assets/asset_backfill_apply/bytes")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("font/ttf")
    assert served.content[:4] == b"\x00\x01\x00\x00"
    assert TTFont(BytesIO(served.content)).getGlyphOrder() == TTFont(INTER).getGlyphOrder()
    # The original blob is untouched (reversible by hand from the provenance note).
    assert (storage_root / workspace_id / "design" / old_digest).read_bytes() == woff2

    second = script.decode_stored_web_fonts(
        conn, storage_root, workspace_id=workspace_id, apply=True
    )
    assert second.decoded == 0 and second.failed == 0


def test_missing_blob_is_reported_not_fatal(client: TestClient, conn, storage_root: Path) -> None:
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    digest = "ab" * 32
    HybridRepository().create_asset_record(
        {
            "id": "asset_backfill_missing",
            "label": "missing.woff2",
            "kind": "font",
            "status": "ready",
            "source": {"kind": "uploaded"},
            "media": {
                "mime_type": "font/woff2",
                "digest": {"algorithm": "sha256", "value": digest},
                "filename": "missing.woff2",
                "byte_length": 10,
                "location": design_location(design_storage_key(workspace_id, digest)),
            },
        }
    )
    summary = load_script().decode_stored_web_fonts(
        conn, storage_root, workspace_id=workspace_id, apply=True
    )
    assert summary.missing == 1 and summary.decoded == 0


def test_corrupt_blob_is_reported_not_fatal(client: TestClient, conn, storage_root: Path) -> None:
    seed_web_font(client, "asset_backfill_corrupt", b"wOF2" + b"\x00" * 96, "font/woff2")
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    summary = load_script().decode_stored_web_fonts(
        conn, storage_root, workspace_id=workspace_id, apply=True
    )
    assert summary.failed == 1 and summary.decoded == 0
    stored = HybridRepository().require_asset_record("asset_backfill_corrupt")["asset"]
    assert stored["media"]["mime_type"] == "font/woff2"  # left exactly as it was
