"""Business-logic scenarios for the Puck site document in the design API (Wave 2 Lane A, Task V1).

The unit suites beside this one (test_site_write_routes, test_site_tools, test_site_validation,
test_site_document_kind) pin each piece. This file drives the real composed app across whole
flows instead: ``create_app`` over the Postgres test database, the test's own blob storage, the
real site-kit validator bundle and the real HTTP routes, with the state the editor would read back
(``GET /documents/{id}``: version, both stacks, the stored site) checked after every step.

The brand and the agent-section store are Lane B's seams; ``install_site_inputs`` stands in for
them exactly as the unit suites do. Nothing else is stubbed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from py_lumen_config import settings
from sqlalchemy import text

from clue_design.storage import SOURCE_KEY_ASSET
from conftest import make_blob_store, make_client
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.main import create_app
from lumen_api.site_doc_inputs import brand_loader_not_composed
from site_kit_support import (
    FIXTURES,
    born_site,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    hold_site_images,
    install_site_inputs,
    png,
    store_site,
)
from test_agent_run_write_lock import create_document as create_scene_document
from test_agent_run_write_lock import finish_run, start_leg_run
from test_site_validation import quote_module

DOC = "site_scenario"
QUOTE_ITEM = {"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": "Fewer surprises."}}


@pytest.fixture(autouse=True)
def _no_embedded_fleet_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # The lock scenario seeds a running run row directly; nothing here offers fleet work, and a
    # worker draining the shared queue would only add another writer nobody asked for.
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


@pytest.fixture()
def garner(client: TestClient) -> tuple[dict, dict]:
    """Garner's site and brand with every image swapped for bytes THIS workspace holds."""
    return hold_site_images(garner_site(DOC), garner_brand(), make_blob_store(client.app))


# --- small local helpers ---------------------------------------------------------------------


def with_heading(site: dict, heading: str) -> dict:
    """Garner's site with one heading edited: the CtaBand "cta" on /analysis."""
    changed = copy.deepcopy(site)
    changed["pages"]["/analysis"]["content"][3]["props"]["heading"] = heading
    return changed


def heading_of(site: dict) -> str:
    return site["pages"]["/analysis"]["content"][3]["props"]["heading"]


def with_quote(site: dict, digest: str) -> dict:
    """The site with the agent's QuoteBand appended to the home page and pinned."""
    changed = copy.deepcopy(site)
    changed["agent_sections"] = {"QuoteBand": digest}
    changed["pages"]["/"]["content"].append(copy.deepcopy(QUOTE_ITEM))
    return changed


def read_document(client: TestClient, doc: str = DOC) -> dict:
    response = client.get(f"/documents/{doc}")
    assert response.status_code == 200, response.text
    return response.json()


def depths(body: dict) -> tuple[int, int]:
    # Strict on purpose: a site reads its stacks as arrays even before its first write (K4), so a
    # null stack here fails loudly rather than counting as empty.
    return len(body["undo_stack"]), len(body["redo_stack"])


def expect_state(client: TestClient, version: int, undo: int, redo: int, scene: dict, doc: str = DOC) -> dict:
    """Assert the whole stored state (the scene deep-equal) and return the document body."""
    body = read_document(client, doc)
    assert (body["current_version"], *depths(body)) == (version, undo, redo)
    assert body["scene"] == scene
    return body


def put_site(client: TestClient, site: Any, base: int, doc: str = DOC):
    return client.put(f"/documents/{doc}/site", json={"site": site, "base_version": base})


def undo(client: TestClient, base: int, doc: str = DOC):
    return client.post(f"/documents/{doc}/site/undo", json={"base_version": base})


def redo(client: TestClient, base: int, doc: str = DOC):
    return client.post(f"/documents/{doc}/site/redo", json={"base_version": base})


def restore(client: TestClient, batch_id: str, base: int, doc: str = DOC):
    return client.post(f"/documents/{doc}/site/versions/{batch_id}/restore", json={"base_version": base})


def versions(client: TestClient, doc: str = DOC, **params: Any):
    return client.get(f"/documents/{doc}/site/versions", params=params)


def brand_read(client: TestClient, doc: str = DOC):
    return client.get(f"/documents/{doc}/site/brand")


def agent_write(client: TestClient, workspace_id: str, site: dict, base: int, doc: str = DOC, intent: str = "Site turn"):
    """A site turn's persist (Lane B5): the governed tool, as the agent."""
    return client.app.state.design_tools.invoke(
        "design_write_site",
        {"document_id": doc, "site": site, "intent": intent, "actor_kind": "agent", "source": "agent", "expected_base_version": base},
        workspace_id=workspace_id,
        actor="agent",
    )


def expect_ok(response, version: int, doc: str = DOC, **extra: Any) -> dict:
    """A write's 200 body: exactly the document ref (plus the moved batch for undo/redo)."""
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"schema_version": 1, "document": {"id": doc, "current_version": version, "doc_kind": "site"}, **extra}
    return body


def expect_refused(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code, detail
    return detail


def stack_tops(client: TestClient, doc: str = DOC) -> tuple[list[str], list[str]]:
    body = read_document(client, doc)
    return list(body["undo_stack"]), list(body["redo_stack"])


# --- 1 + 9. The whole editing session -------------------------------------------------------------


def editing_session(client: TestClient, workspace_id: str, site: dict, brand: dict) -> list[tuple[str, int, dict]]:
    """Scenario 1, step by step. Returns each successful write as (kind, the version its response
    named, the document as GET reads it right after) for scenario 9."""
    module = quote_module()
    install_site_inputs(client.app, brand, sections=[module])
    log: list[tuple[str, int, dict]] = []

    def record(kind: str, version: int) -> None:
        log.append((kind, version, read_document(client)))

    born = expect_state(client, 0, 0, 0, born_site(DOC))["scene"]

    # v1: the agent's turn adds a QuoteBand agent section and its pin.
    s1 = with_quote(site, module.digest)
    result = agent_write(client, workspace_id, s1, base=0)
    assert (result.references["document_id"], result.references["current_version"], result.references["status"]) == (DOC, 1, "draft")
    (b1,), _ = stack_tops(client)
    expect_state(client, 1, 1, 0, s1)
    record("write", result.references["current_version"])

    # v2: a manual save edits one heading (the agent section is kept untouched, so it is allowed).
    s2 = with_heading(s1, "Your provider analysis, free")
    expect_ok(put_site(client, s2, 1), 2)
    undo_stack, redo_stack = stack_tops(client)
    assert undo_stack[0] == b1 and len(undo_stack) == 2 and redo_stack == []
    b2 = undo_stack[1]
    expect_state(client, 2, 2, 0, s2)
    record("write", 2)

    # A second tab still on v1 saves: refused, nothing changes.
    stale = expect_refused(put_site(client, with_heading(s1, "From the stale tab"), 1), 409, "edits.base_version_mismatch")
    assert stale["current_version"] == 2
    expect_state(client, 2, 2, 0, s2)

    # undo -> the agent's v1 site; undo -> the born site; a third undo has nothing left.
    expect_ok(undo(client, 2), 3, undone_batch_id=b2)
    assert stack_tops(client) == ([b1], [b2])
    expect_state(client, 3, 1, 1, s1)
    record("undo", 3)
    expect_ok(undo(client, 3), 4, undone_batch_id=b1)
    assert stack_tops(client) == ([], [b2, b1])
    expect_state(client, 4, 0, 2, born)
    record("undo", 4)
    expect_refused(undo(client, 4), 409, "undo.empty")
    expect_state(client, 4, 0, 2, born)

    # redo -> v1 again (agent section and pin back).
    expect_ok(redo(client, 4), 5, redone_batch_id=b1)
    assert stack_tops(client) == ([b1], [b2])
    expect_state(client, 5, 1, 1, s1)
    record("redo", 5)

    # A new manual save — the quote and its pin removed by hand — clears the redo stack.
    s3 = with_heading(site, "Request your analysis")
    expect_ok(put_site(client, s3, 5), 6)
    undo_stack, redo_stack = stack_tops(client)
    assert undo_stack[0] == b1 and len(undo_stack) == 2 and redo_stack == []
    b6 = undo_stack[1]
    expect_state(client, 6, 2, 0, s3)
    record("write", 6)
    expect_refused(redo(client, 6), 409, "redo.empty")
    expect_state(client, 6, 2, 0, s3)

    # The history: newest first, one entry per envelope, who wrote each one, and what it was.
    listed = versions(client)
    assert listed.status_code == 200, listed.text
    entries = listed.json()["versions"]
    assert listed.json()["schema_version"] == 1
    assert [entry["version"] for entry in entries] == [6, 5, 4, 3, 2, 1]
    assert [entry["actor_kind"] for entry in entries] == ["editor", "system", "system", "system", "editor", "agent"]
    assert [entry["intent"] for entry in entries] == [
        "Manual edit", "redo:Site turn", "undo:Site turn", "undo:Manual edit", "Manual edit", "Site turn",
    ]
    assert entries[0]["batch_id"] == b6 and entries[4]["batch_id"] == b2 and entries[5]["batch_id"] == b1
    assert len({entry["batch_id"] for entry in entries}) == 6
    assert all(set(entry) == {"batch_id", "version", "actor_kind", "intent", "created_at"} for entry in entries)
    assert [entry["created_at"] for entry in entries] == sorted((entry["created_at"] for entry in entries), reverse=True)
    limited = versions(client, limit=2)
    assert limited.status_code == 200 and limited.json()["versions"] == entries[:2]

    # Restore v1: the agent's section and its pin come back exactly, as one undoable save.
    expect_ok(restore(client, b1, 6), 7)
    restored = expect_state(client, 7, 3, 0, s1)
    assert restored["scene"]["agent_sections"] == {"QuoteBand": module.digest}
    assert restored["scene"]["pages"]["/"]["content"][-1] == QUOTE_ITEM
    b7 = restored["undo_stack"][-1]
    record("write", 7)

    # Undo the restore: back to the site that stood before it.
    expect_ok(undo(client, 7), 8, undone_batch_id=b7)
    assert stack_tops(client) == ([b1, b6], [b7])
    expect_state(client, 8, 2, 1, s3)
    record("undo", 8)

    final = versions(client).json()["versions"]
    assert [(entry["version"], entry["actor_kind"], entry["intent"]) for entry in final[:2]] == [
        (8, "system", f"undo:restore:{b1}"),
        (7, "editor", f"restore:{b1}"),
    ]
    assert final[2:] == entries
    return log


def test_the_whole_editing_session(client: TestClient, workspace_id: str, garner: tuple[dict, dict]) -> None:
    site, brand = garner
    store_site(born_site(DOC))
    editing_session(client, workspace_id, site, brand)


def test_the_document_read_the_editor_depends_on(client: TestClient, workspace_id: str, garner: tuple[dict, dict]) -> None:
    """Lane C's K4 (the read) and K7 (the app counts one undo step per save and re-reads the true
    depths): after the whole session the read is a site's, and at every step it agreed with what
    the step's response said and with the counting model."""
    site, brand = garner
    account = client.post("/web/accounts", json={"name": "Syracuse City School District", "domain": "syracusecityschools.com"})
    assert account.status_code == 200, account.text
    account_id = account.json()["account_id"]
    store_site(born_site(DOC), account_id=account_id)
    born = read_document(client)

    log = editing_session(client, workspace_id, site, brand)

    undo_depth, redo_depth = 0, 0
    for kind, response_version, document in log:
        if kind == "write":
            undo_depth, redo_depth = min(undo_depth + 1, 50), 0
        elif kind == "undo":
            undo_depth, redo_depth = undo_depth - 1, redo_depth + 1
        else:
            undo_depth, redo_depth = undo_depth + 1, redo_depth - 1
        assert document["current_version"] == response_version
        assert (len(document["undo_stack"]), len(document["redo_stack"])) == (undo_depth, redo_depth), kind
        assert document["doc_kind"] == "site" and "render_context" not in document
        assert document["account_id"] == account_id

    final = read_document(client)
    assert final["doc_kind"] == "site"
    assert "render_context" not in final and "fragment_meta" not in final
    assert final["account_id"] == account_id
    assert final["status"] == "draft"
    assert (final["current_version"], len(final["undo_stack"]), len(final["redo_stack"])) == (8, 2, 1)
    agent_run = client.get(f"/documents/{DOC}/agent-run")
    assert agent_run.status_code == 200
    assert agent_run.json() == {"schema_version": 1, "document_id": DOC, "active": False, "run_id": None, "current_version": 8}

    # The read before any write — what the editor loads for a site the agent has not written yet.
    # K4 (Lane C plan): `{…, current_version, undo_stack: [], redo_stack: []}`; the editor's
    # LoadedSiteWireSchema (site-wire.ts) takes an array or no key at all, never null.
    assert (born["doc_kind"], born["current_version"], born["account_id"]) == ("site", 0, account_id)
    assert "render_context" not in born
    assert (born["undo_stack"], born["redo_stack"]) == ([], [])

    # A web document's read is unchanged: never written, its stacks still read null (the web
    # editor's reader tolerates that; only the site read is normalised).
    web = client.post("/documents", json={"doc_kind": "web", "title": "A web page"})
    assert web.status_code == 200, web.text
    web_read = read_document(client, web.json()["document"]["id"])
    assert web_read["doc_kind"] == "web" and web_read["current_version"] == 0
    assert web_read["undo_stack"] is None and web_read["redo_stack"] is None


# --- 2. The 50-step cap ---------------------------------------------------------------------------


def test_the_undo_stack_holds_the_last_fifty_saves(client: TestClient, garner: tuple[dict, dict]) -> None:
    site, brand = garner
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand)
    snapshots = [born_site(DOC)] + [with_heading(site, f"Save {k}: your provider analysis") for k in range(1, 56)]

    for k in range(1, 56):
        expect_ok(put_site(client, snapshots[k], k - 1), k)
        expect_state(client, k, min(k, 50), 0, snapshots[k])
    assert len(read_document(client)["undo_stack"]) == 50

    for i in range(1, 51):
        undo_stack, _ = stack_tops(client)
        expect_ok(undo(client, 55 + i - 1), 55 + i, undone_batch_id=undo_stack[-1])
        expect_state(client, 55 + i, 50 - i, i, snapshots[55 - i])

    expect_refused(undo(client, 105), 409, "undo.empty")
    final = expect_state(client, 105, 0, 50, snapshots[5])
    assert heading_of(final["scene"]) == "Save 5: your provider analysis"


# --- 3. Two writers race ----------------------------------------------------------------------------


def test_two_writers_from_the_same_version_one_wins(client: TestClient, garner: tuple[dict, dict]) -> None:
    site, brand = garner
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand)
    second = make_client(client.app)
    barrier = threading.Barrier(2)
    headings = ["Heading from tab A", "Heading from tab B"]

    def write(tab: TestClient, heading: str):
        barrier.wait(timeout=30)
        return put_site(tab, with_heading(site, heading), 0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, tab, heading) for tab, heading in zip((client, second), headings)]
        responses = [future.result(timeout=120) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409], [r.text for r in responses]
    winner = next(index for index, response in enumerate(responses) if response.status_code == 200)
    expect_ok(responses[winner], 1)
    loser = expect_refused(responses[1 - winner], 409, "edits.base_version_mismatch")
    assert loser["current_version"] == 1
    expect_state(client, 1, 1, 0, with_heading(site, headings[winner]))
    entries = versions(client).json()["versions"]
    assert [(entry["version"], entry["actor_kind"], entry["intent"]) for entry in entries] == [(1, "editor", "Manual edit")]


# --- 4. Tenancy ----------------------------------------------------------------------------------


def test_an_image_only_another_workspace_holds_is_refused_until_this_one_holds_it(
    client: TestClient, workspace_id: str, garner: tuple[dict, dict]
) -> None:
    site, brand = garner
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand)
    born = born_site(DOC)

    # A real second tenant on the same backend: its own workspace row, artifact row and blob key.
    other = DesignBlobStore(client.app.state.storage, f"ws_test_other_{uuid.uuid4().hex[:12]}")
    assert other.workspace_id != workspace_id
    data = png((7, 77, 177))
    other.register(data, media_type="image/png", source_key=SOURCE_KEY_ASSET)
    digest = hashlib.sha256(data).hexdigest()
    image = f"/asset-store/{digest}"
    # The public byte route serves any tenant's blob by ruling (R-D4-7) — which is exactly why the
    # save must check custody: the bytes are reachable, but they are not this workspace's.
    served = client.get(image)
    assert served.status_code == 200 and served.content == data

    foreign = copy.deepcopy(site)
    foreign["pages"]["/analysis"]["content"][0]["props"]["image"] = image  # FeatureSplit "what"
    refused = expect_refused(put_site(client, foreign, 0), 422, "site.invalid")
    # Custody names it, and the kit's validator — which is handed only the images this workspace
    # holds — refuses the same image where it sits. Both errors name exactly that image.
    assert refused["errors"] == [
        f"image {image} is not stored in this workspace; use one of the brand's assets or an image generated for this site",
        f'pages/analysis.content.0(what).image: image "{image}" is not in the brand\'s assets; pick a file from brand/brand.md',
    ]
    expect_state(client, 0, 0, 0, born)

    make_blob_store(client.app).register(data, media_type="image/png", source_key=SOURCE_KEY_ASSET)
    expect_ok(put_site(client, foreign, 0), 1)
    expect_state(client, 1, 1, 0, foreign)


# --- 5. The agent-run lock, whole lifecycle -------------------------------------------------------


def test_the_agent_run_lock_over_its_whole_lifecycle(client: TestClient, workspace_id: str, garner: tuple[dict, dict]) -> None:
    site, brand = garner
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand)
    first, second = with_heading(site, "First save"), with_heading(site, "Second save")
    expect_ok(put_site(client, first, 0), 1)
    expect_ok(put_site(client, second, 1), 2)
    second_batch = stack_tops(client)[0][-1]
    expect_ok(undo(client, 2), 3, undone_batch_id=second_batch)
    # Both stacks non-empty, so undo/redo below can only refuse because of the lock.
    held = expect_state(client, 3, 1, 1, first)
    b1 = held["undo_stack"][0]
    history = versions(client).json()["versions"]

    repo = HybridRepository()
    run_id = start_leg_run(repo, DOC)
    try:
        for response in (
            put_site(client, with_heading(site, "A manual edit mid-run"), 3),
            undo(client, 3),
            redo(client, 3),
            restore(client, b1, 3),
        ):
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == {"code": "document.agent_run_active", "run_id": run_id}
            expect_state(client, 3, 1, 1, first)

        # The reads the editor needs stay open while the agent works.
        assert read_document(client)["current_version"] == 3
        listed = versions(client)
        assert listed.status_code == 200 and listed.json()["versions"] == history
        served_brand = brand_read(client)
        assert served_brand.status_code == 200 and served_brand.json() == {"schema_version": 1, "brand": brand}
        busy = client.get(f"/documents/{DOC}/agent-run").json()
        assert (busy["active"], busy["run_id"], busy["current_version"]) == (True, run_id, 3)

        # The agent's own persist is not a manual write: it lands, as one undoable step.
        turn = with_heading(site, "Written by the agent mid-run")
        result = agent_write(client, workspace_id, turn, base=3)
        assert result.references["current_version"] == 4
        expect_state(client, 4, 2, 0, turn)
        assert versions(client).json()["versions"][0]["actor_kind"] == "agent"
    finally:
        finish_run(repo, run_id)

    after = with_heading(site, "A manual edit after the run")
    expect_ok(put_site(client, after, 4), 5)
    expect_state(client, 5, 3, 0, after)
    assert client.get(f"/documents/{DOC}/agent-run").json()["active"] is False


# --- 6. The refusal matrix ---------------------------------------------------------------------


def site_routes(client: TestClient, doc: str, site: dict, base: int, batch_id: str = "batch_any") -> dict[str, Any]:
    """Every site route on ``doc``, keyed by name."""
    return {
        "put": put_site(client, site, base, doc=doc),
        "undo": undo(client, base, doc=doc),
        "redo": redo(client, base, doc=doc),
        "versions": versions(client, doc=doc),
        "restore": restore(client, batch_id, base, doc=doc),
        "brand": brand_read(client, doc=doc),
    }


def stored(client: TestClient, doc: str) -> tuple[int, list, list, dict]:
    body = read_document(client, doc)
    return body["current_version"], body["undo_stack"], body["redo_stack"], body["scene"]


def test_the_refusal_matrix(client: TestClient, garner: tuple[dict, dict]) -> None:
    site, brand = garner
    install_site_inputs(client.app, brand)

    # A web document and a scene document are not sites: every site route is a 409.
    web = client.post("/documents", json={"doc_kind": "web", "title": "A web page"})
    assert web.status_code == 200, web.text
    scene = create_scene_document(client)
    for other in (web.json()["document"]["id"], scene["id"]):
        before = stored(client, other)
        for name, response in site_routes(client, other, {**site, "id": other}, before[0]).items():
            assert response.status_code == 409, (other, name, response.text)
            assert response.json()["detail"]["code"] == "document.kind_unsupported", (other, name)
        assert stored(client, other) == before

    # A document that does not exist: every site route is a 404.
    for name, response in site_routes(client, "doc_nowhere", {**site, "id": "doc_nowhere"}, 0).items():
        assert response.status_code == 404, (name, response.text)
        assert response.json()["detail"]["code"] == "document.not_found", name

    # A finalized site refuses every write. No route finalizes a site (POST /finalize is the
    # scene-template path and refuses a site, shown here), so the document's status column is set to
    # 'finalized' directly — the value a scene finalize leaves there, and the column
    # require_draft_document reads first.
    store_site(born_site(DOC))
    expect_ok(put_site(client, with_heading(site, "First save"), 0), 1)
    expect_ok(put_site(client, with_heading(site, "Second save"), 1), 2)
    second_batch = stack_tops(client)[0][-1]
    expect_ok(undo(client, 2), 3, undone_batch_id=second_batch)
    b1 = read_document(client)["undo_stack"][0]
    finalize = client.post(f"/documents/{DOC}/finalize", json={})
    expect_refused(finalize, 409, "document.kind_unsupported")
    repo = HybridRepository()
    repo._bridge._run(
        lambda conn: conn.execute(
            text("UPDATE design_document SET status = 'finalized' WHERE id = :d AND workspace_id = :w"),
            {"d": DOC, "w": repo.workspace_id},
        )
    )
    before = stored(client, DOC)
    assert read_document(client)["status"] == "finalized"
    for response in (put_site(client, with_heading(site, "After finalize"), 3), undo(client, 3), redo(client, 3), restore(client, b1, 3)):
        expect_refused(response, 409, "document.finalized")
        assert stored(client, DOC) == before
    assert versions(client).status_code == 200 and brand_read(client).status_code == 200

    # The site's own shape, refused by name before anything runs.
    store_site(born_site("site_shape"))
    shaped = {**site, "id": "site_shape"}
    born = born_site("site_shape")
    cases = [
        ({**shaped, "id": DOC}, ["site.id: must be this document's id 'site_shape'"]),
        ({**shaped, "extra": 1}, ["site.extra: not a site field (the fields are id, title, theme, pages, shell, agent_sections)"]),
        (
            {**shaped, "pages": {**shaped["pages"], "/Pricing": {"root": {"props": {}}, "content": []}}},
            ["site.pages['/Pricing']: a route is / or /<name> (lowercase letters, digits, dashes)"],
        ),
    ]
    for bad, errors in cases:
        refused = expect_refused(put_site(client, bad, 0, doc="site_shape"), 422, "site.invalid")
        assert refused["errors"] == errors
        expect_state(client, 0, 0, 0, born, doc="site_shape")

    for limit in (0, 201):
        response = versions(client, doc="site_shape", limit=limit)
        assert response.status_code == 422, (limit, response.text)
        assert [item["loc"] for item in response.json()["detail"]] == [["query", "limit"]]


# --- 7. What the validator and the inputs refuse ------------------------------------------------


def test_what_the_validator_and_the_inputs_refuse(
    client: TestClient, workspace_id: str, garner: tuple[dict, dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site, brand = garner
    module = quote_module()
    store_site(born_site(DOC))
    install_site_inputs(client.app, brand, sections=[module])
    born = born_site(DOC)

    # The validator bundle is not where the API looks: a typed 503, nothing written.
    empty = tmp_path / "no-site-kit"
    empty.mkdir()
    with monkeypatch.context() as patch:
        patch.setenv("LUMEN_SITE_KIT_DIST", str(empty))
        expect_refused(put_site(client, site, 0), 503, "site_validator.unavailable")
    expect_state(client, 0, 0, 0, born)

    # No brand builder composed (the shipped default until Lane B2): the save and the brand read 503.
    composed = client.app.state.site_brand_loader
    client.app.state.site_brand_loader = brand_loader_not_composed
    expect_refused(put_site(client, site, 0), 503, "site_inputs.unavailable")
    expect_refused(brand_read(client), 503, "site_inputs.unavailable")
    client.app.state.site_brand_loader = composed
    expect_state(client, 0, 0, 0, born)

    # A manual save cannot add an agent section, even one the store holds.
    refused = expect_refused(put_site(client, with_quote(site, module.digest), 0), 422, "site.invalid")
    assert refused["errors"] == ["agent_sections.QuoteBand: a manual save cannot add or change an agent section"]
    expect_state(client, 0, 0, 0, born)

    # The agent adds it (v1); manual saves now keep it, and the checks below run against it.
    s1 = with_quote(site, module.digest)
    assert agent_write(client, workspace_id, s1, base=0).references["current_version"] == 1
    expect_state(client, 1, 1, 0, s1)

    # Its props break its STORED schema: refused, naming that section.
    broken = copy.deepcopy(s1)
    broken["pages"]["/"]["content"][5]["props"]["surface"] = "green"
    refused = expect_refused(put_site(client, broken, 1), 422, "site.invalid")
    # Two true refusals on the one path: the section's stored schema, and the brand's surfaces.
    surface_at = "page.content.5(quote).surface: "
    stored_schema = surface_at + 'Invalid option: expected one of "page"|"card"|"muted"|"brandSubtle"|"brand"|"inverse"'
    brand_surface = surface_at + (
        '"green" is not one of this brand\'s surfaces; its surfaces are '
        "page, card, muted, brandSubtle, brand, inverse, canvas, elevated, accent (brand/brand.md, Surfaces)"
    )
    assert len(refused["errors"]) == 2 and all(e.startswith(surface_at) for e in refused["errors"]), refused["errors"]
    assert sorted(refused["errors"]) == sorted([stored_schema, brand_surface]), refused["errors"]
    expect_state(client, 1, 1, 0, s1)

    # A link to a page this site does not have.
    lost = copy.deepcopy(s1)
    lost["pages"]["/analysis"]["content"][3]["props"]["buttonHref"] = "/pricing"
    refused = expect_refused(put_site(client, lost, 1), 422, "site.invalid")
    assert refused["errors"] == [
        "pages/analysis.content.3(cta).buttonHref: links to /pricing, which is not a page of this site; "
        "its pages are /, /analysis (a new page is pages/<name>.json)"
    ]
    expect_state(client, 1, 1, 0, s1)

    # The section store no longer holds the pinned module: refused naming agent_sections.
    install_site_inputs(client.app, brand, sections=[])
    refused = expect_refused(put_site(client, with_heading(s1, "An edit after the module went"), 1), 422, "site.invalid")
    assert refused["errors"] == [f"agent_sections: agent section QuoteBand has no stored module {module.digest[:12]}"]
    expect_state(client, 1, 1, 0, s1)


# --- 8. Two realistic sites ---------------------------------------------------------------------

#: The slot kinds the conduit-atrium site fills (its clones' own kinds are not in the fixture set).
CONDUIT_SLOT_KINDS = {"headline": "text", "body": "text", "cta_href": "href"}


def conduit_site(document_id: str) -> dict:
    stored_site = json.loads((FIXTURES / "conduit-atrium.json").read_text(encoding="utf-8"))
    return {
        "id": document_id,
        "title": stored_site["pages"]["/"]["root"]["props"]["title"],
        "theme": {},
        "pages": stored_site["pages"],
        "shell": stored_site["shell"],
        "agent_sections": {},
    }


def conduit_brand(site: dict) -> dict:
    """site-kit's fixtures carry no Conduit brand (only garner's kit, fonts, assets, clones and
    measurements). Garner's BrandData supplies the SHAPE — kit, fonts, measured, kit assets — under
    the slug "conduit", and each clone the site names is stood in with exactly the slots it fills."""
    garner_data = garner_brand()
    clones: dict[str, dict] = {}
    for page in site["pages"].values():
        for item in page["content"]:
            if item["type"] != "ClonedSection":
                continue
            fragment_id, slots = item["props"]["fragmentId"], item["props"]["slots"]
            markup = "".join(
                f'<a data-lumen-slot="{key}" href="{value}">Book a demo</a>' if CONDUIT_SLOT_KINDS[key] == "href"
                else f'<p data-lumen-slot="{key}">{value}</p>'
                for key, value in slots.items()
            )
            clones[fragment_id] = {
                "id": fragment_id,
                "role": "other",
                "label": f"Conduit — {item['props']['id']}",
                "page_url": "https://www.conduit.ai/",
                "section_index": None,
                "wrapper_class": "lumen-" + fragment_id.replace("_", "-"),
                "html": f"<section>{markup}</section>",
                "css": ".x{}",
                "slots": {key: {"kind": CONDUIT_SLOT_KINDS[key], "fallback": value} for key, value in slots.items()},
            }
    kit_assets = json.loads((FIXTURES / "assets.json").read_text(encoding="utf-8"))
    return {**garner_data, "slug": "conduit", "assets": kit_assets, "clones": clones}


def round_trip(client: TestClient, doc: str, site: dict, brand: dict) -> None:
    """Born -> save -> read back deep-equal -> undo to born -> redo deep-equal."""
    install_site_inputs(client.app, brand)
    born = expect_state(client, 0, 0, 0, born_site(doc, title=site["title"]), doc=doc)["scene"]
    served_brand = brand_read(client, doc=doc)
    assert served_brand.status_code == 200 and served_brand.json()["brand"] == brand
    expect_ok(put_site(client, site, 0, doc=doc), 1, doc=doc)
    b1 = expect_state(client, 1, 1, 0, site, doc=doc)["undo_stack"][0]
    expect_ok(undo(client, 1, doc=doc), 2, doc=doc, undone_batch_id=b1)
    expect_state(client, 2, 0, 1, born, doc=doc)
    expect_ok(redo(client, 2, doc=doc), 3, doc=doc, redone_batch_id=b1)
    expect_state(client, 3, 1, 0, site, doc=doc)


def test_two_realistic_sites_round_trip(client: TestClient) -> None:
    blobs = make_blob_store(client.app)

    garner_doc = "site_garner"
    site, brand = hold_site_images(garner_site(garner_doc), garner_brand(), blobs)
    store_site(born_site(garner_doc, title=site["title"]))
    round_trip(client, garner_doc, site, brand)

    conduit_doc = "site_conduit"
    exported = conduit_site(conduit_doc)
    site, brand = hold_site_images(exported, conduit_brand(exported), blobs)
    store_site(born_site(conduit_doc, title=site["title"]))
    install_site_inputs(client.app, brand)
    # As exported by the spike, /stories' "teams" clone sends its CTA to a second destination
    # (/customers). One destination for the offer is the agent's skill, not a save check (founder
    # 2026-10-18), so the realistic site round-trips as exported.
    round_trip(client, conduit_doc, site, brand)
