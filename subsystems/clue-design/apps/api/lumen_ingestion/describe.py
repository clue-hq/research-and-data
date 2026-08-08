"""Asset description engine (§3/§4).

Turns brand-kit logos/images into human-readable library metadata
(title/description/usage/tags). ``AssetDescriber`` is the model seam:
``NullDescriber`` (the default everywhere, incl. tests) returns ``[None]*n``;
``OpenRouterDescriber`` (env-gated) captions via a multimodal OpenRouter call.

``DescriptionStore`` persists results in the ``design_asset_description`` table
(Postgres, via ``clue_design.descriptions`` since Part II D2.3), protecting
human-authored rows from AI overwrites.
``apply_descriptions`` orchestrates: cache hits stamp directly, misses with
resolvable bytes get a downscaled preview and one batched ``describe`` call,
then results are persisted and stamped onto the evidence.

Import hygiene: neither Pillow nor httpx is imported at module load — both are
lazy-imported only on the paths that need them (preview downscale / network).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from clue_design import descriptions as design_descriptions
from lumen_api.design_store import DesignStoreBridge, default_workspace_id
from py_lumen_config import settings

from .evidence import BrandEvidence, ImageEvidence, LogoEvidence

DEFAULT_TIMEOUT_S = 60.0
PREVIEW_MAX_PX = 512
#: Cap on how much of an HTTP error body / exception message is threaded into a
#: diagnostic — loud enough to name the cause, bounded so a giant HTML error
#: page never floods the report.
FAILURE_EXCERPT_MAX = 300


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
    """Deterministic no-op describer. The default everywhere; tests use this.

    ``active = False`` tells the orchestrator to skip the miss pass entirely —
    describe being OFF is not N per-asset failures."""

    active = False

    def describe(self, items: list[DescribeItem]) -> list[DescribeResult | None]:
        return [None] * len(items)


# --- persistence ----------------------------------------------------------------


class DescriptionStore:
    """Durable store for asset descriptions (Part II slice D2.3: Postgres, same surface).

    The SQL moved to ``clue_design.descriptions``; every method routes through one
    :class:`~lumen_api.design_store.DesignStoreBridge` call (one coroutine, one loop, one
    transaction — the O5 rule) and returns the same shapes as before. ``put_ai`` still never
    overwrites a human-authored row — the guard is the DAL's conditional ``ON CONFLICT``.

    D2.5B deleted the vestigial ``connection`` (the SQLite handle) and ``now_iso`` (timestamps
    have been the database's ``now()`` since the port) constructor arguments along with the
    SQLite substrate itself. ``workspace_id`` defaults to the configured dev workspace, like
    ``HybridRepository``.
    """

    def __init__(self, *, workspace_id: str | None = None) -> None:
        self.workspace_id = workspace_id or default_workspace_id()
        self._bridge = DesignStoreBridge(self.workspace_id)

    def get_many(self, asset_ids: list[str]) -> dict[str, dict]:
        return self._bridge._run(
            lambda conn: design_descriptions.get_many(
                conn, workspace_id=self.workspace_id, asset_ids=list(asset_ids)
            )
        )

    def put_ai(self, result: DescribeResult, model: str) -> None:
        self._bridge._run(
            lambda conn: design_descriptions.put_ai(
                conn,
                workspace_id=self.workspace_id,
                asset_id=result.asset_id,
                title=result.title,
                description=result.description,
                usage=result.usage,
                tags=list(result.tags),
                model=model,
            )
        )

    def put_human(
        self,
        asset_id: str,
        title: str | None,
        description: str | None,
        usage: str | None,
        tags: list[str],
    ) -> None:
        self._bridge._run(
            lambda conn: design_descriptions.put_human(
                conn,
                workspace_id=self.workspace_id,
                asset_id=asset_id,
                title=title,
                description=description,
                usage=usage,
                tags=list(tags),
            )
        )


# --- orchestration --------------------------------------------------------------


def apply_descriptions(
    evidence: BrandEvidence,
    *,
    describer: AssetDescriber,
    resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
    reporter: Callable[[str, float], None],
    rasterize_svg: Callable[[str], bytes | None] | None = None,
    diagnostics: list[dict] | None = None,
    workspace_id: str | None = None,
) -> BrandEvidence:
    """Stamp title/description/usage_note/tags onto ``evidence`` logos+images.

    Cache hits (any origin) stamp directly; each miss gets its OWN describe
    call (one image per request — a timeout or malformed image costs exactly
    one caption, never a batch; the ``asset_descriptions`` cache makes the
    per-image latency a once-per-lifetime cost). SVGs raster through the
    injected ``rasterize_svg`` seam (the engine renderer, in production).

    Nothing is skipped silently: every miss that ends undescribed appends one
    named warning to ``diagnostics`` (LUMI0803 describe failed, LUMI0804
    preview unavailable, LUMI0805 bytes unresolvable), and the final reporter
    call carries the described-N-of-M summary. An INACTIVE describer (Null, or
    OpenRouter without the env gate/key) skips the miss pass entirely — off is
    off, not N failures. Deterministic with ``NullDescriber``.
    """
    reporter("Describing your assets…", 0.80)
    sink = diagnostics if diagnostics is not None else []
    store = DescriptionStore(workspace_id=workspace_id)
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

    misses = [a for a in targets if a not in cached]
    if not misses or not getattr(describer, "active", True):
        reporter(
            f"Asset descriptions: {len(cached)}/{len(targets)} cached"
            + ("" if getattr(describer, "active", True) else " (describe disabled)"),
            0.82,
        )
        return evidence

    described = 0
    failed = 0
    for asset_id, preview in _previews(
        misses, kinds, resolve_bytes, rasterize_svg, sink
    ):
        if preview is None:
            failed += 1
            continue
        item = DescribeItem(
            asset_id=asset_id,
            kind=kinds[asset_id],
            image_b64=preview,
            filename=None,
            context=context,
        )
        result: DescribeResult | None
        try:
            results = describer.describe([item])
            result = results[0] if results else None
        except Exception as error:  # noqa: BLE001 - one asset must never sink the rest
            _warn(
                sink,
                "LUMI0803",
                f"asset description failed for {asset_id}: {error}",
            )
            failed += 1
            continue
        if result is None:
            _warn(
                sink,
                "LUMI0803",
                f"asset description returned nothing for {asset_id}"
                + _describe_failure_suffix(describer),
            )
            failed += 1
            continue
        store.put_ai(result, model)
        _stamp(targets[asset_id], _result_to_row(result))
        described += 1

    reporter(
        f"Asset descriptions: {described + len(cached)}/{len(targets)} "
        f"({described} new, {len(cached)} cached, {failed} failed)",
        0.85,
    )
    return evidence


def _previews(
    misses: list[str],
    kinds: dict[str, str],
    resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
    rasterize_svg: Callable[[str], bytes | None] | None,
    sink: list[dict],
):
    """Yield (asset_id, preview_b64 | None) per miss, appending one named
    diagnostic for every miss that cannot produce a preview."""
    for asset_id in misses:
        resolved = resolve_bytes(asset_id)
        if resolved is None:
            _warn(
                sink,
                "LUMI0805",
                f"asset bytes unresolvable for {asset_id} — description skipped",
            )
            yield asset_id, None
            continue
        data, mime = resolved
        if mime == "image/svg+xml" or _is_svg_bytes(data):
            raster = rasterize_svg(asset_id) if rasterize_svg is not None else None
            if raster is None:
                _warn(
                    sink,
                    "LUMI0804",
                    f"svg preview unavailable for {asset_id} — description skipped",
                )
                yield asset_id, None
                continue
            data = raster
        preview = _downscale_preview(data)
        if preview is None:
            _warn(
                sink,
                "LUMI0804",
                f"preview downscale failed for {asset_id} — description skipped",
            )
            yield asset_id, None
            continue
        yield asset_id, preview


def _warn(sink: list[dict], code: str, message: str) -> None:
    sink.append({"code": code, "severity": "warning", "message": message})


def _describe_failure_suffix(describer: "AssetDescriber") -> str:
    """`: <reason>` when the describer recorded why its last call produced no
    captions (HTTP status/body or exception), else empty. Lets the LUMI0803
    'returned nothing' diagnostic carry the actual cause instead of a bare
    'nothing'."""
    reason = getattr(describer, "last_failure_reason", None)
    if reason:
        return f": {reason}"
    return ""


def describe_kit_assets(
    brand_kit: dict,
    *,
    describer: AssetDescriber,
    resolve_bytes: Callable[[str], "tuple[bytes, str] | None"],
    rasterize_svg: Callable[[str], bytes | None] | None = None,
    diagnostics: list[dict] | None = None,
    brand_name: str | None = None,
    workspace_id: str | None = None,
) -> dict:
    """Backfill (imagery slice 1): stamp title/description/usage_note onto the
    KIT's own logo/image entries — cache-first over ``asset_descriptions``,
    one describe call per miss, same diagnostics contract as
    ``apply_descriptions``. Mutates ``brand_kit`` in place and returns counts;
    the caller republishes the kit as a NEW version, because descriptions are
    frozen into the kit JSON at publish — healing the library alone never
    reaches the agent's brand card."""
    sink = diagnostics if diagnostics is not None else []
    store = DescriptionStore(workspace_id=workspace_id)
    model = settings.lumen_ingestion_describe_model
    assets = brand_kit.get("assets") or {}

    # asset_id -> every kit entry it should stamp (an asset can sit in several
    # slots), plus a kind per asset for the vision prompt.
    targets: dict[str, list[dict]] = {}
    kinds: dict[str, str] = {}
    for logo in (assets.get("logos") or {}).values():
        if not isinstance(logo, dict):
            continue
        variants = [v for v in (logo.get("variants") or []) if isinstance(v, dict)]
        asset_id = str((variants[0] if variants else {}).get("asset_id") or "")
        if asset_id:
            targets.setdefault(asset_id, []).append(logo)
            kinds[asset_id] = "logo"
    for image in (assets.get("images") or {}).values():
        if not isinstance(image, dict):
            continue
        asset_id = str(image.get("asset_id") or "")
        if asset_id:
            targets.setdefault(asset_id, []).append(image)
            kinds.setdefault(asset_id, str(image.get("role") or "image"))

    counts = {
        "total": len(targets),
        "cached": 0,
        "described": 0,
        "failed": 0,
        # Per-asset failure reasons (asset_id -> why), so the job summary
        # carries the cause of every LUMI0803, not just a count.
        "failures": {},
    }
    if not targets:
        return counts

    cached = store.get_many(list(targets.keys()))
    for asset_id, row in cached.items():
        for entry in targets[asset_id]:
            _stamp_kit_entry(entry, row)
    counts["cached"] = len(cached)

    misses = [a for a in targets if a not in cached]
    if not misses or not getattr(describer, "active", True):
        return counts

    context = _context(brand_name, "backfill")
    for asset_id, preview in _previews(
        misses, kinds, resolve_bytes, rasterize_svg, sink
    ):
        if preview is None:
            counts["failed"] += 1
            continue
        item = DescribeItem(
            asset_id=asset_id,
            kind=kinds[asset_id],
            image_b64=preview,
            filename=None,
            context=context,
        )
        try:
            results = describer.describe([item])
            result = results[0] if results else None
        except Exception as error:  # noqa: BLE001 - one asset must never sink the rest
            reason = f"{type(error).__name__}: {error}"[:FAILURE_EXCERPT_MAX]
            _warn(sink, "LUMI0803", f"asset description failed for {asset_id}: {reason}")
            counts["failures"][asset_id] = reason
            counts["failed"] += 1
            continue
        if result is None:
            suffix = _describe_failure_suffix(describer)
            _warn(
                sink,
                "LUMI0803",
                f"asset description returned nothing for {asset_id}" + suffix,
            )
            counts["failures"][asset_id] = suffix[2:] if suffix else "returned nothing"
            counts["failed"] += 1
            continue
        store.put_ai(result, model)
        row = _result_to_row(result)
        for entry in targets[asset_id]:
            _stamp_kit_entry(entry, row)
        counts["described"] += 1

    return counts


def _stamp_kit_entry(entry: dict, row: dict) -> None:
    """Stamp library metadata onto a kit logo/image entry. Absent values leave
    the entry untouched (fields stay OMITTED, matching the Rust
    skip_serializing_if on title/description/usage_note)."""
    if row.get("title"):
        entry["title"] = row["title"]
    if row.get("description"):
        entry["description"] = row["description"]
    if row.get("usage"):
        entry["usage_note"] = row["usage"]


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
        #: Why the most recent ``describe`` call produced no captions (HTTP
        #: status + body excerpt, or exception class + message). Set on every
        #: call so the orchestrator can thread it into the LUMI0803 diagnostic;
        #: None when the call succeeded.
        self.last_failure_reason: str | None = None

    @property
    def active(self) -> bool:
        """Whether describe can actually run — gates the orchestrator's miss
        pass so an un-keyed/disabled describer is OFF, not N failures."""
        return bool(self.enabled and self.api_key)

    def describe(self, items: list[DescribeItem]) -> list[DescribeResult | None]:
        self.last_failure_reason = None
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
        for attempt in range(2):
            try:
                response = httpx.post(url, json=body, headers=headers, timeout=DEFAULT_TIMEOUT_S)
                if response.status_code >= 400:
                    excerpt = response.text[:FAILURE_EXCERPT_MAX]
                    self.last_failure_reason = (
                        f"HTTP {response.status_code} (attempt {attempt + 1}): {excerpt}"
                    )
                    continue
                raw = response.json()["choices"][0]["message"]["content"]
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    parsed = parsed.get("descriptions") or parsed.get("items") or []
                if isinstance(parsed, list):
                    self.last_failure_reason = None
                    return parsed
                self.last_failure_reason = (
                    f"malformed response (attempt {attempt + 1}): expected a JSON array, "
                    f"got {type(parsed).__name__}"
                )
                continue
            except Exception as error:  # noqa: BLE001
                message = str(error)[:FAILURE_EXCERPT_MAX]
                self.last_failure_reason = (
                    f"{type(error).__name__} (attempt {attempt + 1}): {message}"
                )
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
