"""The governed site writes (Wave 2 Contract 2): an agent turn persists as ONE undoable write
through design_write_site, the same tool a manual save uses (REQ-20 parity)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.site_doc_validate import SiteDocumentInvalid
from site_kit_support import born_site, ensure_site_kit_dist, garner_brand, garner_site, hold_site_images, install_site_inputs, store_site


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def test_an_agent_turn_persists_as_one_undoable_write(client: TestClient, workspace_id: str) -> None:
    site, brand = hold_site_images(garner_site("site_tool_agent"), garner_brand(), make_blob_store(client.app))
    store_site(born_site("site_tool_agent"))
    install_site_inputs(client.app, brand)
    result = client.app.state.design_tools.invoke(
        "design_write_site",
        {"document_id": "site_tool_agent", "site": site, "intent": "Site turn", "actor_kind": "agent", "source": "agent", "expected_base_version": 0},
        workspace_id=workspace_id,
        actor="agent",
    )
    assert result.references["current_version"] == 1
    repo = HybridRepository()
    document = repo.require_document("site_tool_agent")
    assert document["scene"]["pages"] == site["pages"]
    assert len(document["undo_stack"]) == 1 and document["redo_stack"] == []
    (envelope,) = repo.list_envelopes("site_tool_agent")
    assert envelope["operations"] == [{"kind": "replace_site", "site": document["scene"]}]
    assert envelope["inverse_operations"][0]["kind"] == "replace_site"
    assert envelope["inverse_operations"][0]["site"]["shell"] is None
    assert envelope["actor"]["kind"] == "agent"


def test_an_invalid_site_is_refused_and_nothing_is_written(client: TestClient, workspace_id: str) -> None:
    store_site(born_site("site_tool_bad"))
    install_site_inputs(client.app, garner_brand())
    broken = garner_site("site_tool_bad")
    broken["pages"]["/analysis"]["content"][0]["props"]["surface"] = "green"
    with pytest.raises(SiteDocumentInvalid) as refused:
        client.app.state.design_tools.invoke(
            "design_write_site",
            {"document_id": "site_tool_bad", "site": broken, "actor_kind": "agent", "source": "agent", "expected_base_version": 0},
            workspace_id=workspace_id,
            actor="agent",
        )
    assert any("surface" in error for error in refused.value.errors)
    assert HybridRepository().require_document("site_tool_bad")["current_version"] == 0
