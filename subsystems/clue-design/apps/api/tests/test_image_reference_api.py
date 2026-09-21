"""Real generation route/schema/transport, with external custody seams in memory."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from lumen_api import main, spend
from py_lumen_config import settings
from test_image_reference_custody import _png
from test_image_reference_custody import fake_transport as fake_transport

from clue_spend import HttpResponse, LedgerStamp


@pytest.fixture
def route_client(tmp_path, monkeypatch: pytest.MonkeyPatch, fake_transport):
    records = {}
    ledger = {}
    blobs = {}
    writes = []
    monkeypatch.setattr(settings, "image_model_api_style", "images")
    monkeypatch.setattr(settings, "lumen_asset_store_root", "")
    for asset_id, color in (("a", "red"), ("b", "blue")):
        data = _png(6, 4, color)
        digest = hashlib.sha256(data).hexdigest()
        blobs[("ws_a", digest)] = data
        records[("ws_a", asset_id)] = {
            "asset": {
                "id": asset_id,
                "kind": "raster_image",
                "status": "ready",
                "media": {"digest": {"value": digest}, "mime_type": "image/png"},
            }
        }

    class Repository:
        def __init__(self, workspace_id, **kwargs):
            self.workspace_id = workspace_id

        def require_asset_record(self, asset_id):
            return records[(self.workspace_id, asset_id)]

        def get_generation_result(self, key):
            return ledger.get((self.workspace_id, key))

    class BlobStore:
        def __init__(self, storage, workspace_id, **kwargs):
            self.workspace_id = workspace_id

        def read(self, digest):
            return blobs[(self.workspace_id, digest)]

    def ingest_asset(**kwargs):
        data = base64.b64decode(kwargs["bytes_base64"])
        record = {
            "id": kwargs["asset_id"],
            "kind": "raster_image",
            "status": "ready",
            "provenance": copy.deepcopy(kwargs["provenance"]),
            "source": kwargs["source"],
            "media": {
                "digest": {"value": hashlib.sha256(data).hexdigest()},
                "mime_type": kwargs["declared_mime_type"],
            },
        }
        return {"ok": True, "asset": {"record": record, "deduplicated": False}}

    def invoke(name, body, *, workspace_id, **kwargs):
        assert name == "design_register_generated_asset"
        writes.append(copy.deepcopy(body))
        stored = {"asset": copy.deepcopy(body["record"])}
        ledger[(workspace_id, body["generation_key"])] = stored
        records[(workspace_id, body["record"]["id"])] = stored
        return SimpleNamespace(references={"asset_id": body["record"]["id"]})

    monkeypatch.setattr(main, "HybridRepository", Repository)
    monkeypatch.setattr(main, "DesignBlobStore", BlobStore)
    monkeypatch.setattr(
        main, "DescriptionStore", lambda **kwargs: SimpleNamespace(get_many=lambda ids: {})
    )
    monkeypatch.setattr(main, "register_engine_write", lambda *args, **kwargs: None)

    calls, output = fake_transport

    class RequestTransport:
        def send(self, request):
            assert request.method == "POST"
            assert request.url == "https://provider.invalid/v1/images"
            assert request.headers["Authorization"] == "Bearer unit-test"
            calls.append((request.url, json.loads(request.body)))
            return HttpResponse(
                status=200,
                body=json.dumps({
                    "data": [{"b64_json": base64.b64encode(output).decode("ascii")}]
                }).encode("utf-8"),
            )

    # The route opens its own caller, which supersedes fake_transport's unscoped
    # fallback. Keep a real request-scoped ProviderCaller, with transport and
    # ledger custody in memory like this fixture's asset repository and blobs.
    monkeypatch.setattr(
        main,
        "_request_spend_scope",
        lambda workspace_id: spend.spend_scope(
            LedgerStamp(workspace_id=workspace_id), transport=RequestTransport()
        ),
    )
    app = main.create_app(tmp_path / "engine-cache")
    app.state.core = SimpleNamespace(ingest_asset=ingest_asset)
    app.state.design_tools = SimpleNamespace(invoke=invoke)
    # No lifespan entry: no fleet worker, database or services are started.
    client = TestClient(app, headers={"X-Workspace-Id": "ws_a"})
    yield client, fake_transport[0], ledger, writes
    client.close()


@pytest.mark.parametrize(
    "changed",
    [
        {"reference_roles": ["treatment", "source"]},
        {"reference_framing": "Place the subject on the left."},
        {"operation": "fresh_concept"},
        {"reference_asset_ids": ["b", "a"]},
    ],
)
def test_route_semantics_partition_cache_and_receipt_survives_persistence(route_client, changed):
    client, calls, ledger, writes = route_client
    payload = {
        "provider": "image-gen-v1",
        "prompt": "Campaign image",
        "width": 1080,
        "height": 1350,
        "aspect_ratio": "4:5",
        "reference_asset_ids": ["a", "b"],
        "reference_roles": ["source", "treatment"],
        "reference_framing": "Place the subject on the right.",
        "operation": "close_companion",
    }
    first = client.post("/assets/generate", json=payload)
    assert first.status_code == 200, first.text
    second = client.post("/assets/generate", json={**payload, **changed})
    assert second.status_code == 200, second.text
    assert second.json()["deduplicated"] is False
    assert len(calls) == 2
    repeat = client.post("/assets/generate", json=payload)
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["deduplicated"] is True
    assert len(calls) == 2
    assert len(ledger) == 2
    receipt = first.json()["image_request_receipt"]
    assert receipt["reference_roles"] == payload["reference_roles"]
    assert receipt["reference_framing"] == payload["reference_framing"]
    assert receipt["operation"] == payload["operation"]
    assert receipt["effective_aspect_ratio"] == "3:4"
    assert receipt["output_dimensions"] == {"width": 24, "height": 32}
    assert repeat.json()["image_request_receipt"] == receipt
    notes = writes[0]["record"]["provenance"]["notes"]
    assert any(note.startswith("image_request=") for note in notes)
    assert first.json()["asset"]["provenance"]["notes"] == notes


@pytest.mark.parametrize(
    "changed",
    [
        {"reference_roles": ["source"]},
        {"reference_roles": ["logo", "treatment"]},
        {"reference_asset_ids": ["a", "a"]},
        {"reference_asset_ids": ["", "b"]},
        {"reference_framing": "  "},
        {"source_asset_id": "a"},
    ],
)
def test_invalid_api_reference_semantics_are_rejected_before_spend(route_client, changed):
    client, calls, ledger, writes = route_client
    response = client.post(
        "/assets/generate",
        json={
            "provider": "image-gen-v1",
            "prompt": "Campaign image",
            "reference_asset_ids": ["a", "b"],
            "reference_roles": ["source", "treatment"],
            **changed,
        },
    )
    assert response.status_code == 422, response.text
    assert calls == []
    assert ledger == {}
    assert writes == []


def test_reference_custody_still_requires_request_workspace(route_client):
    client, calls, _, writes = route_client
    response = client.post(
        "/assets/generate",
        headers={"X-Workspace-Id": "ws_other"},
        json={
            "provider": "image-gen-v1",
            "prompt": "Campaign image",
            "reference_asset_ids": ["a"],
            "reference_roles": ["source"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "reference.asset_not_found"
    assert calls == []
    assert writes == []


def test_generation_route_still_requires_workspace_header(route_client):
    client, calls, _, writes = route_client
    del client.headers["X-Workspace-Id"]
    response = client.post(
        "/assets/generate",
        json={
            "provider": "image-gen-v1",
            "prompt": "Campaign image",
            "reference_asset_ids": ["a"],
            "reference_roles": ["source"],
        },
    )
    assert response.status_code == 401
    assert calls == []
    assert writes == []


def test_api_edit_intent_and_source_digest_survive_cache_replay(route_client):
    client, calls, _, writes = route_client
    payload = {
        "provider": "image-gen-v1",
        "prompt": "Remove background",
        "source_asset_id": "a",
        "operation": "remove_background",
    }
    first = client.post("/assets/generate", json=payload)
    assert first.status_code == 200, first.text
    receipt = first.json()["image_request_receipt"]
    assert receipt["operation"] == "remove_background"
    assert receipt["provider_operation"] == "edit"
    assert receipt["reference_inputs"][0]["role"] == "source"
    assert writes[0]["record"]["source"]["source_asset_id"] == "a"
    repeat = client.post("/assets/generate", json=payload)
    assert repeat.json()["deduplicated"] is True
    assert repeat.json()["image_request_receipt"] == receipt
    changed = client.post("/assets/generate", json={**payload, "source_asset_id": "b"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["deduplicated"] is False
    assert (
        changed.json()["image_request_receipt"]["reference_inputs"][0]["sha256"]
        != (receipt["reference_inputs"][0]["sha256"])
    )
    assert len(calls) == 2


def test_legacy_api_cache_hit_does_not_manufacture_missing_receipt(route_client):
    client, calls, ledger, _ = route_client
    payload = {"provider": "image-gen-v1", "prompt": "New image"}
    first = client.post("/assets/generate", json=payload)
    assert first.status_code == 200, first.text
    stored = next(iter(ledger.values()))["asset"]
    stored["provenance"]["notes"] = ["legacy provider record", "image_request={broken-json"]
    repeat = client.post("/assets/generate", json=payload)
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["deduplicated"] is True
    assert "image_request_receipt" not in repeat.json()
    assert len(calls) == 1


def test_reference_semantics_are_not_silently_dropped_by_another_provider(route_client):
    client, calls, _, writes = route_client

    def must_not_generate(**kwargs):
        pytest.fail("unsupported reference semantics reached the other provider")

    client.app.state.core.generate_asset = must_not_generate
    response = client.post(
        "/assets/generate",
        json={
            "provider": "stub-image-v0",
            "prompt": "Campaign image",
            "reference_asset_ids": ["a"],
            "reference_roles": ["source"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "image_model.unsupported_reference_semantics"
    assert calls == []
    assert writes == []
