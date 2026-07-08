"""Asset description engine (§3/§4).

Turns brand-kit logos/images into human-readable library metadata
(title/description/usage/tags). ``AssetDescriber`` is the model seam:
``NullDescriber`` (the default everywhere, incl. tests) returns ``[None]*n``;
``OpenRouterDescriber`` (env-gated) captions via a multimodal OpenRouter call.

``DescriptionStore`` persists results in the ``asset_descriptions`` table
(migration 008), protecting human-authored rows from AI overwrites.
``apply_descriptions`` orchestrates: cache hits stamp directly, misses with
resolvable bytes get a downscaled preview and one batched ``describe`` call,
then results are persisted and stamped onto the evidence.

Import hygiene: neither Pillow nor httpx is imported at module load — both are
lazy-imported only on the paths that need them (preview downscale / network).
"""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol, runtime_checkable

from py_lumen_config import settings

from .evidence import BrandEvidence, ImageEvidence, LogoEvidence

DEFAULT_TIMEOUT_S = 60.0
BATCH_SIZE = 8
PREVIEW_MAX_PX = 512


def _default_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- contracts ------------------------------------------------------------------


@dataclass
class DescribeItem:
    asset_id: str
    kind: str  # logo|image|icon|illustration|photo
    image_b64: str  # downscaled preview (≤512px longest side, JPEG/PNG)
    filename: str | None
    context: str  # e.g. "brand: Insight Health; source: upload"


@dataclass
class DescribeResult:
    asset_id: str
    title: str  # ≤ 60 chars
    description: str  # 1–2 sentence literal visual caption (ploy-style)
    usage: str  # design-usage guidance ("use on dark backgrounds…")
    tags: list[str] = field(default_factory=list)


@runtime_checkable
class AssetDescriber(Protocol):
    def describe(self, items: list[DescribeItem]) -> list[DescribeResult | None]: ...


class NullDescriber:
    """Deterministic no-op describer. The default everywhere; tests use this."""

    def describe(self, items: list[DescribeItem]) -> list[DescribeResult | None]:
        return [None] * len(items)


# --- persistence ----------------------------------------------------------------


class DescriptionStore:
    """Durable store for asset descriptions (migration 008).

    Takes a ``sqlite3.Connection`` like the other ingestion stores. Timestamps
    are minted by an injectable ``now_iso`` (default ISO-8601 UTC) so tests can
    freeze them. ``put_ai`` never overwrites a human-authored row.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        now_iso: Callable[[], str] = _default_now_iso,
    ) -> None:
        self.connection = connection
        self.now_iso = now_iso

    def get_many(self, asset_ids: list[str]) -> dict[str, dict]:
        if not asset_ids:
            return {}
        placeholders = ",".join("?" for _ in asset_ids)
        rows = self.connection.execute(
            f"SELECT * FROM asset_descriptions WHERE asset_id IN ({placeholders})",
            list(asset_ids),
        ).fetchall()
        return {row["asset_id"]: _row_to_dict(row) for row in rows}

    def put_ai(self, result: DescribeResult, model: str) -> None:
        now = self.now_iso()
        self.connection.execute(
            """
            INSERT INTO asset_descriptions (
              asset_id, title, description, usage, tags_json,
              origin, model, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'ai', ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
              title = excluded.title,
              description = excluded.description,
              usage = excluded.usage,
              tags_json = excluded.tags_json,
              origin = 'ai',
              model = excluded.model,
              updated_at = excluded.updated_at
            WHERE asset_descriptions.origin != 'human'
            """,
            (
                result.asset_id,
                result.title,
                result.description,
                result.usage,
                json.dumps(list(result.tags)),
                model,
                now,
                now,
            ),
        )
        self.connection.commit()

    def put_human(
        self,
        asset_id: str,
        title: str | None,
        description: str | None,
        usage: str | None,
        tags: list[str],
    ) -> None:
        now = self.now_iso()
        self.connection.execute(
            """
            INSERT INTO asset_descriptions (
              asset_id, title, description, usage, tags_json,
              origin, model, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'human', NULL, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
              title = excluded.title,
              description = excluded.description,
              usage = excluded.usage,
              tags_json = excluded.tags_json,
              origin = 'human',
              model = NULL,
              updated_at = excluded.updated_at
            """,
            (
                asset_id,
                title,
                description,
                usage,
                json.dumps(list(tags)),
                now,
                now,
            ),
        )
        self.connection.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "asset_id": row["asset_id"],
        "title": row["title"],
        "description": row["description"],
        "usage": row["usage"],
        "tags": json.loads(row["tags_json"]) if row["tags_json"] else [],
        "origin": row["origin"],
        "model": row["model"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# --- orchestration --------------------------------------------------------------


def apply_descriptions(
    evidence: BrandEvidence,
    *,
    connection: sqlite3.Connection,
    describer: AssetDescriber,
    resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
    reporter: Callable[[str, float], None],
) -> BrandEvidence:
    """Stamp title/description/usage_note/tags onto ``evidence`` logos+images.

    Cache hits (any origin) stamp directly; misses with resolvable, previewable
    bytes get ONE ``describer.describe`` call in batches of ≤ 8, are persisted
    via ``put_ai``, then stamped. SVGs (no raster preview in v1) and describer
    failures/None are skipped silently with an info diagnostic. Deterministic
    with ``NullDescriber``.
    """
    reporter("Describing your assets…", 0.80)
    store = DescriptionStore(connection)
    model = settings.lumen_ingestion_describe_model

    # asset_id -> evidence entry (logos + images). Both stamp identically.
    targets: dict[str, LogoEvidence | ImageEvidence] = {}
    kinds: dict[str, str] = {}
    for logo in evidence.logos:
        targets[logo.asset_id] = logo
        kinds[logo.asset_id] = "logo"
    for image in evidence.images:
        targets[image.asset_id] = image
        kinds[image.asset_id] = image.kind_hint or "image"

    if not targets:
        return evidence

    brand_name = evidence.narrative.brand_name
    source_kind = evidence.source.get("kind") if isinstance(evidence.source, dict) else None
    context = _context(brand_name, source_kind)

    cached = store.get_many(list(targets.keys()))
    for asset_id, row in cached.items():
        _stamp(targets[asset_id], row)

    # Misses that resolve to previewable bytes → describe.
    items: list[DescribeItem] = []
    for asset_id, entry in targets.items():
        if asset_id in cached:
            continue
        resolved = resolve_bytes(asset_id)
        if resolved is None:
            continue
        data, mime = resolved
        if mime == "image/svg+xml" or _is_svg_bytes(data):
            # LUMI0804: svg preview unavailable — description skipped. A human can
            # title it in the library UI (slice 4).
            continue
        preview = _downscale_preview(data)
        if preview is None:
            continue
        items.append(
            DescribeItem(
                asset_id=asset_id,
                kind=kinds[asset_id],
                image_b64=preview,
                filename=None,
                context=context,
            )
        )

    for batch in _batched(items, BATCH_SIZE):
        try:
            results = describer.describe(batch)
        except Exception:  # noqa: BLE001 - failure must never escape
            # LUMI0803: asset description unavailable — skipped silently, evidence
            # unchanged for this batch.
            continue
        for item, result in zip(batch, results):
            if result is None:
                continue
            store.put_ai(result, model)
            _stamp(targets[item.asset_id], _result_to_row(result))

    return evidence


def _context(brand_name: str | None, source_kind: str | None) -> str:
    parts = []
    if brand_name:
        parts.append(f"brand: {brand_name}")
    if source_kind:
        parts.append(f"source: {source_kind}")
    return "; ".join(parts) if parts else "source: upload"


def _stamp(entry: "LogoEvidence | ImageEvidence", row: dict) -> None:
    entry.title = row.get("title")
    entry.description = row.get("description")
    entry.usage_note = row.get("usage")
    entry.tags = list(row.get("tags") or [])


def _result_to_row(result: DescribeResult) -> dict:
    return {
        "title": result.title,
        "description": result.description,
        "usage": result.usage,
        "tags": list(result.tags),
    }


def _batched(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _is_svg_bytes(data: bytes) -> bool:
    head = data[:512].decode("utf-8", errors="ignore").lstrip("﻿ \t\r\n")
    return "<svg" in head.lower()


def _downscale_preview(data: bytes) -> str | None:
    """Downscale to ≤512px longest side, return base64 JPEG/PNG, or None on
    failure. Pillow is lazy-imported here only."""
    try:
        from io import BytesIO

        from PIL import Image  # lazy: only the preview path needs Pillow

        with Image.open(BytesIO(data)) as img:
            img.load()
            has_alpha = img.mode in ("RGBA", "LA", "P")
            img = img.convert("RGBA") if has_alpha else img.convert("RGB")
            img.thumbnail((PREVIEW_MAX_PX, PREVIEW_MAX_PX))
            buffer = BytesIO()
            if has_alpha:
                img.save(buffer, format="PNG")
            else:
                img.save(buffer, format="JPEG", quality=85)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001
        return None


# --- OpenRouter describer -------------------------------------------------------


class OpenRouterDescriber:
    """LLM-backed multimodal describer over OpenRouter. Enabled only when
    ``LUMEN_INGESTION_DESCRIBE=1``. Never call the network in tests."""

    def __init__(self) -> None:
        self.enabled = settings.lumen_ingestion_describe
        self.model = settings.lumen_ingestion_describe_model
        self.base_url = settings.openrouter_base_url
        self.api_key = settings.openrouter_api_key

    def describe(self, items: list[DescribeItem]) -> list[DescribeResult | None]:
        if not items:
            return []
        if not self.enabled or not self.api_key:
            return [None] * len(items)
        payload = self._invoke(items)
        if payload is None:
            return [None] * len(items)
        by_id = {str(obj.get("asset_id")): obj for obj in payload if isinstance(obj, dict)}
        results: list[DescribeResult | None] = []
        for item in items:
            obj = by_id.get(item.asset_id)
            if obj is None:
                results.append(None)
                continue
            results.append(
                DescribeResult(
                    asset_id=item.asset_id,
                    title=str(obj.get("title") or "")[:60],
                    description=str(obj.get("description") or ""),
                    usage=str(obj.get("usage") or ""),
                    tags=[str(t) for t in (obj.get("tags") or [])],
                )
            )
        return results

    def _invoke(self, items: list[DescribeItem]) -> list | None:
        import httpx  # lazy: only the real network path needs it

        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    "Describe each image below. Return a JSON array with one object per "
                    "image, in order, each with keys asset_id, title, description, usage, "
                    "tags.\n\n" + _items_manifest(items)
                ),
            }
        ]
        for item in items:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(item)},
                }
            )

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "asset_descriptions",
                    "strict": True,
                    "schema": _RESPONSE_SCHEMA,
                },
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = self.base_url.rstrip("/") + "/chat/completions"
        for _ in range(2):
            try:
                response = httpx.post(url, json=body, headers=headers, timeout=DEFAULT_TIMEOUT_S)
                if response.status_code >= 400:
                    continue
                raw = response.json()["choices"][0]["message"]["content"]
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    parsed = parsed.get("descriptions") or parsed.get("items") or []
                return parsed if isinstance(parsed, list) else None
            except Exception:  # noqa: BLE001
                continue
        return None


def _items_manifest(items: list[DescribeItem]) -> str:
    lines = []
    for index, item in enumerate(items, start=1):
        label = item.filename or item.asset_id
        lines.append(f"{index}. asset_id={item.asset_id} kind={item.kind} ({label}) — {item.context}")
    return "\n".join(lines)


def _data_url(item: DescribeItem) -> str:
    # Preview is JPEG or PNG; PNG is a safe superset for the data URL header.
    return f"data:image/png;base64,{item.image_b64}"


_SYSTEM_PROMPT = (
    "You caption brand assets for a design library. For each image return a "
    "literal visual caption — name the subjects, colors, any text visible in the "
    "image, and the style. Then give one sentence of design-usage guidance "
    "(background suitability, scale, pairing). Keep titles under 60 characters. "
    "Return valid JSON matching the schema; one object per image in the given "
    "order, echoing each asset_id."
)

_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "asset_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "usage": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["asset_id", "title", "description", "usage", "tags"],
        "additionalProperties": False,
    },
}
