"""Hybrid `search_assets` (founder ruling 2026-10-05): keyword ranking fused with CLIP closeness.

Offline: the query encoder is stubbed with fixed vectors, so these pin the ranking contract —
exact ids first, fusion of the two lists, the kind filter on both, the keyword-only fallback that
says why, and compact results — without the model. The encoder itself is tested in
apps/api/tests/test_asset_embeddings.py.
"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from lumen_agent.tools.substrate import LumenDesignTools

from agent_fixtures import FakeCoreClient, runtime_config


def _vec(*hot):
    v = np.zeros(512, np.float32)
    for i in hot:
        v[i] = 1.0
    return (v / np.linalg.norm(v)).tolist()


LIBRARY = {
    "asset_pastel": {"record": {"id": "asset_pastel", "kind": "raster_image"},
                     "title": "Soft blurred background", "creative_type": "background",
                     "description": "A heavily blurred pastel field. Pink and blue bloom across it. More text here."},
    "asset_inbox": {"record": {"id": "asset_inbox", "kind": "raster_image"},
                    "title": "Product screenshot", "creative_type": "product_screenshot",
                    "description": "An application window listing guest conversations."},
    "asset_logo": {"record": {"id": "asset_logo", "kind": "logo"},
                   "title": "Partner logo", "creative_type": "logo",
                   "description": "A red wordmark on white."},
    "asset_nodesc": {"record": {"id": "asset_nodesc", "kind": "raster_image"}},
}
VECTORS = {"asset_pastel": _vec(0), "asset_inbox": _vec(1), "asset_logo": _vec(2), "asset_nodesc": _vec(0, 3)}


def _tools(tmp_path, monkeypatch, *, embeddings=VECTORS):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(runtime_config(tmp_path), brand_kit_assets=None, asset_library=LIBRARY,
                     asset_embeddings=embeddings)
    return LumenDesignTools(config, "test")


@pytest.fixture
def query_near(monkeypatch):
    """Make the query embed to a chosen direction."""
    from lumen_api import asset_embeddings

    state = {"vector": np.array(_vec(0), np.float32)}
    monkeypatch.setattr(asset_embeddings, "embed_query", lambda text: state["vector"])
    return state


def _search(tools, q, **kw):
    return json.loads(tools.search_assets(q, **kw))


def test_an_image_with_no_matching_words_is_found_by_its_look(tmp_path, monkeypatch, query_near):
    tools = _tools(tmp_path, monkeypatch)
    out = _search(tools, "dreamy haze")  # no keyword hit anywhere
    ids = [r["asset_id"] for r in out["results"]]
    assert out["visual_search"] == "on"
    assert ids[:2] == ["asset_pastel", "asset_nodesc"]  # closest by vector, incl. one with no description
    assert out["results"][0]["match"] == "look"


def test_agreement_between_words_and_look_ranks_first(tmp_path, monkeypatch, query_near):
    tools = _tools(tmp_path, monkeypatch)
    query_near["vector"] = np.array(_vec(1), np.float32)
    out = _search(tools, "screenshot")
    assert out["results"][0]["asset_id"] == "asset_inbox"
    assert out["results"][0]["match"] == "words and look"


def test_an_exact_id_stays_first_whatever_the_vectors_say(tmp_path, monkeypatch, query_near):
    tools = _tools(tmp_path, monkeypatch)
    out = _search(tools, "asset_logo")
    assert out["results"][0]["asset_id"] == "asset_logo" and out["results"][0]["match"] == "id"
    assert [r["asset_id"] for r in out["results"]].count("asset_logo") == 1


def test_kind_filters_the_visual_list_too(tmp_path, monkeypatch, query_near):
    tools = _tools(tmp_path, monkeypatch)
    query_near["vector"] = np.array(_vec(2), np.float32)  # closest to the logo
    out = _search(tools, "anything at all", kind="image")
    assert "asset_logo" not in [r["asset_id"] for r in out["results"]]


def test_limit_is_respected(tmp_path, monkeypatch, query_near):
    tools = _tools(tmp_path, monkeypatch)
    assert len(_search(tools, "background", limit=2)["results"]) == 2


def test_results_carry_a_one_line_description(tmp_path, monkeypatch, query_near):
    tools = _tools(tmp_path, monkeypatch)
    pastel = next(r for r in _search(tools, "blurred")["results"] if r["asset_id"] == "asset_pastel")
    assert pastel["description"] == "A heavily blurred pastel field."


def test_no_vectors_means_keyword_only_and_says_so(tmp_path, monkeypatch, query_near):
    tools = _tools(tmp_path, monkeypatch, embeddings=None)
    out = _search(tools, "screenshot")
    assert out["visual_search"] == "off: this library has no image vectors yet"
    assert [r["asset_id"] for r in out["results"]] == ["asset_inbox"]
    assert out["results"][0]["match"] == "words"


def test_an_unavailable_model_means_keyword_only_with_the_reason(tmp_path, monkeypatch):
    from lumen_api import asset_embeddings

    def unavailable(_):
        raise asset_embeddings.EmbeddingUnavailable("no embedding model directory is configured")

    monkeypatch.setattr(asset_embeddings, "embed_query", unavailable)
    tools = _tools(tmp_path, monkeypatch)
    out = _search(tools, "screenshot")
    assert out["visual_search"] == "off: no embedding model directory is configured"
    assert [r["asset_id"] for r in out["results"]] == ["asset_inbox"]


def test_keyword_only_order_is_unchanged_from_before(tmp_path, monkeypatch):
    """With visual search off, the ranking must be exactly today's rank_assets order."""
    from lumen_agent.tools.asset_catalog import rank_assets

    tools = _tools(tmp_path, monkeypatch, embeddings={})
    candidates = {aid: (e, "library") for aid, e in LIBRARY.items()}
    expected = [row[0] for row in rank_assets(candidates, "logo screenshot background", "")][:8]
    assert [r["asset_id"] for r in _search(tools, "logo screenshot background")["results"]] == expected


def test_bad_inputs_are_refused_as_before(tmp_path, monkeypatch, query_near):
    tools = _tools(tmp_path, monkeypatch)
    assert _search(tools, "  ")["status"] == "error"
    assert _search(tools, "x", limit=0)["status"] == "error"
    assert _search(tools, "x", limit=21)["status"] == "error"


def test_many_weak_word_matches_do_not_bury_the_best_look(tmp_path, monkeypatch, query_near):
    """Regression (2026-10-05): fusing the WHOLE keyword list — most assets share a word with any
    query — pushed the visually best image out of the top 5 on the real Conduit library."""
    library = dict(LIBRARY)
    vectors = dict(VECTORS)
    for i in range(60):
        aid = f"asset_conduit_{i}"
        library[aid] = {"record": {"id": aid, "kind": "raster_image"},
                        "title": f"Conduit ad {i}", "description": "A conduit ad with a card."}
        v = np.zeros(512, np.float32)
        v[0], v[4 + i] = -0.3 - i / 200, 1.0  # word matches that look nothing like the query
        vectors[aid] = (v / np.linalg.norm(v)).tolist()
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(replace(runtime_config(tmp_path), brand_kit_assets=None,
                                     asset_library=library, asset_embeddings=vectors), "test")
    out = json.loads(tools.search_assets("conduit", limit=5))
    ids = [r["asset_id"] for r in out["results"]]
    assert "asset_nodesc" in ids  # no words at all, best look (VECTORS: dims 0 and 3)
    assert out["results"][ids.index("asset_nodesc")]["match"] == "look"
