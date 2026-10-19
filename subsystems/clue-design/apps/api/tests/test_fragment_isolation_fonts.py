"""Pinned font resolution for isolation previews; no database or vendor calls."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from lumen_api.database import NotFoundError

DIGEST = "7e" * 32


class _FontRepo:
    workspace_id = "ws_font_preview"

    def require_brand_kit(self, kit_id, version):
        if (kit_id, version) != ("kit_pinned", 2):
            raise NotFoundError("brand_kit", kit_id)
        return {
            "brand_kit": {
                "assets": {
                    "fonts": {
                        "brand": {
                            "family": "brandAlias",
                            "faces": [
                                {"asset_id": "font_medium", "weight": 500, "style": "normal"}
                            ],
                        }
                    }
                }
            }
        }

    def require_asset_record(self, asset_id):
        if asset_id != "font_medium":
            raise NotFoundError("asset", asset_id)
        return {"asset": {"media": {"digest": {"algorithm": "sha256", "value": DIGEST}}}}


def _blobs():
    return SimpleNamespace(
        workspace_id="ws_font_preview",
        read=lambda digest: b"wOF2-held-font",
        read_blob=lambda digest: ("font/woff2", b"wOF2-held-font"),
        storage=object(),
    )


def test_pinned_font_alias_weight_and_digest_reach_isolation(tmp_path: Path) -> None:
    from lumen_api.main import fragment_isolation_fonts

    fonts = fragment_isolation_fonts(
        {"source_kit_id": "kit_pinned", "source_kit_version": 2},
        _FontRepo(),
        _blobs(),
        str(tmp_path),
    )
    assert fonts is not None
    assert 'font-family:"brandAlias"' in fonts.css
    assert "font-weight:500" in fonts.css
    assert f"https://isolation.lumen.invalid/asset-store/{DIGEST}" in fonts.css
    assert fonts.asset_digests == (DIGEST,)


@pytest.mark.parametrize(
    "pin",
    [
        {},
        {"source_kit_id": "kit_pinned"},
        {"source_kit_id": "kit_pinned", "source_kit_version": 3},
        {"source_kit_id": "foreign_kit", "source_kit_version": 2},
    ],
)
def test_missing_or_foreign_pin_does_not_fall_back_to_latest(pin, tmp_path: Path) -> None:
    from lumen_api.main import fragment_isolation_fonts

    assert fragment_isolation_fonts(pin, _FontRepo(), _blobs(), str(tmp_path)) is None


def test_font_resolution_rejects_disagreeing_workspace_custody(tmp_path: Path) -> None:
    from lumen_api.main import fragment_isolation_fonts

    blobs = _blobs()
    blobs.workspace_id = "ws_other"
    with pytest.raises(ValueError, match="workspace"):
        fragment_isolation_fonts(
            {"source_kit_id": "kit_pinned", "source_kit_version": 2},
            _FontRepo(),
            blobs,
            str(tmp_path),
        )


def test_native_repair_preview_resolves_its_frozen_font_pin(monkeypatch, tmp_path: Path) -> None:
    from lumen_api import agent_cloned_sections, fragments
    from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
    from lumen_api.main import fragment_isolation_fonts

    loaded = SimpleNamespace(
        fragment_id="frag_" + "ab" * 8,
        row={"source_kit_id": "kit_pinned", "source_kit_version": 2},
        payload={},  # ordinary capture: no declared platform dependencies
        html='<section><h2 style="font-family:brandAlias">Heading</h2></section>',
        css="",
        slot_manifest={},
        asset_digests=(),
    )
    monkeypatch.setattr(agent_cloned_sections, "read_web_fragment", lambda *a, **k: loaded)
    monkeypatch.setattr(
        fragments,
        "attach_web_fragment_preview",
        lambda *a, **k: {
            "preview_digest": "preview",
        },
    )
    blobs = _blobs()
    registry = DurableAgentClonedSectionRegistry(
        blobs=blobs,
        cache_dir=tmp_path,
        isolation_fonts=lambda row: fragment_isolation_fonts(
            row, _FontRepo(), blobs, str(tmp_path)
        ),
    )
    rendered: dict = {}

    class Core:
        def web_render(self, *args, **kwargs):
            rendered.update(kwargs)
            return {"html": "<html></html>"}

    def shoot(page, assets):
        assert assets[DIGEST] == ("font/woff2", b"wOF2-held-font")
        assert page.asset_digests == (DIGEST,)
        return b"preview-png"

    assert registry.render_repair_preview(loaded.fragment_id, Core(), shoot=shoot) == "preview"
    assert 'font-family:"brandAlias"' in rendered["font_face_css"]


def test_preview_route_resolves_its_frozen_font_pin(monkeypatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from lumen_api import main

    loaded = SimpleNamespace(
        fragment_id="frag_" + "ab" * 8,
        row={"source_kit_id": "kit_pinned", "source_kit_version": 2},
        payload={},  # ordinary capture: no declared platform dependencies
        html='<section><h2 style="font-family:brandAlias">Heading</h2></section>',
        css="",
        slot_manifest={},
        asset_digests=(),
    )
    blobs = _blobs()
    attached: dict = {}
    rendered: dict = {}
    monkeypatch.setattr(main, "read_web_fragment", lambda *a, **k: loaded)
    monkeypatch.setattr(main, "DesignBlobStore", lambda *a, **k: blobs)
    monkeypatch.setattr(main, "attach_web_fragment_preview", lambda *a, **k: attached.update(k))
    monkeypatch.setattr(main, "fragment_card", lambda *a, **k: {"fragment_id": loaded.fragment_id})
    app = main.create_app(tmp_path, storage=blobs.storage)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/web/fragments/{fragment_id}/preview"
    )
    app.dependency_overrides[route.dependant.dependencies[0].call] = _FontRepo

    class Core:
        def web_render(self, *args, **kwargs):
            rendered.update(kwargs)
            return {"html": "<html></html>"}

    def shoot(page, assets):
        assert assets[DIGEST] == ("font/woff2", b"wOF2-held-font")
        assert page.asset_digests == (DIGEST,)
        return b"preview-png"

    app.state.core = Core()
    app.state.isolation_shooter = shoot
    # No lifespan: no embedded worker, database, browser, or external service starts.
    response = TestClient(app).post(f"/web/fragments/{loaded.fragment_id}/preview")
    assert response.status_code == 200
    assert 'font-family:"brandAlias"' in rendered["font_face_css"]
    assert attached["workspace_id"] == _FontRepo.workspace_id
    assert attached["preview"] == b"preview-png"
