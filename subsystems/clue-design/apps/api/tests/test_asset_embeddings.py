"""Hybrid asset search — the ONNX CLIP runtime, its degradation paths and the ranking helpers.

Three groups:
- pure helpers (rank fusion, visual ranking, vector text form) — always run;
- preprocessing (CLIPImageProcessor's steps + the white composite for transparency) — always run,
  on an encoder built without a model;
- the model itself against the torch reference fixture — runs only where the model directory is
  configured (LUMEN_ASSET_EMBEDDING_MODEL_DIR), skipped elsewhere.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from clip_fixture_images import PHRASES, fixture_images
from lumen_api import asset_embeddings as emb
from py_lumen_config import settings

FIXTURE = Path(__file__).parent / "fixtures" / "clip_reference.json"
MODEL_DIR = Path(settings.lumen_asset_embedding_model_dir or "/nonexistent").expanduser()
HAS_MODEL = (MODEL_DIR / "text.onnx").is_file() and (MODEL_DIR / "image.onnx").is_file()
needs_model = pytest.mark.skipif(not HAS_MODEL, reason="no CLIP ONNX model directory configured")


@pytest.fixture(autouse=True)
def _fresh_encoders():
    emb._ENCODERS.clear()
    yield
    emb._ENCODERS.clear()


def _cos(a, b) -> float:
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


# --- pure helpers -------------------------------------------------------------------------------

def test_fusion_rewards_agreement_and_is_deterministic():
    keyword = ["a", "b", "c"]
    visual = ["c", "d", "a"]
    fused = emb.fuse_rankings(keyword, visual)
    assert fused[:2] == ["a", "c"]  # in both lists beats a first place in one
    assert set(fused) == {"a", "b", "c", "d"}
    assert emb.fuse_rankings(keyword, visual) == fused
    assert emb.fuse_rankings(["x", "y"], ["y", "x"]) == ["x", "y"]  # exact tie keeps first seen


def test_fusion_of_one_list_is_that_list_and_of_none_is_empty():
    assert emb.fuse_rankings(["a", "b"]) == ["a", "b"]
    assert emb.fuse_rankings([], []) == []


def test_visual_ranking_orders_by_closeness_and_skips_ids_without_vectors():
    q = np.array([1.0, 0.0, 0.0], np.float32)
    vecs = {"near": [0.9, 0.1, 0.0], "far": [0.0, 1.0, 0.0], "mid": [0.6, 0.6, 0.0]}
    assert emb.visual_ranking(q, vecs, ["far", "mid", "near", "no_vector"]) == ["near", "mid", "far"]
    assert emb.visual_ranking(q, vecs, ["no_vector"]) == []
    assert emb.visual_ranking(q, vecs, ["near", "mid", "far"], top=1) == ["near"]


def test_vector_text_form_round_trips():
    v = np.random.default_rng(1).normal(size=512).astype(np.float32)
    back = np.array(emb.parse_vector(emb.vector_literal(v)), np.float32)
    assert back.shape == (512,) and np.allclose(back, v, atol=1e-5)


def test_normalise_gives_unit_rows_and_survives_a_zero_row():
    out = emb.normalise(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(out[0], [0.6, 0.8]) and np.all(np.isfinite(out[1]))


# --- configuration and degradation --------------------------------------------------------------

def test_switched_off_is_a_stated_reason(monkeypatch):
    monkeypatch.setattr(settings, "lumen_asset_embeddings", False)
    with pytest.raises(emb.EmbeddingUnavailable, match="switched off"):
        emb.encoder()


def test_no_directory_configured_is_a_stated_reason(monkeypatch):
    monkeypatch.setattr(settings, "lumen_asset_embeddings", True)
    monkeypatch.setattr(settings, "lumen_asset_embedding_model_dir", "")
    with pytest.raises(emb.EmbeddingUnavailable, match="no embedding model directory"):
        emb.embed_query("anything")


def test_missing_directory_is_a_stated_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "lumen_asset_embeddings", True)
    monkeypatch.setattr(settings, "lumen_asset_embedding_model_dir", str(tmp_path / "absent"))
    with pytest.raises(emb.EmbeddingUnavailable, match="does not exist"):
        emb.model_info()


def test_incomplete_directory_names_the_missing_files(monkeypatch, tmp_path):
    (tmp_path / "model.json").write_text(json.dumps({"space": "s", "dim": 512}))
    monkeypatch.setattr(settings, "lumen_asset_embeddings", True)
    monkeypatch.setattr(settings, "lumen_asset_embedding_model_dir", str(tmp_path))
    with pytest.raises(emb.EmbeddingUnavailable, match="tokenizer.json, preprocess.json"):
        emb.encoder()


def test_unreadable_model_json_is_a_stated_reason(monkeypatch, tmp_path):
    (tmp_path / "model.json").write_text("{not json")
    monkeypatch.setattr(settings, "lumen_asset_embeddings", True)
    monkeypatch.setattr(settings, "lumen_asset_embedding_model_dir", str(tmp_path))
    with pytest.raises(emb.EmbeddingUnavailable, match="model.json is unreadable"):
        emb.model_info()


def test_load_workspace_embeddings_is_empty_when_search_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "lumen_asset_embeddings", False)
    assert emb.load_workspace_embeddings("ws_any") == {}


# --- preprocessing ------------------------------------------------------------------------------

def _bare_encoder() -> emb.ClipEncoder:
    """An encoder with CLIP's preprocessing constants and no model or tokenizer loaded."""
    enc = object.__new__(emb.ClipEncoder)
    enc.pre = {"size": 224, "crop": 224, "mean": [0.48145466, 0.4578275, 0.40821073],
               "std": [0.26862954, 0.26130258, 0.27577711], "context_length": 77}
    enc._mean = np.array(enc.pre["mean"], np.float32).reshape(3, 1, 1)
    enc._std = np.array(enc.pre["std"], np.float32).reshape(3, 1, 1)
    return enc


@pytest.mark.parametrize("size", [(224, 224), (640, 360), (360, 640), (3, 2), (2000, 50), (50, 2000)])
def test_every_shape_becomes_one_normalised_224_square(size):
    x = _bare_encoder().pixels(Image.new("RGB", size, (120, 80, 200)))
    assert x.shape == (3, 224, 224) and x.dtype == np.float32
    expected = (np.array([120, 80, 200], np.float32) / 255 - np.array(
        [0.48145466, 0.4578275, 0.40821073], np.float32)) / np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
    assert np.allclose(x[:, 112, 112], expected, atol=1e-5)


def test_crop_is_centred_with_floor_rounding_like_transformers():
    # 225 wide (no resize needed) -> one spare column. transformers.center_crop floors the
    # offset: left = (225 - 224) // 2 = 0, so the first column (red) survives and the last
    # column (blue, x=224) is the one cropped away. Rounding to nearest would do the opposite.
    image = Image.new("RGB", (225, 224), (0, 255, 0))
    for y in range(224):
        image.putpixel((0, y), (255, 0, 0))
        image.putpixel((224, y), (0, 0, 255))
    x = _bare_encoder().pixels(image)
    green = x[:, 100, 112]
    assert x[0, 100, 0] > green[0] + 1  # red kept at the first column
    assert abs(x[2, 100, 223] - green[2]) < 0.2  # last column is still green: blue was dropped


def test_transparent_pixels_become_white_not_black():
    logo = Image.new("RGBA", (224, 224), (0, 0, 0, 0))
    logo.paste((10, 10, 10, 255), (80, 80, 144, 144))
    x = _bare_encoder().pixels(logo)
    white = (1.0 - np.array([0.48145466, 0.4578275, 0.40821073], np.float32)) / np.array(
        [0.26862954, 0.26130258, 0.27577711], np.float32)
    assert np.allclose(x[:, 5, 5], white, atol=1e-4)  # was transparent: now white
    assert np.all(x[:, 112, 112] < 0)  # the dark mark stays dark


@pytest.mark.parametrize("mode", ["L", "P", "CMYK", "LA", "I;16"])
def test_other_pixel_modes_are_accepted(mode):
    base = Image.new("RGB", (64, 48), (30, 160, 90))
    image = base.convert(mode) if mode not in ("LA",) else base.convert("L").convert("LA")
    assert _bare_encoder().pixels(image).shape == (3, 224, 224)


def test_palette_with_transparency_is_composited():
    image = Image.new("P", (32, 32), 0)
    image.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    image.info["transparency"] = 0
    x = _bare_encoder().pixels(image)
    assert x[0, 0, 0] > 1.5  # transparent index 0 -> white, not black


def test_animated_gif_uses_its_first_frame(tmp_path):
    frames = [Image.new("RGB", (40, 40), c) for c in ((250, 0, 0), (0, 0, 250))]
    path = tmp_path / "a.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=50, loop=0)
    with Image.open(path) as gif:
        gif.seek(1)
        x = _bare_encoder().pixels(gif)
    assert x[0, 112, 112] > x[2, 112, 112]  # red first frame, not the blue second


# --- the model against the torch reference ------------------------------------------------------

@needs_model
def test_image_vectors_reproduce_torch_exactly():
    ref = json.loads(FIXTURE.read_text())["images"]
    names, images = zip(*fixture_images())
    got = emb.encoder().embed_images(list(images))
    for name, vec in zip(names, got):
        assert _cos(vec, ref[name]) > 0.9999, name
        assert abs(np.linalg.norm(vec) - 1) < 1e-4


@needs_model
def test_query_vectors_stay_close_to_torch_after_int8():
    ref = json.loads(FIXTURE.read_text())["phrases"]
    got = emb.encoder().embed_texts(PHRASES)
    sims = [_cos(v, ref[p]) for v, p in zip(got, PHRASES)]
    assert min(sims) > 0.95 and float(np.mean(sims)) > 0.98, sims


@needs_model
def test_each_phrase_finds_its_own_image():
    enc = emb.encoder()
    names, images = zip(*fixture_images())
    imgs = enc.embed_images(list(images))
    for phrase, name in [(PHRASES[0], "red_circle"), (PHRASES[1], "blue_square"),
                         (PHRASES[3], "stripes"), (PHRASES[5], "yellow_star")]:
        q = enc.embed_texts([phrase])[0]
        assert names[int(np.argmax(imgs @ q))] == name, phrase


@needs_model
def test_bytes_and_pil_inputs_agree_and_batching_changes_nothing():
    import io

    enc = emb.encoder()
    _, images = zip(*fixture_images())
    buf = io.BytesIO()
    images[0].save(buf, format="PNG")
    one = enc.embed_images([images[0]])[0]
    from_bytes = enc.embed_images([buf.getvalue()])[0]
    batched = enc.embed_images(list(images), batch=3)[0]
    assert _cos(one, from_bytes) > 0.99999 and _cos(one, batched) > 0.99999
    texts = enc.embed_texts(PHRASES)  # a query's vector must not depend on its neighbours
    assert all(_cos(enc.embed_texts([p])[0], texts[i]) > 0.99999 for i, p in enumerate(PHRASES))
    assert all(_cos(enc.embed_texts([p, "something else entirely"])[0], texts[i]) > 0.99999
               for i, p in enumerate(PHRASES))


@needs_model
def test_long_empty_and_unicode_queries_embed_without_error():
    enc = emb.encoder()
    out = enc.embed_texts([PHRASES[6], "", PHRASES[7]])
    assert out.shape == (3, 512) and np.all(np.isfinite(out))


@needs_model
def test_concurrent_searches_get_identical_answers():
    enc = emb.encoder()
    expected = enc.embed_texts(PHRASES)
    results, errors = {}, []

    def worker(i):
        try:
            results[i] = enc.embed_texts(PHRASES)
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and all(np.allclose(r, expected, atol=1e-6) for r in results.values())


@needs_model
def test_the_encoder_is_built_once_per_process():
    assert emb.encoder() is emb.encoder()


@needs_model
def test_a_corrupt_text_model_is_a_stated_reason_not_a_crash(monkeypatch, tmp_path):
    for name in ("tokenizer.json", "preprocess.json", "model.json"):
        shutil.copy(MODEL_DIR / name, tmp_path / name)
    (tmp_path / "text.onnx").write_bytes(b"not an onnx model")
    monkeypatch.setattr(settings, "lumen_asset_embedding_model_dir", str(tmp_path))
    with pytest.raises(emb.EmbeddingUnavailable, match="could not be embedded"):
        emb.embed_query("blue")


# --- hybrid order (regression: fusing the whole keyword list, found live 2026-10-05) -------------

def test_a_long_keyword_list_cannot_drown_the_best_visual_match():
    # The live shape: dozens of assets share a common word with the query AND sit somewhere in
    # the visual list; one image is the best look and matches no word at all.
    common = [f"c{i}" for i in range(60)]
    keyword = common
    visual = ["best_look"] + list(reversed(common))
    assert emb.fuse_rankings(keyword, visual).index("best_look") >= 5  # the old whole-list fusion
    assert emb.hybrid_ranking(keyword, visual).index("best_look") < 5


def test_hybrid_returns_every_id_once_and_alternates_the_tails():
    keyword = [f"k{i}" for i in range(12)]
    visual = [f"v{i}" for i in range(12)]
    order = emb.hybrid_ranking(keyword, visual, depth=2)
    assert sorted(order) == sorted(keyword + visual) and len(order) == len(set(order))
    assert order[4:8] == ["k2", "v2", "k3", "v3"]  # tails taken in turn after the fused head


def test_hybrid_with_an_empty_side_is_the_other_side():
    assert emb.hybrid_ranking(["a", "b", "c"], []) == ["a", "b", "c"]
    assert emb.hybrid_ranking([], ["x", "y"]) == ["x", "y"]
