"""An archived asset is gone for the design agent too (asset delete, 2026-10-31).

The Assets page's Delete archives an asset. The workspace library already leaves archived records
out; the brand kit's own logos and images are read by id from the kit, so they need the same rule.
"""

from __future__ import annotations

import pytest
from lumen_api import main


class _Repo:
    workspace_id = "ws_archived"

    def __init__(self, records):
        self.records = records

    def require_asset_record(self, asset_id):
        return {"asset": self.records[asset_id]}


KIT = {
    "assets": {
        "logos": {"primary": {"variants": [{"asset_id": "asset_logo"}]}},
        "images": {"hero": {"asset_id": "asset_kept"}, "old": {"asset_id": "asset_gone"}},
    }
}


@pytest.fixture(autouse=True)
def _no_bytes(monkeypatch):
    monkeypatch.setattr(main, "ensure_materialized", lambda *_a, **_k: None)


def test_an_archived_kit_image_is_not_handed_to_the_agent():
    repo = _Repo(
        {
            "asset_logo": {"id": "asset_logo", "status": "ready"},
            "asset_kept": {"id": "asset_kept", "status": "ready"},
            "asset_gone": {"id": "asset_gone", "status": "archived"},
        }
    )
    manifest = main.brand_kit_asset_manifest(repo, KIT, blobs=None, cache_dir="/tmp")
    assert set(manifest) == {"asset_logo", "asset_kept"}
