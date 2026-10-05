"""CLIP image and query embeddings for the scene agent's hybrid asset search (2026-10-05).

Founder ruling: `search_assets` fuses today's keyword ranking with a visual one. Ingestion stores
one image vector per asset (`design_asset_embedding`); a turn hands the runtime the workspace's
vectors by value; each search turns the query into a vector and ranks the images by closeness.

Runs on ONNX Runtime, never torch: the backend image is shared by the Railway API servers and the
worker VM, so the model and its runtime stay small and the model files live outside the image
(`LUMEN_ASSET_EMBEDDING_MODEL_DIR`, built by `scripts/export_clip_onnx.py`):

- ``image.onnx``  fp32 image encoder. Loaded only where images are embedded (the ingestion pool).
- ``text.onnx``   int8 text encoder. Loaded by any process that searches (the fleet workers).
- ``tokenizer.json``, ``preprocess.json``, ``model.json``.

The fp32 image half reproduces the torch reference exactly; the int8 text half keeps the T1
search result unchanged (accuracy check 2026-10-05, plan doc §7). Preprocessing mirrors
``CLIPImageProcessor``: RGB, shortest side to 224 with bicubic, floor-centred 224 crop, scale to
[0, 1], normalise with CLIP's mean and std.

Everything here degrades instead of failing: a missing setting, directory or file, or a model
that will not load, makes the encoder unavailable with a stated reason. Ingestion then skips the
vector and search stays keyword-only.
"""

from __future__ import annotations

import io
import json
import threading
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np

from py_lumen_config import settings
from py_lumen_obs import get_logger

logger = get_logger("lumen_api.asset_embeddings")

#: The rank-fusion constant (reciprocal rank fusion, the usual 60). Larger flattens the curve.
FUSION_K = 60
#: How deep into EACH ranking the fusion reaches. Measured 2026-10-05 against the founder's T1
#: labels through the real tool: fusing each list's top 3–8 found a right asset for 9/9 requests
#: (28/36 right assets); top 10 → 27/36, top 20 → 7/9 and 25/36, everything → 7/9 and 26/36. The
#: keyword list is long (most Conduit assets share a word with almost any query), so fusing all of
#: it rewards images that are mediocre in both lists over one that is first in either.
FUSION_DEPTH = 8


class EmbeddingUnavailable(RuntimeError):
    """The encoder cannot run here; the message says why in one plain sentence."""


@dataclass(frozen=True)
class ModelInfo:
    space: str
    dim: int
    directory: Path


def _model_dir() -> Path:
    if not settings.lumen_asset_embeddings:
        raise EmbeddingUnavailable("visual search is switched off (LUMEN_ASSET_EMBEDDINGS=0)")
    raw = (settings.lumen_asset_embedding_model_dir or "").strip()
    if not raw:
        raise EmbeddingUnavailable("no embedding model directory is configured")
    directory = Path(raw).expanduser()
    if not directory.is_dir():
        raise EmbeddingUnavailable(f"the embedding model directory does not exist: {directory}")
    return directory


def model_info() -> ModelInfo:
    """The embedding space this host's model belongs to. Raises :class:`EmbeddingUnavailable`."""
    directory = _model_dir()
    try:
        meta = json.loads((directory / "model.json").read_text())
        return ModelInfo(space=str(meta["space"]), dim=int(meta["dim"]), directory=directory)
    except Exception as error:  # noqa: BLE001
        raise EmbeddingUnavailable(f"model.json is unreadable: {type(error).__name__}") from error


class ClipEncoder:
    """One loaded model directory. Each half loads on first use; both are thread-safe."""

    def __init__(self, directory: Path, *, threads: int | None = None) -> None:
        from tokenizers import Tokenizer

        self.directory = directory
        self.pre = json.loads((directory / "preprocess.json").read_text())
        self._threads = threads
        self._image = None
        self._text = None
        self._image_lock = threading.Lock()
        self._text_lock = threading.Lock()
        tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        length = int(self.pre["context_length"])
        eos = tokenizer.token_to_id("<|endoftext|>")
        tokenizer.enable_truncation(max_length=length)
        tokenizer.enable_padding(length=length, pad_id=eos, pad_token="<|endoftext|>")
        self._tokenizer = tokenizer
        self._mean = np.array(self.pre["mean"], dtype=np.float32).reshape(3, 1, 1)
        self._std = np.array(self.pre["std"], dtype=np.float32).reshape(3, 1, 1)

    def _session(self, name: str):
        import onnxruntime as ort

        options = ort.SessionOptions()
        if self._threads:
            options.intra_op_num_threads = self._threads
        return ort.InferenceSession(str(self.directory / name), options, providers=["CPUExecutionProvider"])

    # --- images -------------------------------------------------------------------------------
    def pixels(self, image: Any) -> np.ndarray:
        """One image as CLIP's [3, 224, 224] float32 input (see the module docstring)."""
        from PIL import Image

        size, crop = int(self.pre["size"]), int(self.pre["crop"])
        if getattr(image, "is_animated", False):
            image.seek(0)
        if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
            # A transparent logo converted straight to RGB turns its clear pixels black, so a dark
            # mark on a transparent ground becomes dark-on-black and CLIP sees almost nothing.
            # Composite over white first — the one deliberate step beyond CLIPImageProcessor.
            rgba = image.convert("RGBA")
            ground = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            image = Image.alpha_composite(ground, rgba)
        image = image.convert("RGB")
        width, height = image.size
        if width <= height:
            new_w, new_h = size, max(size, int(size * height / width))
        else:
            new_w, new_h = max(size, int(size * width / height)), size
        image = image.resize((new_w, new_h), Image.Resampling.BICUBIC)
        left, top = (new_w - crop) // 2, (new_h - crop) // 2  # floor, as transformers.center_crop
        image = image.crop((left, top, left + crop, top + crop))
        array = np.asarray(image, dtype=np.float32).transpose(2, 0, 1) / 255.0
        return (array - self._mean) / self._std

    def embed_images(self, images: Sequence[Any], *, batch: int = 16) -> np.ndarray:
        """Normalised [N, dim] vectors for PIL images or encoded image bytes."""
        from PIL import Image

        with self._image_lock:
            if self._image is None:
                self._image = self._session("image.onnx")
            session = self._image
        out = []
        for start in range(0, len(images), batch):
            chunk = []
            for item in images[start:start + batch]:
                image = Image.open(io.BytesIO(item)) if isinstance(item, (bytes, bytearray)) else item
                chunk.append(self.pixels(image))
            (vectors,) = session.run(None, {"pixel_values": np.stack(chunk).astype(np.float32)})
            out.append(vectors)
        if not out:
            return np.zeros((0, 512), dtype=np.float32)
        return normalise(np.concatenate(out))

    # --- text ---------------------------------------------------------------------------------
    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Normalised [N, dim] vectors. Text past the model's 77 tokens is truncated.

        One text per model call, on purpose: the int8 text model quantises its activations per
        call, so a phrase embedded beside others came out slightly different (cosine 0.995–0.999)
        from the same phrase alone. Alone, a query always gets the same vector. ~8 ms each.
        """
        with self._text_lock:
            if self._text is None:
                self._text = self._session("text.onnx")
            session = self._text
        out = []
        for encoded in self._tokenizer.encode_batch([str(t or "") for t in texts]):
            ids = np.array([encoded.ids], dtype=np.int64)
            mask = np.array([encoded.attention_mask], dtype=np.int64)
            (vectors,) = session.run(None, {"input_ids": ids, "attention_mask": mask})
            out.append(vectors[0])
        if not out:
            return np.zeros((0, 512), dtype=np.float32)
        return normalise(np.stack(out))


def normalise(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)


_ENCODERS: dict[str, ClipEncoder] = {}
_ENCODERS_LOCK = threading.Lock()


def encoder() -> ClipEncoder:
    """This process's encoder for the configured directory. Raises :class:`EmbeddingUnavailable`."""
    directory = _model_dir()
    key = str(directory.resolve())
    with _ENCODERS_LOCK:
        found = _ENCODERS.get(key)
        if found is not None:
            return found
        missing = [n for n in ("tokenizer.json", "preprocess.json", "model.json") if not (directory / n).is_file()]
        if missing:
            raise EmbeddingUnavailable(f"the embedding model directory lacks {', '.join(missing)}")
        try:
            found = ClipEncoder(directory)
        except Exception as error:  # noqa: BLE001
            raise EmbeddingUnavailable(f"the embedding model will not load: {type(error).__name__}") from error
        _ENCODERS[key] = found
        return found


def embed_query(text: str) -> np.ndarray:
    """One normalised query vector. Raises :class:`EmbeddingUnavailable` with the reason."""
    try:
        return encoder().embed_texts([text])[0]
    except EmbeddingUnavailable:
        raise
    except Exception as error:  # noqa: BLE001 - a broken text.onnx is a stated gap, not a crash
        raise EmbeddingUnavailable(f"the query could not be embedded: {type(error).__name__}") from error


def embed_image_bytes(data: bytes) -> np.ndarray:
    """One normalised image vector. Raises :class:`EmbeddingUnavailable` or the decode error."""
    try:
        enc = encoder()
    except EmbeddingUnavailable:
        raise
    return enc.embed_images([data])[0]


# --- storage ----------------------------------------------------------------------------------

def vector_literal(vector: Iterable[float]) -> str:
    """pgvector's text form: ``[0.1,0.2,...]``."""
    return "[" + ",".join(f"{float(x):.7g}" for x in vector) + "]"


def parse_vector(text: str) -> list[float]:
    return [float(x) for x in str(text).strip().strip("[]").split(",") if x.strip()]


def load_workspace_embeddings(workspace_id: str, asset_ids: Optional[Iterable[str]] = None) -> dict[str, list[float]]:
    """``{asset_id: vector}`` for this workspace in the configured model's space.

    Empty when visual search is unavailable or the read fails: a turn must never fail on it.
    """
    try:
        space = model_info().space
    except EmbeddingUnavailable:
        return {}
    wanted = set(asset_ids) if asset_ids is not None else None
    try:
        from sqlalchemy import text

        from lumen_api.design_store import DesignStoreBridge

        async def read(conn):
            rows = await conn.execute(
                text("SELECT asset_id, embedding::text AS v FROM design_asset_embedding "
                     "WHERE workspace_id = :w AND model = :m"),
                {"w": workspace_id, "m": space},
            )
            return [(r.asset_id, r.v) for r in rows]

        # A read must never write: the default bridge would create a missing workspace row.
        rows = DesignStoreBridge(workspace_id, ensure_workspace=False)._run(read)
    except Exception as error:  # noqa: BLE001
        logger.warning("asset_embeddings_unreadable", workspace_id=workspace_id, error=type(error).__name__)
        return {}
    return {aid: parse_vector(v) for aid, v in rows if wanted is None or aid in wanted}


# --- ranking ----------------------------------------------------------------------------------

def fuse_rankings(*rankings: Sequence[str], k: int = FUSION_K) -> list[str]:
    """Reciprocal rank fusion: each list contributes 1 / (k + rank) to an id; best first.

    Ties keep the order of first appearance, so the result is deterministic.
    """
    score: dict[str, float] = {}
    first: dict[str, int] = {}
    order = 0
    for ranking in rankings:
        for rank, asset_id in enumerate(ranking):
            score[asset_id] = score.get(asset_id, 0.0) + 1.0 / (k + rank + 1)
            if asset_id not in first:
                first[asset_id] = order
                order += 1
    return sorted(score, key=lambda a: (-score[a], first[a]))


def hybrid_ranking(keyword: Sequence[str], visual: Sequence[str], *, depth: int = FUSION_DEPTH) -> list[str]:
    """The search order: the fused heads of both lists, then their tails taken in turn.

    Only the top ``depth`` of each list is fused (see FUSION_DEPTH); a request for more results
    than that continues with the remaining keyword and visual hits alternately, so asking for 20
    still returns 20 without letting the deep keyword tail dilute the head.
    """
    head = fuse_rankings(keyword[:depth], visual[:depth])
    seen = set(head)
    tail: list[str] = []
    for pair in zip_longest(keyword[depth:], visual[depth:]):
        for asset_id in pair:
            if asset_id is not None and asset_id not in seen:
                seen.add(asset_id)
                tail.append(asset_id)
    return head + tail


def visual_ranking(query_vector: np.ndarray, embeddings: dict[str, Sequence[float]],
                   candidates: Iterable[str], *, top: int = 50) -> list[str]:
    """Candidate ids with a stored vector, closest to the query first."""
    ids = [a for a in candidates if a in embeddings]
    if not ids:
        return []
    matrix = normalise(np.array([embeddings[a] for a in ids], dtype=np.float32))
    scores = matrix @ np.asarray(query_vector, dtype=np.float32)
    order = np.argsort(-scores, kind="stable")[:top]
    return [ids[i] for i in order]
