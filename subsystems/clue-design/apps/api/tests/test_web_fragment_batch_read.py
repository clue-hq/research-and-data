"""Reading many fragments at once (site loading, 2026-10-29).

A site's brand carries every released section of the workspace. Production read them one at a
time — one transaction and one storage fetch each — so opening a site with ~100 sections spent
about 8 s on this alone, and every save paid it again (the save check loads the brand too).

``read_web_fragments`` reads them in one transaction, fetches the payloads it has not seen before
in parallel, and keeps parsed payloads in memory (they are content-addressed, so a digest's bytes
never change). The row and the blob's record are still read fresh on every call, so a fragment
another tenant holds, one that is gone, or one whose blob was erased is left out exactly as the
single read refuses it.
"""

from __future__ import annotations

import pytest
from lumen_api.design_store import DesignStoreBridge
from lumen_api.fragments import create_web_fragment, read_web_fragment, read_web_fragments, registry

from clue_design.storage import design_storage_key
from clue_storage import FsStorage
from clue_storage.artifacts import mark_erased


class CountingStorage(FsStorage):
    """An ``FsStorage`` that counts the payload fetches made through it."""

    def __init__(self, root) -> None:
        super().__init__(root)
        self.gets: list[str] = []

    async def get(self, key: str) -> bytes:
        self.gets.append(key)
        return await super().get(key)


@pytest.fixture
def storage(tmp_path) -> CountingStorage:
    return CountingStorage(tmp_path / "design-storage")


@pytest.fixture(autouse=True)
def _empty_payload_cache():
    registry.clear_fragment_payload_cache()
    yield
    registry.clear_fragment_payload_cache()


def _create(workspace_id: str, storage: FsStorage, n: int):
    html = f'<section class="band"><h2 class="head">Band {n}</h2></section>'
    row, artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=html,
        css=f".band {{ padding: {n}px }}",
        rehosted={},
        source_url="https://seller.example/",
        section_role="section",
    )
    return row, artifact


def test_many_fragments_read_back_exactly_as_one_at_a_time(workspace_id: str, storage) -> None:
    ids = [_create(workspace_id, storage, n)[1].fragment_id for n in range(4)]

    batch = read_web_fragments(storage, workspace_id=workspace_id, fragment_ids=ids)

    assert list(batch) == ids, "answers come back in the order asked"
    for fragment_id in ids:
        single = read_web_fragment(storage, workspace_id=workspace_id, fragment_id=fragment_id)
        assert batch[fragment_id].row == single.row
        assert batch[fragment_id].payload == single.payload


def test_unknown_and_other_tenants_fragments_are_left_out(workspace_id: str, storage) -> None:
    _, mine = _create(workspace_id, storage, 1)
    _, theirs = _create(f"{workspace_id}_other", storage, 2)

    batch = read_web_fragments(
        storage,
        workspace_id=workspace_id,
        fragment_ids=[mine.fragment_id, theirs.fragment_id, "wf_" + "0" * 32],
    )

    assert list(batch) == [mine.fragment_id]


def test_a_second_read_fetches_nothing_but_still_honours_an_erased_blob(
    workspace_id: str, storage
) -> None:
    rows = [_create(workspace_id, storage, n)[0] for n in range(3)]
    ids = [str(row["fragment_id"]) for row in rows]

    read_web_fragments(storage, workspace_id=workspace_id, fragment_ids=ids)
    assert len(storage.gets) == 3
    storage.gets.clear()

    again = read_web_fragments(storage, workspace_id=workspace_id, fragment_ids=ids)
    assert list(again) == ids
    assert storage.gets == [], "parsed payloads are kept, so no fetch is repeated"

    erased_key = design_storage_key(workspace_id, rows[1]["payload_digest"])
    DesignStoreBridge(workspace_id)._run(lambda conn: mark_erased(conn, erased_key))

    after = read_web_fragments(storage, workspace_id=workspace_id, fragment_ids=ids)
    assert list(after) == [ids[0], ids[2]], "an erased blob is left out even though it was kept"
    assert storage.gets == []


def test_a_missing_blob_is_left_out_and_the_rest_still_load(workspace_id: str, storage) -> None:
    rows = [_create(workspace_id, storage, n)[0] for n in range(2)]
    gone = storage._path(design_storage_key(workspace_id, rows[0]["payload_digest"]))
    gone.unlink()

    batch = read_web_fragments(
        storage, workspace_id=workspace_id, fragment_ids=[str(row["fragment_id"]) for row in rows]
    )

    assert list(batch) == [str(rows[1]["fragment_id"])]


def test_the_payload_cache_stays_under_its_byte_limit(
    workspace_id: str, storage, monkeypatch
) -> None:
    rows = [_create(workspace_id, storage, n)[0] for n in range(3)]
    ids = [str(row["fragment_id"]) for row in rows]
    first_key = design_storage_key(workspace_id, rows[0]["payload_digest"])
    one = len(storage._path(first_key).read_bytes())
    monkeypatch.setattr(registry, "FRAGMENT_PAYLOAD_CACHE_MAX_BYTES", one * 2 + one // 2)

    read_web_fragments(storage, workspace_id=workspace_id, fragment_ids=ids)
    storage.gets.clear()
    read_web_fragments(storage, workspace_id=workspace_id, fragment_ids=ids)

    assert len(storage.gets) >= 1, "the oldest payload was dropped to stay under the limit"
    assert registry.fragment_payload_cache_bytes() <= one * 2 + one // 2
