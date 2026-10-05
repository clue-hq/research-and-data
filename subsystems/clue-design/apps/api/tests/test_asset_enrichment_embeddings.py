"""Hybrid asset search, ingestion side: enrichment stores a CLIP vector per asset, never fails an
asset over it, and refuses descriptions that say nothing (the 5 junk Conduit rows, 2026-10-05).

Offline: an in-memory store stands in for EnrichmentStore and the encoder is stubbed, so these run
without a database or the model. The real encoder is covered by test_asset_embeddings.py.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from asset_analysis_fixture import analysis
from lumen_api import asset_embeddings
from lumen_ingestion import asset_enrichment as enrich
from lumen_ingestion.describe import DescribeResult

SPACE = "openai/clip-vit-base-patch32"


def _png(color=(30, 90, 200), size=(80, 60)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class MemoryStore:
    """Just enough of EnrichmentStore for enrich_assets and embed_preview."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.vectors: dict[str, tuple[str, list[float]]] = {}
        self.upserts = 0

    def prepare(self, asset_id, inputs, job_id):
        row = self.rows.setdefault(asset_id, {"status": "stale", "analysis_input": inputs,
                                              "input_fingerprint": hashlib.sha256(repr(inputs).encode()).hexdigest()})
        return row

    def begin(self, asset_id, fingerprint, token, job_id):
        return True

    def finish(self, asset_id, token, **result):
        row = self.rows[asset_id]
        row["status"] = result.get("status", "ready")
        row.update({k: v for k, v in result.items() if k != "status"})
        return True

    def read(self, asset_id):
        return self.rows.get(asset_id, {})

    def embedding_digest(self, asset_id, model):
        found = self.vectors.get(asset_id)
        return found[0] if found and model == SPACE else None

    def upsert_embedding(self, asset_id, model, digest, vector):
        assert model == SPACE and len(vector) == 512
        self.vectors[asset_id] = (digest, vector)
        self.upserts += 1


class Describer:
    active = True
    model = "test-describer"

    def __init__(self, descriptions=None):
        self.descriptions = descriptions or {}
        self.calls = 0

    def describe(self, items):
        self.calls += 1
        out = []
        for item in items:
            a = analysis("A title", item.source_occurrences)
            text = self.descriptions.get(item.asset_id)
            if text is not None:
                a = {**a, "description": text}
            out.append(DescribeResult(item.asset_id, "A title", a["description"], "Usage", [], analysis=a))
        return out


@pytest.fixture
def stub_encoder(monkeypatch):
    calls = []

    def fake_embed(data: bytes):
        calls.append(hashlib.sha256(data).hexdigest())
        v = np.zeros(512, np.float32)
        v[len(calls) % 512] = 1.0
        return v

    monkeypatch.setattr(asset_embeddings, "model_info",
                        lambda: asset_embeddings.ModelInfo(space=SPACE, dim=512, directory=None))
    monkeypatch.setattr(asset_embeddings, "embed_image_bytes", fake_embed)
    return calls


def _run(store, describer, assets: dict[str, bytes]):
    targets = {aid: {"kind": "image", "source_occurrences": []} for aid in assets}
    return enrich.enrich_assets(
        targets, workspace_id="ws_test", describer=describer,
        resolve_bytes=lambda aid: (assets[aid], "image/png"),
        reporter=lambda *_: None, store=store, concurrency=2,
    )


# --- embed_preview ------------------------------------------------------------------------------

def test_every_described_asset_gets_a_vector_from_its_preview(stub_encoder):
    store = MemoryStore()
    summary = _run(store, Describer(), {"a1": _png(), "a2": _png((200, 40, 40))})
    assert summary["ready"] == 2
    assert set(store.vectors) == {"a1", "a2"}
    # The vector is made from the analysis preview (the bytes the describer saw), not the original.
    preview_digest = store.rows["a1"]["analysis_input"]["preview"]["digest"]
    assert store.vectors["a1"][0] == preview_digest


def test_an_unchanged_preview_is_not_embedded_again(stub_encoder):
    store = MemoryStore()
    assets = {"a1": _png()}
    _run(store, Describer(), assets)
    _run(store, Describer(), assets)
    assert store.upserts == 1 and len(stub_encoder) == 1


def test_a_changed_preview_is_embedded_again(stub_encoder):
    store = MemoryStore()
    _run(store, Describer(), {"a1": _png()})
    _run(store, Describer(), {"a1": _png((0, 200, 0))})
    assert store.upserts == 2


def test_an_unavailable_model_skips_the_vector_and_keeps_the_asset(monkeypatch):
    def unavailable():
        raise asset_embeddings.EmbeddingUnavailable("no embedding model directory is configured")

    monkeypatch.setattr(asset_embeddings, "model_info", unavailable)
    store = MemoryStore()
    summary = _run(store, Describer(), {"a1": _png()})
    assert summary["ready"] == 1 and store.vectors == {}


def test_a_failing_encoder_never_fails_the_asset(monkeypatch):
    monkeypatch.setattr(asset_embeddings, "model_info",
                        lambda: asset_embeddings.ModelInfo(space=SPACE, dim=512, directory=None))

    def boom(_):
        raise RuntimeError("onnxruntime exploded")

    monkeypatch.setattr(asset_embeddings, "embed_image_bytes", boom)
    store = MemoryStore()
    summary = _run(store, Describer(), {"a1": _png()})
    assert summary["ready"] == 1 and store.vectors == {}


def test_embed_preview_reports_what_happened(stub_encoder):
    store = MemoryStore()
    preview = base64.b64encode(_png()).decode()
    digest = hashlib.sha256(base64.b64decode(preview)).hexdigest()
    assert enrich.embed_preview(store, "x", preview, digest) == "embedded"
    assert enrich.embed_preview(store, "x", preview, digest) == "current"
    assert enrich.embed_preview(object(), "x", preview, digest) == "skipped"  # store without vectors
    assert enrich.embed_preview(store, "x", None, None) == "skipped"


def test_a_lease_fence_still_stops_the_worker(stub_encoder):
    from clue_design.errors import DesignJobFencedError

    class FencedStore(MemoryStore):
        def embedding_digest(self, asset_id, model):
            raise DesignJobFencedError("job", 1, 2)

    preview = base64.b64encode(_png()).decode()
    with pytest.raises(DesignJobFencedError):
        enrich.embed_preview(FencedStore(), "x", preview, hashlib.sha256(b"x").hexdigest())


# --- junk descriptions --------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Describe each image below.", "N/A", "เหลว", "portrait-or",
                                  "asset_ing_761b0b47f1b7c604", "", "  none. "])
def test_the_five_real_junk_descriptions_and_friends_are_refused(text):
    assert enrich.junk_description_reason({"description": text, "title": "x"}, "asset_ing_761b0b47f1b7c604")


@pytest.mark.parametrize("text,title", [
    ("A square ad on a soft blurred pastel background with a dark wordmark top left.", "Pastel ad"),
    ("Lowercase conduit wordmark in dark ink on a transparent ground.", "Conduit wordmark"),
    ("Blue arrow icon", "Arrow"),  # terse but real: three words is enough
])
def test_real_descriptions_pass(text, title):
    assert enrich.junk_description_reason({"description": text, "title": title}, "asset_ing_1") is None


def test_a_junk_answer_is_retried_then_recorded_as_failed_not_stored(stub_encoder):
    store = MemoryStore()
    describer = Describer({"a1": "Describe each image below."})
    summary = _run(store, describer, {"a1": _png()})
    assert summary["failed"] == 1 and summary["ready"] == 0
    assert describer.calls == 2  # the existing one validation retry
    assert store.rows["a1"]["diagnostic"]["code"] == "analysis_failed"
    assert "echoes the instruction" in store.rows["a1"]["diagnostic"]["message"]
    assert "a1" in store.vectors  # the image itself is still searchable by look
