"""`CoreClient.ingest_asset` is the ONE chokepoint every font byte passes through — the harvest
evidence builder, the upload analyzer, the PDF capture, `POST /assets`, and the font-library
provisioning all call it. Option A (2026-09-02) decodes WOFF/WOFF2 there, so no caller and
no consumer has to know the wrapper ever existed.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from lumen_api.core import CoreClient, CoreError
from lumen_api.font_containers import (
    INGEST_FONT_DECODE_FAILED,
    decode_web_font,
    normalize_ingest_font,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture(scope="module")
def inter_ttf() -> bytes:
    return INTER.read_bytes()


@pytest.fixture(scope="module")
def inter_woff2(inter_ttf: bytes) -> bytes:
    font = TTFont(BytesIO(inter_ttf), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = "woff2"
    out = BytesIO()
    font.save(out)
    return out.getvalue()


class RecordingClient(CoreClient):
    """A CoreClient whose helper call is captured instead of executed."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict] = []

    def _run(self, request, raise_on_error=True):  # type: ignore[override]
        self.requests.append(request)
        return {"ok": True, "asset": {"record": {"id": request["asset_id"]}}}


# --- normalize_ingest_font (pure) -----------------------------------------------------------


def test_normalize_decodes_a_woff2_payload_and_rewrites_mime_filename_provenance(
    inter_woff2: bytes,
) -> None:
    normalized = normalize_ingest_font(
        bytes_base64=b64(inter_woff2),
        declared_mime_type="font/woff2",
        filename="inter.woff2",
        provenance={"created_by": "test", "notes": ["kept"]},
    )
    assert normalized.refusal is None
    assert normalized.decoded is not None
    decoded = base64.b64decode(normalized.bytes_base64)
    assert decoded[:4] == b"\x00\x01\x00\x00"
    expected = decode_web_font(inter_woff2)
    assert expected is not None and decoded == expected.data
    assert normalized.declared_mime_type == "font/ttf"
    assert normalized.filename == "inter.ttf"
    assert normalized.provenance is not None
    assert normalized.provenance["created_by"] == "test"
    assert normalized.provenance["notes"][0] == "kept"
    assert normalized.provenance["notes"][1].startswith(
        "font container decoded at ingestion: woff2 -> ttf"
    )


def test_normalize_leaves_sfnt_and_non_font_payloads_byte_identical(
    inter_ttf: bytes,
) -> None:
    for payload, mime, name in (
        (inter_ttf, "font/ttf", "inter.ttf"),
        (TINY_PNG, "image/png", "dot.png"),
    ):
        encoded = b64(payload)
        normalized = normalize_ingest_font(
            bytes_base64=encoded, declared_mime_type=mime, filename=name, provenance=None
        )
        assert normalized.bytes_base64 is encoded
        assert normalized.declared_mime_type == mime
        assert normalized.filename == name
        assert normalized.provenance is None
        assert normalized.decoded is None
        assert normalized.refusal is None


def test_normalize_creates_provenance_when_the_caller_passed_none(inter_woff2: bytes) -> None:
    normalized = normalize_ingest_font(
        bytes_base64=b64(inter_woff2), declared_mime_type=None, filename=None, provenance=None
    )
    assert normalized.provenance == {"notes": [normalized.provenance["notes"][0]]}
    assert normalized.filename is None
    assert normalized.declared_mime_type == "font/ttf"


def test_normalize_refuses_an_undecodable_web_font() -> None:
    normalized = normalize_ingest_font(
        bytes_base64=b64(b"wOF2" + b"\x00" * 96),
        declared_mime_type="font/woff2",
        filename="broken.woff2",
        provenance=None,
    )
    assert normalized.decoded is None
    assert normalized.refusal is not None
    assert normalized.refusal["code"] == INGEST_FONT_DECODE_FAILED
    assert "broken.woff2" in normalized.refusal["message"]


def test_normalize_tolerates_a_payload_the_helper_would_refuse_anyway() -> None:
    # Not valid base64: the helper reports that; the normalizer must not raise first.
    normalized = normalize_ingest_font(
        bytes_base64="@@@not-base64@@@", declared_mime_type=None, filename=None, provenance=None
    )
    assert normalized.bytes_base64 == "@@@not-base64@@@"
    assert normalized.refusal is None


# --- CoreClient.ingest_asset (captured helper call) ------------------------------------------


def test_ingest_asset_hands_the_helper_sfnt_bytes_for_a_woff2_payload(
    inter_woff2: bytes,
) -> None:
    client = RecordingClient()
    response = client.ingest_asset(
        store_root="/tmp/unused",
        bytes_base64=b64(inter_woff2),
        asset_id="asset_test_woff2",
        label="Inter web",
        declared_mime_type="font/woff2",
        filename="inter.woff2",
        kind="font",
        tags=["font"],
        provenance={"created_by": "lumen_ingestion", "notes": []},
    )
    assert response["ok"] is True
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request["action"] == "ingest_asset"
    assert base64.b64decode(request["bytes_base64"])[:4] == b"\x00\x01\x00\x00"
    assert request["declared_mime_type"] == "font/ttf"
    assert request["filename"] == "inter.ttf"
    assert request["kind"] == "font"
    assert request["tags"] == ["font"]
    assert request["provenance"]["created_by"] == "lumen_ingestion"
    assert any("decoded at ingestion" in note for note in request["provenance"]["notes"])


def test_ingest_asset_passes_sfnt_and_images_through_untouched(inter_ttf: bytes) -> None:
    client = RecordingClient()
    ttf_b64 = b64(inter_ttf)
    png_b64 = b64(TINY_PNG)
    client.ingest_asset("/tmp/unused", ttf_b64, "asset_ttf", "ttf", "font/ttf", "inter.ttf")
    client.ingest_asset("/tmp/unused", png_b64, "asset_png", "png", "image/png", "dot.png")
    assert client.requests[0]["bytes_base64"] is ttf_b64
    assert client.requests[0]["declared_mime_type"] == "font/ttf"
    assert client.requests[0]["provenance"] is None
    assert client.requests[1]["bytes_base64"] is png_b64
    assert client.requests[1]["declared_mime_type"] == "image/png"


def test_ingest_asset_refuses_an_undecodable_web_font_without_calling_the_helper() -> None:
    client = RecordingClient()
    refused = client.ingest_asset(
        "/tmp/unused",
        b64(b"wOF2" + b"\x00" * 96),
        "asset_broken",
        "broken",
        "font/woff2",
        "broken.woff2",
        raise_on_error=False,
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] == INGEST_FONT_DECODE_FAILED
    assert refused["diagnostics"] == []
    assert client.requests == []
    with pytest.raises(CoreError) as raised:
        client.ingest_asset(
            "/tmp/unused",
            b64(b"wOF2" + b"\x00" * 96),
            "asset_broken",
            "broken",
            "font/woff2",
            "broken.woff2",
        )
    assert raised.value.code == INGEST_FONT_DECODE_FAILED
    assert client.requests == []


# --- the real helper --------------------------------------------------------------------------


def test_real_helper_stores_the_decoded_face(tmp_path: Path, inter_woff2: bytes) -> None:
    """End to end through the release helper: the record and the cached bytes are sfnt."""
    core = CoreClient()
    response = core.ingest_asset(
        store_root=str(tmp_path),
        bytes_base64=b64(inter_woff2),
        asset_id="asset_test_decoded_face",
        label="Inter web (decoded)",
        declared_mime_type="font/woff2",
        filename="inter.woff2",
        kind="font",
        provenance={"created_by": "test", "notes": []},
        raise_on_error=False,
    )
    assert response.get("ok"), response
    record = response["asset"]["record"]
    expected = decode_web_font(inter_woff2)
    assert expected is not None
    digest = hashlib.sha256(expected.data).hexdigest()
    assert record["media"]["mime_type"] == "font/ttf"
    assert record["media"]["digest"]["value"] == digest
    assert record["media"]["filename"] == "inter.ttf"
    assert record["media"]["byte_length"] == len(expected.data)
    assert any("decoded at ingestion" in note for note in record["provenance"]["notes"])
    cached = tmp_path / "sha256" / digest[:2] / digest
    assert cached.read_bytes() == expected.data
