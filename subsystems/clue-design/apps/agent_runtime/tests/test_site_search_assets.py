"""search_assets for the site agent (Lane B Task 11): the scene's hybrid search, with files."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from site_fixtures import FakeAssets, garner_site, inputs_for, png

D_CLASS, D_DASH = "1" * 64, "2" * 64
CANDIDATES = {
    "asset_classroom": {"origin": "library", "title": "Classroom", "description": "A calm classroom in morning light.",
                        "record": {"id": "asset_classroom", "kind": "raster_image", "label": "classroom.png",
                                   "media": {"mime_type": "image/png", "digest": {"value": D_CLASS}}}},
    "asset_dashboard": {"origin": "brand_kit", "title": "Dashboard", "description": "The product dashboard.",
                        "record": {"id": "asset_dashboard", "kind": "raster_image", "label": "dash.png",
                                   "media": {"mime_type": "image/png", "digest": {"value": D_DASH}}}},
}


def _vec(*hot):
    v = np.zeros(512, np.float32)
    for i in hot:
        v[i] = 1.0
    return (v / np.linalg.norm(v)).tolist()


def _tools(tmp_path: Path, embeddings=None) -> SiteTools:
    inputs = inputs_for(asset_candidates=CANDIDATES, asset_embeddings=embeddings,
                        assets=FakeAssets(blobs={D_CLASS: ("image/png", png())}))
    materialize_workspace(tmp_path / "workspace", inputs, site=garner_site())
    return SiteTools(workspace=tmp_path / "workspace", inputs=inputs, base_site=garner_site(), retry_delay_s=0)


def test_results_carry_a_placeable_file_and_join_the_turns_brand(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    answer = json.loads(tools.search_assets("calm classroom"))
    assert answer["status"] == "ok" and answer["visual_search"].startswith("off")
    first = answer["results"][0]
    assert first["asset_id"] == "asset_classroom" and first["file"] == f"/asset-store/{D_CLASS}"
    assert "view" not in first
    assert tools.view_asset([first["file"]])[0]["text"].startswith(first["file"])


def test_the_look_finds_an_image_whose_words_do_not_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api import asset_embeddings

    monkeypatch.setattr(asset_embeddings, "embed_query", lambda text: np.array(_vec(7), np.float32))
    tools = _tools(tmp_path, embeddings={"asset_dashboard": _vec(7), "asset_classroom": _vec(1)})
    answer = json.loads(tools.search_assets("blue glowing interface"))
    assert answer["visual_search"] == "on" and answer["results"][0]["asset_id"] == "asset_dashboard"


def test_bad_inputs_are_refused(tmp_path: Path) -> None:
    assert json.loads(_tools(tmp_path).search_assets("x", limit=0))["status"] == "error"
