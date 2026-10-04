"""`CoreClient.ingest_asset` decodes AVIF to PNG before the helper sniffs it (2026-10-04).

A CDN that negotiates the format from ``Accept`` (Cloudflare ``cdn-cgi/image/f=auto``) served
Atrium Hospitality's header logo as AVIF; the helper cannot sniff AVIF, stored it as
``application/octet-stream``, and every placement failed ``op.asset_incompatible``.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, features

from lumen_api.core import CoreClient, CoreError
from lumen_api.image_containers import (
    INGEST_IMAGE_DECODE_FAILED,
    decode_avif,
    is_avif,
    normalize_ingest_image,
)

pytestmark = pytest.mark.skipif(not features.check("avif"), reason="Pillow built without AVIF")

TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def avif_bytes(mode: str = "RGBA") -> bytes:
    image = Image.new(mode, (24, 12), (20, 90, 200, 128) if mode == "RGBA" else (20, 90, 200))
    out = BytesIO()
    image.save(out, format="AVIF", quality=90)
    return out.getvalue()


class RecordingClient(CoreClient):
    """A CoreClient whose helper call is captured instead of executed."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict] = []

    def _run(self, request, raise_on_error=True):  # type: ignore[override]
        self.requests.append(request)
        return {"ok": True, "asset": {"record": {"id": request["asset_id"]}}}


# --- sniffing and decoding (pure) -------------------------------------------------------------


def test_is_avif_recognizes_the_ftyp_brand_and_nothing_else() -> None:
    assert is_avif(avif_bytes())
    assert not is_avif(TINY_PNG)
    assert not is_avif(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")  # an MP4
    assert not is_avif(b"")


def test_decode_avif_keeps_alpha_and_size() -> None:
    decoded = decode_avif(avif_bytes("RGBA"))
    assert decoded is not None
    assert decoded.mime_type == "image/png"
    with Image.open(BytesIO(decoded.data)) as png:
        assert png.format == "PNG"
        assert png.size == (24, 12)
        assert png.mode == "RGBA"


def test_decode_avif_is_deterministic() -> None:
    data = avif_bytes()
    first, second = decode_avif(data), decode_avif(data)
    assert first is not None and second is not None
    assert first.data == second.data


# --- normalize_ingest_image (pure) ------------------------------------------------------------


def test_normalize_decodes_avif_and_rewrites_mime_filename_provenance() -> None:
    data = avif_bytes()
    normalized = normalize_ingest_image(
        bytes_base64=b64(data),
        declared_mime_type="image/avif",
        filename="logo.avif",
        provenance={"created_by": "logo_ladder", "notes": ["kept"]},
    )
    assert normalized.refusal is None
    assert normalized.decoded is not None
    assert base64.b64decode(normalized.bytes_base64)[:8] == TINY_PNG[:8]
    assert normalized.declared_mime_type == "image/png"
    assert normalized.filename == "logo.png"
    assert normalized.provenance["created_by"] == "logo_ladder"
    assert normalized.provenance["notes"][0] == "kept"
    assert hashlib.sha256(data).hexdigest() in normalized.provenance["notes"][1]


def test_normalize_leaves_other_payloads_byte_identical() -> None:
    png_b64 = b64(TINY_PNG)
    normalized = normalize_ingest_image(
        bytes_base64=png_b64, declared_mime_type="image/png", filename="dot.png", provenance=None
    )
    assert normalized.bytes_base64 is png_b64
    assert normalized.decoded is None and normalized.refusal is None


def test_normalize_refuses_an_undecodable_avif() -> None:
    broken = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 64
    normalized = normalize_ingest_image(
        bytes_base64=b64(broken), declared_mime_type=None, filename="x.avif", provenance=None
    )
    assert normalized.decoded is None
    assert normalized.refusal is not None
    assert normalized.refusal["code"] == INGEST_IMAGE_DECODE_FAILED


# --- CoreClient.ingest_asset (captured helper call) -------------------------------------------


def test_ingest_asset_hands_the_helper_png_bytes_for_an_avif_payload() -> None:
    client = RecordingClient()
    response = client.ingest_asset(
        store_root="/tmp/unused",
        bytes_base64=b64(avif_bytes()),
        asset_id="asset_test_avif",
        label="Atrium Hospitality logo (light_lockup)",
        declared_mime_type="image/avif",
        tags=["target-account", "logo-ladder"],
        provenance={"created_by": "logo_ladder"},
    )
    assert response["ok"] is True
    request = client.requests[0]
    assert base64.b64decode(request["bytes_base64"])[:8] == TINY_PNG[:8]
    assert request["declared_mime_type"] == "image/png"
    assert request["tags"] == ["target-account", "logo-ladder"]
    assert any("avif -> png" in note for note in request["provenance"]["notes"])


def test_ingest_asset_refuses_an_undecodable_avif_without_calling_the_helper() -> None:
    client = RecordingClient()
    broken = b64(b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 64)
    refused = client.ingest_asset("/tmp/unused", broken, "a", "a", raise_on_error=False)
    assert refused["ok"] is False
    assert refused["error"]["code"] == INGEST_IMAGE_DECODE_FAILED
    assert client.requests == []
    with pytest.raises(CoreError) as raised:
        client.ingest_asset("/tmp/unused", broken, "a", "a")
    assert raised.value.code == INGEST_IMAGE_DECODE_FAILED


# --- the real helper --------------------------------------------------------------------------


def test_real_helper_stores_the_decoded_png_as_a_raster_image(tmp_path: Path) -> None:
    """End to end through the release helper: the record is a PNG raster, not `other`."""
    data = avif_bytes()
    response = CoreClient().ingest_asset(
        store_root=str(tmp_path),
        bytes_base64=b64(data),
        asset_id="asset_test_avif_logo",
        label="avif logo",
        declared_mime_type="image/avif",
        provenance={"created_by": "test", "notes": []},
        raise_on_error=False,
    )
    assert response.get("ok"), response
    record = response["asset"]["record"]
    expected = decode_avif(data)
    assert expected is not None
    assert record["kind"] == "raster_image"
    assert record["media"]["mime_type"] == "image/png"
    assert record["media"]["digest"]["value"] == hashlib.sha256(expected.data).hexdigest()
