"""A captured video gets a poster and, when large, a smaller rendition, kept beside the fragment by
the video's digest (brand facts plan 2026-10-17, Task 4; controller ruling: the fragment payload is
untouched). The site's clones carry the map, site-kit's fillClone uses it, and the preview serves
the poster on request."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess

import pytest

from lumen_api.design_store import default_workspace_id
from lumen_ingestion.capture import video_renditions as vr

FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _synthetic_mp4(tmp_path, *, seconds: int = 3) -> bytes:
    out = tmp_path / "in.mp4"
    subprocess.run(
        # Noise keeps the encoder from squeezing the test pattern: about 2 MB at 1920 wide.
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
         "-vf", "noise=alls=20:allf=t", "-c:v", "libx264", "-crf", "31", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", str(out)],
        check=True, timeout=120,
    )
    return out.read_bytes()


def _width(data: bytes, tmp_path, name: str) -> int:
    path = tmp_path / name
    path.write_bytes(data)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return int(probe.stdout.strip())


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not on PATH")
def test_ffmpeg_makes_a_full_width_poster_and_a_smaller_rendition_of_a_large_video(tmp_path) -> None:
    source = _synthetic_mp4(tmp_path)
    assert len(source) > vr.RENDITION_MIN_BYTES  # a ~2 MB file, over the 1.5 MB line
    poster, rendition = vr.make_video_renditions(source)
    assert poster is not None and poster[:2] == b"\xff\xd8"  # a JPEG
    from PIL import Image

    assert Image.open(io.BytesIO(poster)).width == 1920
    assert rendition is not None and len(rendition) < len(source)
    assert _width(rendition, tmp_path, "out.mp4") == 1280


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not on PATH")
def test_a_small_video_gets_a_poster_and_no_rendition(tmp_path) -> None:
    small = tmp_path / "small.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(small)], check=True, timeout=60)
    poster, rendition = vr.make_video_renditions(small.read_bytes())
    assert poster is not None and rendition is None


def test_without_ffmpeg_nothing_is_made_and_a_diagnostic_says_so(monkeypatch) -> None:
    monkeypatch.setattr(vr.shutil, "which", lambda name: None)
    digest = hashlib.sha256(b"no ffmpeg video").hexdigest()
    made: list[str] = []
    diagnostics = vr.ensure_video_renditions(
        {digest: b"no ffmpeg video"}, workspace_id=default_workspace_id(),
        register=lambda data, media_type: made.append(media_type) or "0" * 64,
    )
    assert made == []
    assert [d["code"] for d in diagnostics] == ["LUMI0545"]
    assert "ffmpeg" in diagnostics[0]["message"]
    assert vr.video_renditions_for([digest], workspace_id=default_workspace_id()) == {}


def test_renditions_are_kept_by_the_videos_digest_and_a_recapture_makes_none_again() -> None:
    from lumen_api.site_brand import clone_video_renditions

    workspace_id = default_workspace_id()
    video = f"rendition test video {hashlib.sha256(str(id(object())).encode()).hexdigest()}".encode()
    digest = hashlib.sha256(video).hexdigest()
    calls: list[bytes] = []
    stored: dict[str, bytes] = {}

    def make(data: bytes):
        calls.append(data)
        return b"poster bytes " + data, b"rendition bytes " + data

    def register(data: bytes, media_type: str) -> str:
        key = hashlib.sha256(data).hexdigest()
        stored[key] = data
        return key

    for _ in range(2):  # a capture, then a re-capture of the same video
        assert vr.ensure_video_renditions({digest: video}, workspace_id=workspace_id, register=register, make=make,
                                          ffmpeg_present=True) == []
    assert calls == [video]
    poster = hashlib.sha256(b"poster bytes " + video).hexdigest()
    rendition = hashlib.sha256(b"rendition bytes " + video).hexdigest()
    assert vr.video_renditions_for([digest], workspace_id=workspace_id) == {
        digest: {"poster": poster, "rendition": rendition}}
    clones = [{"id": "frag_v", "html": f'<video autoplay muted><source src="/asset-store/{digest}" type="video/mp4"></video>'}]
    assert clone_video_renditions(clones, workspace_id=workspace_id) == {digest: {"poster": poster, "rendition": rendition}}


def test_the_preview_serves_the_poster_on_request() -> None:
    from lumen_api.site_render import RenderedPage, capture_site_screenshot

    poster = hashlib.sha256(b"poster").hexdigest()
    asked: list[str] = []
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (1, 64, 54)).save(buffer, format="JPEG")

    def read_blob(digest: str):
        asked.append(digest)
        return "image/jpeg", buffer.getvalue()

    html = f'<video preload="metadata" poster="/asset-store/{poster}" width="640" height="360"></video>'
    capture_site_screenshot(RenderedPage(route="/", html=html), "", width=800, read_blob=read_blob)
    assert poster in asked


def test_the_capture_hands_every_downloaded_video_over_by_its_digest() -> None:
    import base64
    from types import SimpleNamespace

    clip, image = b"a captured clip", b"a captured photo"
    page = SimpleNamespace(downloads=[
        SimpleNamespace(kind="video", bytes_b64=base64.b64encode(clip).decode(), sha256="ignored"),
        SimpleNamespace(kind="image", bytes_b64=base64.b64encode(image).decode(), sha256="ignored"),
    ])
    again = SimpleNamespace(downloads=[page.downloads[0]])
    assert vr.captured_videos([page, again]) == {hashlib.sha256(clip).hexdigest(): clip}
