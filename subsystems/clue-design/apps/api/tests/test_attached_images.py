"""Attached images become library images and design references (spec 2026-10-30 §3.4).

An image sent in the chat thread is registered once in the workspace's image library — keyed by
the file's own sha256, so a retried or taken-over turn registers the same asset — labelled with
its filename and tagged as attached in chat. On an ad turn, the images sent with THIS message ride
as references (up to the cap); on a site turn, the site agent can look at them and place them.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, replace

from conftest import make_blob_store
from lumen_api.asset_custody import write_cache_blob
from lumen_api.attached_images import (
    ATTACHED_IN_CHAT_TAG,
    attached_reference_ids,
    register_attached_images,
)
from lumen_api.main import REFERENCE_ASSETS_MAX, create_app

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'
PNG = b"\x89PNG\r\n\x1a\nattached"


@dataclass(frozen=True)
class _File:
    filename: str
    media_type: str
    sha256: str
    data: bytes
    current: bool = True
    viewable: tuple[bytes, str] | None = None
    unavailable: str | None = None


def _image(name: str, data: bytes, media: str, *, current: bool = True) -> _File:
    return _File(name, media, hashlib.sha256(data).hexdigest(), data, current, (data, media))


class _Core:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_asset(self, **kwargs):
        self.calls.append(kwargs)
        data = base64.b64decode(kwargs["bytes_base64"])
        digest = hashlib.sha256(data).hexdigest()
        write_cache_blob(kwargs["store_root"], digest, data)
        return {"ok": True, "asset": {"record": {
            "id": kwargs["asset_id"], "kind": kwargs["kind"], "label": kwargs["label"],
            "status": "ready", "source": kwargs["source"], "tags": kwargs["tags"],
            "media": {"mime_type": kwargs["declared_mime_type"],
                      "digest": {"algorithm": "sha256", "value": digest},
                      "location": {"provider": "local-store", "opaque_ref": f"sha256/{digest[:2]}/{digest}"}}}}}


class _Invocations:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def invoke(self, name, body, *, workspace_id, actor, actor_id=None):
        assert name == "design_register_asset_record" and actor == "agent"
        self.records.append(body["record"])


def test_attached_images_register_once_each_under_the_files_own_digest(tmp_path, design_storage) -> None:
    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    core, invocations = _Core(), _Invocations()
    files = [
        _image("photo.png", PNG, "image/png"),
        _image("logo.svg", SVG, "image/svg+xml"),
        _File("brief.md", "text/markdown", "b" * 64, b"# Brief"),
        replace(_image("gone.png", b"gone", "image/png"), viewable=None, unavailable="erased"),
    ]

    def register() -> dict[str, str]:
        return register_attached_images(
            core=core, blobs=blobs, cache_dir=tmp_path / "cache", invocations=invocations,
            run_id="run_1", files=files,
        )

    first = register()
    second = register()
    assert first == second
    assert set(first) == {files[0].sha256, files[1].sha256}
    # A retried turn re-registers the SAME ids: the library's upsert keeps one row per image.
    assert [r["id"] for r in invocations.records] == [first[files[0].sha256], first[files[1].sha256]] * 2
    record = invocations.records[0]
    assert record["label"] == "photo.png" and ATTACHED_IN_CHAT_TAG in record["tags"]
    assert record["source"]["kind"] == "uploaded"
    assert [call["kind"] for call in core.calls[:2]] == ["raster_image", "vector"]


def test_an_ad_turns_references_are_its_tags_then_this_messages_images() -> None:
    files = [
        _image("old.png", b"old", "image/png", current=False),
        *[_image(f"new{n}.png", f"new{n}".encode(), "image/png") for n in range(5)],
    ]
    registered = {item.sha256: f"asset_att_{n}" for n, item in enumerate(files)}
    ids = attached_reference_ids(["asset_tagged"], files, registered)
    assert ids == ["asset_tagged", "asset_att_1", "asset_att_2", "asset_att_3"]
    assert len(ids) == REFERENCE_ASSETS_MAX
    # An older message's image is in the library, never a reference of this turn.
    assert "asset_att_0" not in attached_reference_ids([], files, registered)


def test_a_leg_ad_turns_request_gains_this_messages_images(monkeypatch) -> None:
    from types import SimpleNamespace

    from lumen_api import attached_images, main
    from lumen_api.models import AgentTurnPreviewRequest

    photo = _image("photo.png", PNG, "image/png")
    older = _image("older.png", b"older", "image/png", current=False)

    class _Reads:
        def thread_attachments(self):
            return (older, photo)

    monkeypatch.setattr(
        attached_images,
        "register_attached_images",
        lambda **kw: {item.sha256: f"asset_att_{item.filename}" for item in kw["files"]},
    )
    for name in ("_turn_core", "_turn_blob_store", "_host_engine_cache_root", "_turn_design_tools"):
        monkeypatch.setattr(main, name, lambda *a, **k: SimpleNamespace(workspace_id="ws"))
    envelope = SimpleNamespace(run_id="run_1", workspace_id="ws")
    payload = AgentTurnPreviewRequest(prompt="Use my photo", scene={}, reference_asset_ids=["asset_tagged"])

    updated = main._with_attached_references(None, envelope, None, payload, _Reads())
    assert updated.reference_asset_ids == ["asset_tagged", "asset_att_photo.png"]


def test_the_real_engine_registers_an_attached_png_and_svg(tmp_path, design_storage) -> None:
    """The fake core above accepts any source; the engine does not. Review C-1 (2026-10-30): a
    source kind the engine has no variant for made it refuse every attached image."""

    import io

    from PIL import Image

    from lumen_api.core import CoreClient

    out = io.BytesIO()
    Image.new("RGB", (8, 6), (10, 20, 30)).save(out, format="PNG")
    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    invocations = _Invocations()
    files = [_image("photo.png", out.getvalue(), "image/png"), _image("logo.svg", SVG, "image/svg+xml")]
    registered = register_attached_images(
        core=CoreClient(), blobs=blobs, cache_dir=tmp_path / "cache", invocations=invocations,
        run_id="run_1", files=files,
    )
    assert set(registered) == {files[0].sha256, files[1].sha256}
    record = invocations.records[0]
    assert record["source"]["kind"] == "uploaded" and record["source"]["filename"] == "photo.png"
    assert ATTACHED_IN_CHAT_TAG in record["tags"]
    assert record["provenance"]["source_label"] == "chat_attachment"


def test_an_image_already_in_the_library_is_not_registered_again(tmp_path, design_storage) -> None:
    """Review M-4: every turn re-registered every image of the thread, which re-ran the engine and
    overwrote a label the person may have changed in the library."""

    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    core, invocations = _Core(), _Invocations()
    photo = _image("photo.png", PNG, "image/png")
    registered = register_attached_images(
        core=core, blobs=blobs, cache_dir=tmp_path / "cache", invocations=invocations,
        run_id="run_2", files=[photo], known=lambda asset_ids: set(asset_ids),
    )
    assert registered == {photo.sha256: f"asset_att_{photo.sha256[:32]}"}
    assert core.calls == [] and invocations.records == []


def test_a_turn_whose_image_setup_fails_still_runs_with_its_files(monkeypatch) -> None:
    """Review M-7: attached images are a capability, never a precondition: a helper that cannot be
    built leaves the turn its files and no library images, never a failed turn."""

    from types import SimpleNamespace

    from lumen_api import main

    photo = _image("photo.png", PNG, "image/png")

    class _Reads:
        def thread_attachments(self):
            return (photo,)

    def broken(*args, **kwargs):
        raise RuntimeError("engine helper missing")

    monkeypatch.setattr(main, "_turn_core", broken)
    envelope = SimpleNamespace(run_id="run_1", workspace_id="ws")
    files, registered = main._attached_images(None, envelope, None, _Reads())
    assert files == (photo,) and registered == {}
