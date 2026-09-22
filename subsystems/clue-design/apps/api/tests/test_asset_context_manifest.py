from types import SimpleNamespace

from lumen_api import main


def test_inventory_reads_every_page_without_materializing_bytes(monkeypatch):
    records = [{"asset": {"id": f"asset_{i}", "kind": "raster_image", "status": "ready"}}
               for i in range(1001)]
    offsets, batches = [], []

    def read_page(*, offset, limit, **kwargs):
        offsets.append(offset)
        return records[offset:offset + limit]

    class Descriptions:
        def __init__(self, workspace_id):
            assert workspace_id == "workspace_a"

        def get_many(self, ids):
            batches.append(len(ids))
            return {id: {"revision": 4, "title": "Historical asset", "status": "ready"} for id in ids}

    monkeypatch.setattr(main, "DescriptionStore", Descriptions)
    repo = SimpleNamespace(workspace_id="workspace_a", list_asset_records=read_page)
    manifest = main.workspace_asset_library_manifest(repo)
    assert offsets == [0, 500, 1000] and batches == [500, 500, 1]
    assert len(manifest) == 1001 and manifest["asset_1000"]["revision"] == 4
    assert manifest["asset_1000"]["asset_context"]["title"] == "Historical asset"
