"""The site routes (Wave 2 Contract 2): save, undo, redo, versions and restore, with the
refusals a second writer meets."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from py_lumen_config import settings

from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.site_render import SectionModule
from site_kit_support import born_site, ensure_site_kit_dist, garner_brand, garner_site, hold_site_images, install_site_inputs, store_site
from test_agent_run_write_lock import finish_run, start_leg_run

DOC = "site_routes"

QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "surface": {"type": "string", "enum": ["page", "card", "muted", "brandSubtle", "brand", "inverse"]},
        "quote": {"type": "string", "minLength": 1},
    },
    "required": ["id", "surface", "quote"],
    "additionalProperties": False,
}


def quote_module(module_js: str = "export const schema = null;\n") -> SectionModule:
    # An agent section the way test_site_validation builds one; its bytes are only hashed here.
    return SectionModule(
        name="QuoteBand", digest=hashlib.sha256(module_js.encode()).hexdigest(),
        module_js=module_js, css="", props_schema=QUOTE_SCHEMA,
    )


@pytest.fixture(autouse=True)
def _no_embedded_fleet_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # The write-lock test seeds a running run row directly; nothing here offers fleet work.
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


@pytest.fixture()
def site_a(client: TestClient) -> dict:
    site, brand = hold_site_images(garner_site(DOC), garner_brand(), make_blob_store(client.app))
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand)
    return site


def with_heading(site: dict, heading: str) -> dict:
    changed = copy.deepcopy(site)
    changed["pages"]["/analysis"]["content"][3]["props"]["heading"] = heading  # CtaBand "cta"
    return changed


def save(client: TestClient, site: dict, base_version: int):
    return client.put(f"/documents/{DOC}/site", json={"site": site, "base_version": base_version})


def stored_site(client: TestClient) -> dict:
    return client.get(f"/documents/{DOC}").json()["scene"]


def test_a_save_writes_one_version(client: TestClient, site_a: dict) -> None:
    response = save(client, site_a, 0)
    assert response.status_code == 200, response.text
    assert response.json() == {"schema_version": 1, "document": {"id": DOC, "current_version": 1, "doc_kind": "site"}}
    assert stored_site(client)["pages"] == site_a["pages"]


def test_a_stale_save_is_refused_with_the_current_version(client: TestClient, site_a: dict) -> None:
    assert save(client, site_a, 0).status_code == 200
    stale = save(client, with_heading(site_a, "Second tab"), 0)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "edits.base_version_mismatch"
    assert stale.json()["detail"]["current_version"] == 1
    assert stored_site(client)["pages"] == site_a["pages"]


def test_an_invalid_site_is_refused_with_its_errors(client: TestClient, site_a: dict) -> None:
    broken = copy.deepcopy(site_a)
    broken["pages"]["/analysis"]["content"][0]["props"]["surface"] = "green"
    response = save(client, broken, 0)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "site.invalid"
    assert any("surface" in error for error in response.json()["detail"]["errors"])


def test_an_image_this_workspace_does_not_hold_is_refused_by_name(client: TestClient, site_a: dict) -> None:
    foreign = copy.deepcopy(site_a)
    foreign["pages"]["/analysis"]["content"][0]["props"]["image"] = "/asset-store/" + "e" * 64
    response = save(client, foreign, 0)
    assert response.status_code == 422
    assert f"image /asset-store/{'e' * 64} is not stored in this workspace" in " ".join(response.json()["detail"]["errors"])
    assert HybridRepository().require_document(DOC)["current_version"] == 0


def test_a_save_is_refused_while_a_site_turn_runs(client: TestClient, site_a: dict) -> None:
    repo = HybridRepository()
    run_id = start_leg_run(repo, DOC)
    try:
        response = save(client, site_a, 0)
        assert response.status_code == 409
        assert response.json()["detail"] == {"code": "document.agent_run_active", "run_id": run_id}
        undo = client.post(f"/documents/{DOC}/site/undo", json={"base_version": 0})
        assert undo.json()["detail"]["code"] == "document.agent_run_active"
    finally:
        finish_run(repo, run_id)
    assert save(client, site_a, 0).status_code == 200


def test_a_web_document_is_not_a_site(client: TestClient, site_a: dict) -> None:
    web = client.post("/documents", json={"doc_kind": "web", "title": "W"}).json()["document"]
    response = client.put(f"/documents/{web['id']}/site", json={"site": site_a, "base_version": 0})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "document.kind_unsupported"


def test_without_a_brand_builder_a_save_is_a_typed_503(client: TestClient, site_a: dict) -> None:
    from lumen_api.site_doc_inputs import brand_loader_not_composed

    client.app.state.site_brand_loader = brand_loader_not_composed
    response = save(client, site_a, 0)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "site_inputs.unavailable"
    brand = client.get(f"/documents/{DOC}/site/brand")
    assert brand.status_code == 503 and brand.json()["detail"]["code"] == "site_inputs.unavailable"


def test_the_brand_read_serves_the_composed_builders_brand(client: TestClient, site_a: dict) -> None:
    """Controller ruling R3: the editor frame's BrandData comes from the same seam the save uses."""
    seen: list[str] = []

    def builder(repo, blobs, document):
        seen.append(document["id"])
        return {"slug": "garner", "kit": {}, "fonts": [], "assets": {}, "clones": {}, "measured": None}

    client.app.state.site_brand_loader = builder
    response = client.get(f"/documents/{DOC}/site/brand")
    assert response.status_code == 200
    assert response.json() == {"schema_version": 1, "brand": builder(None, None, {"id": DOC})}
    assert seen[0] == DOC


def test_undo_and_redo_walk_the_snapshots_exactly(client: TestClient, site_a: dict) -> None:
    site_b = with_heading(site_a, "The analysis, free")
    assert save(client, site_a, 0).status_code == 200
    assert save(client, site_b, 1).status_code == 200
    undone = client.post(f"/documents/{DOC}/site/undo", json={"base_version": 2})
    assert undone.status_code == 200, undone.text
    assert undone.json()["document"]["current_version"] == 3 and undone.json()["undone_batch_id"]
    assert stored_site(client)["pages"] == site_a["pages"]
    assert client.post(f"/documents/{DOC}/site/undo", json={"base_version": 3}).status_code == 200
    assert stored_site(client)["shell"] is None  # back to the born site
    empty = client.post(f"/documents/{DOC}/site/undo", json={"base_version": 4})
    assert empty.status_code == 409 and empty.json()["detail"]["code"] == "undo.empty"
    redone = client.post(f"/documents/{DOC}/site/redo", json={"base_version": 4})
    assert redone.status_code == 200 and redone.json()["redone_batch_id"]
    assert stored_site(client)["pages"] == site_a["pages"]
    assert save(client, with_heading(site_a, "A new save"), 5).status_code == 200
    gone = client.post(f"/documents/{DOC}/site/redo", json={"base_version": 6})
    assert gone.status_code == 409 and gone.json()["detail"]["code"] == "redo.empty"


def test_versions_list_newest_first_and_a_restore_is_undoable(client: TestClient, site_a: dict) -> None:
    site_b = with_heading(site_a, "The analysis, free")
    assert save(client, site_a, 0).status_code == 200
    assert save(client, site_b, 1).status_code == 200
    versions = client.get(f"/documents/{DOC}/site/versions").json()["versions"]
    assert [entry["version"] for entry in versions] == [2, 1]
    assert {entry["actor_kind"] for entry in versions} == {"editor"}
    first = versions[1]["batch_id"]
    restored = client.post(f"/documents/{DOC}/site/versions/{first}/restore", json={"base_version": 2})
    assert restored.status_code == 200, restored.text
    assert restored.json()["document"]["current_version"] == 3
    assert stored_site(client)["pages"] == site_a["pages"]
    assert client.post(f"/documents/{DOC}/site/undo", json={"base_version": 3}).status_code == 200
    assert stored_site(client)["pages"] == site_b["pages"]
    missing = client.post(f"/documents/{DOC}/site/versions/batch_nope/restore", json={"base_version": 4})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "version.not_found"


def test_a_restore_reinstates_the_agent_sections_its_version_held(client: TestClient, workspace_id: str) -> None:
    """A restore lands exactly the site that stood: the agent section a manual save removed comes
    back with its pin, because the tool re-reads the snapshot (it is not client data)."""
    module = quote_module()
    site, brand = hold_site_images(garner_site(DOC), garner_brand(), make_blob_store(client.app))
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand, sections=[module])
    with_quote = copy.deepcopy(site)
    with_quote["agent_sections"] = {"QuoteBand": module.digest}
    with_quote["pages"]["/"]["content"].append(
        {"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": "Fewer surprises."}}
    )
    client.app.state.design_tools.invoke(
        "design_write_site",
        {"document_id": DOC, "site": with_quote, "intent": "Site turn", "actor_kind": "agent", "source": "agent", "expected_base_version": 0},
        workspace_id=workspace_id,
        actor="agent",
    )
    assert save(client, site, 1).status_code == 200  # the quote and its pin removed by hand
    assert stored_site(client)["agent_sections"] == {}
    versions = client.get(f"/documents/{DOC}/site/versions").json()["versions"]
    first = next(entry["batch_id"] for entry in versions if entry["version"] == 1)
    restored = client.post(f"/documents/{DOC}/site/versions/{first}/restore", json={"base_version": 2})
    assert restored.status_code == 200, restored.text
    stored = stored_site(client)
    assert stored["agent_sections"] == {"QuoteBand": module.digest}
    assert stored["pages"]["/"]["content"][-1]["type"] == "QuoteBand"


def test_every_site_write_reports_the_version_it_produced_not_a_later_one(
    client: TestClient, site_a: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding S3-3. Another writer (here a rename) lands between each write's commit and
    the route's answer. The route must report the version ITS write produced: the editor adopts that
    as its next base, so a re-read would make the editor's next save silently revert the rename."""
    original = HybridRepository.update_site_document
    produced: list[int] = []

    def write_then_someone_renames(self, document_id, site, **kwargs):
        written = original(self, document_id, site, **kwargs)
        produced.append(int(written["current_version"]))
        HybridRepository().rename_document(document_id, f"Renamed after v{written['current_version']}")
        return written

    monkeypatch.setattr(HybridRepository, "update_site_document", write_then_someone_renames)

    saved = client.put(f"/documents/{DOC}/site", json={"site": site_a, "base_version": 0})
    assert saved.status_code == 200, saved.text
    assert saved.json()["document"]["current_version"] == produced[-1]
    # The editor's next save from that base meets the rename and is refused, never a silent revert.
    stale = client.put(f"/documents/{DOC}/site", json={"site": site_a, "base_version": produced[-1]})
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "edits.base_version_mismatch"

    current = client.get(f"/documents/{DOC}").json()["current_version"]
    undone = client.post(f"/documents/{DOC}/site/undo", json={"base_version": current})
    assert undone.status_code == 200, undone.text
    assert undone.json()["document"]["current_version"] == produced[-1]

    current = client.get(f"/documents/{DOC}").json()["current_version"]
    redone = client.post(f"/documents/{DOC}/site/redo", json={"base_version": current})
    assert redone.status_code == 200, redone.text
    assert redone.json()["document"]["current_version"] == produced[-1]

    batch = client.get(f"/documents/{DOC}/site/versions").json()["versions"][-1]["batch_id"]
    current = client.get(f"/documents/{DOC}").json()["current_version"]
    restored = client.post(f"/documents/{DOC}/site/versions/{batch}/restore", json={"base_version": current})
    assert restored.status_code == 200, restored.text
    assert restored.json()["document"]["current_version"] == produced[-1]


def test_k1_3_a_restore_may_bring_back_a_clone_the_current_site_no_longer_uses(client: TestClient) -> None:
    """Review finding K1-3. The brand a save is checked against lists the clones the catalog offers
    plus the ones the site's pages already use (``site_workspace_view.pinned_site_clones``). Here the
    catalog no longer offers clone A (replaced by B): the loader below gives exactly that, a brand
    whose clones are the ones the document it is handed uses. Restoring the version that used A
    must be checked against the site being restored, not the current one — undo to the same state
    already worked, and a restore lands exactly the site that stood."""
    site, brand = hold_site_images(garner_site(DOC), garner_brand(), make_blob_store(client.app))
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand)
    clone_a = "frag_9fa31f37a0b94447"
    clone_b = "frag_9fa31f37b0b94447"
    brand["clones"][clone_b] = {**brand["clones"][clone_a], "id": clone_b}

    def used_by(site: dict) -> set[str]:
        return {
            str(item["props"].get("fragmentId"))
            for page in site["pages"].values()
            for item in page["content"]
            if item["type"] == "ClonedSection"
        }

    retired: set[str] = set()

    def catalog(repo, blobs, document):
        # The catalog's clones (minus the retired ones) plus every clone the handed site uses.
        pinned = used_by(document["scene"]) if document.get("scene", {}).get("pages") else set()
        clones = {cid: clone for cid, clone in brand["clones"].items() if cid not in retired or cid in pinned}
        return {**brand, "clones": clones}

    client.app.state.site_brand_loader = catalog
    assert save(client, site, 0).status_code == 200  # v1 uses A, which the catalog still offers
    with_b = copy.deepcopy(site)
    for item in with_b["pages"]["/"]["content"]:
        if item["props"].get("fragmentId") == clone_a:
            item["props"]["fragmentId"] = clone_b
    assert save(client, with_b, 1).status_code == 200  # v2 replaced A with B
    retired.add(clone_a)  # and A is retired from the catalog
    versions = client.get(f"/documents/{DOC}/site/versions").json()["versions"]
    first = next(entry["batch_id"] for entry in versions if entry["version"] == 1)
    restored = client.post(f"/documents/{DOC}/site/versions/{first}/restore", json={"base_version": 2})
    assert restored.status_code == 200, restored.text
    assert clone_a in used_by(stored_site(client))
