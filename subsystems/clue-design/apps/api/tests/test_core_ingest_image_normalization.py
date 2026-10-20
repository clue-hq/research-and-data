"""`CoreClient.ingest_asset` converts AVIF and ICO to PNG before the helper sees them.

Every asset byte passes through that one call — fetch_logo, the brand-kit harvest, uploads,
`POST /assets` — so converting there means no caller and no reader has to know AVIF or ICO
ever existed. The real-helper scenario below is the user-visible proof: a logo fetched as AVIF
is stored as a PNG with a thumbnail, so the agent's `view` can show it.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from lumen_agent.tools.asset_preview import asset_preview_path
from lumen_api.core import CoreClient, CoreError
from lumen_api.image_containers import INGEST_IMAGE_CONVERT_FAILED, convert_to_png
from py_lumen_config import settings

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_HELPER = REPO_ROOT / "target" / "release" / "lumen-api-helper"
BROKEN_AVIF = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1" + b"\x00" * 64


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def encode(image: Image.Image, fmt: str, **params) -> bytes:
    out = BytesIO()
    image.save(out, format=fmt, **params)
    return out.getvalue()


@pytest.fixture(scope="module")
def avif_logo() -> bytes:
    image = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    for x in range(10, 110):
        for y in range(12, 28):
            image.putpixel((x, y), (20, 40, 90, 255))
    return encode(image, "AVIF", quality=95)


@pytest.fixture(scope="module")
def ico_favicon() -> bytes:
    return encode(Image.new("RGBA", (64, 64), (200, 30, 30, 255)), "ICO", sizes=[(16, 16), (32, 32)])


class RecordingClient(CoreClient):
    """A CoreClient whose helper call is captured instead of executed."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict] = []

    def _run(self, request, raise_on_error=True):  # type: ignore[override]
        self.requests.append(request)
        return {"ok": True, "asset": {"record": {"id": request["asset_id"]}}}


def test_ingest_asset_hands_the_helper_png_bytes_for_an_avif_payload(avif_logo: bytes) -> None:
    client = RecordingClient()
    client.ingest_asset(
        store_root="/tmp/unused",
        bytes_base64=b64(avif_logo),
        asset_id="asset_ing_atrium",
        label="Atrium Hospitality logo (light_lockup)",
        declared_mime_type="image/avif",
        filename="atrium.avif",
        kind="raster_image",
        provenance={"created_by": "logo_ladder"},
    )
    (request,) = client.requests
    expected = convert_to_png(avif_logo)
    assert expected is not None
    assert base64.b64decode(request["bytes_base64"]) == expected.data
    assert request["declared_mime_type"] == "image/png"
    assert request["filename"] == "atrium.png"
    assert request["provenance"]["created_by"] == "logo_ladder"
    assert request["provenance"]["notes"][-1].startswith(
        "image container converted at ingestion: avif -> png"
    )


def test_ingest_asset_passes_a_png_through_untouched() -> None:
    client = RecordingClient()
    encoded = b64(encode(Image.new("RGB", (4, 4)), "PNG"))
    client.ingest_asset(
        store_root="/tmp/unused",
        bytes_base64=encoded,
        asset_id="asset_png",
        label="dot",
        declared_mime_type="image/png",
        filename="dot.png",
    )
    (request,) = client.requests
    assert request["bytes_base64"] is encoded
    assert request["declared_mime_type"] == "image/png"
    assert request["filename"] == "dot.png"
    assert request["provenance"] is None


def test_ingest_asset_refuses_an_undecodable_avif_without_calling_the_helper() -> None:
    client = RecordingClient()
    response = client.ingest_asset(
        store_root="/tmp/unused",
        bytes_base64=b64(BROKEN_AVIF),
        asset_id="asset_broken",
        label="broken",
        filename="broken.avif",
        raise_on_error=False,
    )
    assert client.requests == []
    assert response["ok"] is False
    assert response["error"]["code"] == INGEST_IMAGE_CONVERT_FAILED
    with pytest.raises(CoreError):
        client.ingest_asset(
            store_root="/tmp/unused",
            bytes_base64=b64(BROKEN_AVIF),
            asset_id="asset_broken",
            label="broken",
        )
    assert client.requests == []


@pytest.mark.skipif(not RELEASE_HELPER.exists(), reason="needs the release lumen-api-helper")
@pytest.mark.parametrize(
    ("fixture", "size"), [("avif_logo", (120, 40)), ("ico_favicon", (32, 32))]
)
def test_a_fetched_avif_or_ico_logo_is_stored_as_a_viewable_png(
    request, tmp_path: Path, monkeypatch, fixture: str, size: tuple[int, int]
) -> None:
    monkeypatch.setattr(settings, "lumen_core_helper", str(RELEASE_HELPER))
    payload = request.getfixturevalue(fixture)
    # The same call shape fetch_logo uses (`logo_fetch.PreparedLogo.ingest_kwargs`).
    result = CoreClient().ingest_asset(
        store_root=str(tmp_path),
        bytes_base64=b64(payload),
        asset_id=f"asset_ing_{fixture}",
        label=f"{fixture} logo",
        declared_mime_type="image/avif" if fixture == "avif_logo" else "image/x-icon",
        kind="raster_image",
        provenance={"created_by": "logo_ladder", "notes": []},
        tags=["target-account", "logo-ladder"],
        raise_on_error=False,
    )
    assert result.get("ok") is not False, result
    record = result["asset"]["record"]
    media = record["media"]
    assert media["mime_type"] == "image/png"
    assert record["kind"] == "raster_image"
    assert media.get("thumbnail"), "a PNG gets a thumbnail at ingest"
    resolved = asset_preview_path(record, tmp_path)
    assert resolved is not None, "the agent's view must be able to show it"
    preview = Path(resolved[0])
    assert preview.is_file()
    stored = tmp_path / media["location"]["opaque_ref"]
    assert Image.open(stored).size == size
