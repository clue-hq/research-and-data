"""A poster and a smaller rendition for each captured video (brand facts plan 2026-10-17, Task 4).

At capture, every video the pages hold gets, with ``ffmpeg`` on PATH:
- a poster: the frame at 1 s (the first frame for a shorter video), JPEG, at the video's own width;
- when the file is over 1.5 MB, one rendition at most 1280 px wide (H.264 ``-crf 28``,
  ``-preset veryfast``, ``-movflags +faststart``, no audio), kept only when it is smaller.

Both are stored as blobs of the workspace and named in ``design_video_rendition`` by the video's
digest, beside the immutable fragment payload (controller ruling 2026-10-17). A digest that already
has a row is skipped, so a re-capture costs nothing. Without ``ffmpeg`` nothing is made and one
diagnostic says so; a video ffmpeg cannot read gets a diagnostic and no row (tried again next time).
Never fails the capture.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

RENDITION_MIN_BYTES = 1_500_000
RENDITION_MAX_WIDTH = 1280
_FFMPEG_TIMEOUT_S = 120

Made = tuple["bytes | None", "bytes | None"]


def _ffmpeg(*args: str) -> bool:
    try:
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *args], capture_output=True, timeout=_FFMPEG_TIMEOUT_S
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() and path.stat().st_size > 0 else None


def make_video_renditions(data: bytes) -> Made:
    """``(poster JPEG, smaller rendition MP4)`` for one video; either is None when not made."""
    with tempfile.TemporaryDirectory(prefix="lumen-video-") as folder:
        source, poster_path, rendition_path = (Path(folder) / name for name in ("in", "poster.jpg", "out.mp4"))
        source.write_bytes(data)
        poster = None
        for at in ("1", "0"):
            if _ffmpeg("-ss", at, "-i", str(source), "-frames:v", "1", "-q:v", "3", str(poster_path)):
                poster = _read(poster_path)
                if poster:
                    break
        rendition = None
        if len(data) > RENDITION_MIN_BYTES and _ffmpeg(
            "-i", str(source), "-vf", f"scale='min({RENDITION_MAX_WIDTH},iw)':-2",
            "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-an", str(rendition_path),
        ):
            made = _read(rendition_path)
            rendition = made if made and len(made) < len(data) else None
        return poster, rendition


def captured_videos(snapshots: Iterable[object]) -> dict[str, bytes]:
    """Every video the captured pages downloaded, by the digest the fragment rehoster names it with
    (sha256 of the bytes, ``sections.mint.make_asset_rehoster``)."""
    videos: dict[str, bytes] = {}
    for snapshot in snapshots:
        for download in getattr(snapshot, "downloads", None) or []:
            if getattr(download, "kind", None) != "video":
                continue
            try:
                data = base64.b64decode(getattr(download, "bytes_b64", "") or "")
            except (binascii.Error, ValueError):
                continue
            if data:
                videos.setdefault(hashlib.sha256(data).hexdigest(), data)
    return videos


def _run(workspace_id: str, call: Callable) -> object:
    from lumen_api.design_store import DesignStoreBridge

    return DesignStoreBridge(workspace_id)._run(call)


def video_renditions_for(digests: Iterable[str], *, workspace_id: str) -> dict[str, dict[str, str | None]]:
    """What was made for these videos, by video digest (absent: nothing made yet)."""
    from clue_design import video_renditions as dal

    wanted = sorted(set(digests))
    if not wanted:
        return {}
    return _run(workspace_id, lambda conn: dal.get_many(conn, workspace_id=workspace_id, video_digests=wanted))


def ensure_video_renditions(
    videos: Mapping[str, bytes],
    *,
    workspace_id: str,
    register: Callable[[bytes, str], str],
    make: Callable[[bytes], Made] = make_video_renditions,
    ffmpeg_present: bool | None = None,
) -> list[dict]:
    """Make and record a poster and a rendition for every video (``{digest: bytes}``) that has none.

    ``register(bytes, media type) -> digest`` stores a made file as a workspace blob. Returns the
    diagnostics; never raises for one video.
    """
    from clue_design import video_renditions as dal

    if not videos:
        return []
    if ffmpeg_present is None:
        ffmpeg_present = shutil.which("ffmpeg") is not None
    if not ffmpeg_present:
        return [{
            "code": "LUMI0545", "severity": "warning",
            "message": f"ffmpeg is not on PATH: no poster or smaller rendition was made for {len(videos)} captured video(s)",
        }]
    known = video_renditions_for(videos, workspace_id=workspace_id)
    diagnostics: list[dict] = []
    for digest, data in videos.items():
        if digest in known:
            continue
        try:
            poster, rendition = make(data)
            poster_digest = register(poster, "image/jpeg") if poster else None
            rendition_digest = register(rendition, "video/mp4") if rendition else None
        except Exception as error:  # noqa: BLE001 - one video is not the capture
            poster_digest = rendition_digest = None
            reason = f"{type(error).__name__}: {error}"[:300]
        else:
            reason = "ffmpeg could not read it"
        if poster_digest is None and rendition_digest is None:
            diagnostics.append({
                "code": "LUMI0546", "severity": "warning",
                "message": f"no poster or rendition was made for captured video {digest[:12]}: {reason}",
            })
            continue
        _run(workspace_id, lambda conn, d=digest, p=poster_digest, r=rendition_digest: dal.put(
            conn, workspace_id=workspace_id, video_digest=d, poster_digest=p, rendition_digest=r))
    return diagnostics
