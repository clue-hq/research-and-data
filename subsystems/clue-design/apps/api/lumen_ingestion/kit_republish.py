"""Describe a kit's own assets and publish a new kit version carrying the descriptions.

Descriptions are frozen into the kit JSON at publish, so healing the description library alone
never reaches the agent's brand card: the kit must be republished. Two callers share this one
step: the ``POST /brand-kits/{id}/describe-assets`` backfill route, and the workspace-repair job
(``kit_repair``, spec 2026-10-25 §3.4 B), which runs it with an inactive describer after its own
batch enrichment so it only stamps what is already described.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from lumen_api.design_store import DesignBlobStore, HybridRepository

from .describe import describe_kit_assets
from .normalizer.font_metrics import ensure_glyph_coverage, ensure_type_size_ramp

JsonObject = dict[str, Any]

#: ``publish(brand_kit, brand_summary, diagnostics, expected_base_version) -> created kit record``
Publish = Callable[[JsonObject, JsonObject, list, int], JsonObject]


def republish_kit_with_descriptions(
    repo: HybridRepository,
    *,
    brand_kit_id: str,
    blobs: DesignBlobStore,
    describer: Any,
    core: Any,
    publish: Publish,
    cache_dir: str,
) -> JsonObject:
    """Stamp descriptions onto the latest kit version and publish the next one when anything
    changed. Returns ``{brand_kit_id, published, counts, diagnostics, created}``; ``created`` is
    the new kit record, or ``None`` when nothing changed (an identical version would be noise).

    Engine failures raise the core client's own error; the route maps it to HTTP.
    """
    from .pipeline import make_rasterize_svg, make_resolve_bytes

    record = repo.require_brand_kit(brand_kit_id)
    brand_kit = json.loads(json.dumps(record["brand_kit"]))
    before = json.dumps(brand_kit, sort_keys=True)
    # Kits produced before the type-size ramp normalizer lack $type.size.* and fail preflight;
    # idempotent, so an up-to-date kit stays byte-identical and never forces a republish.
    ensure_type_size_ramp(brand_kit)
    diagnostics: list = []
    ensure_glyph_coverage(brand_kit, make_resolve_bytes(repo, blobs), diagnostics)
    counts = describe_kit_assets(
        brand_kit,
        describer=describer,
        resolve_bytes=make_resolve_bytes(repo, blobs),
        rasterize_svg=make_rasterize_svg(repo, blobs, cache_dir),
        diagnostics=diagnostics,
        brand_name=record.get("name"),
        workspace_id=repo.workspace_id,
    )
    result: JsonObject = {
        "brand_kit_id": brand_kit_id,
        "published": False,
        "counts": counts,
        "diagnostics": diagnostics,
        "created": None,
    }
    if json.dumps(brand_kit, sort_keys=True) == before:
        return result
    # Provisional: the publish allocates the real number inside its locked write.
    base_version = int(record["version"])
    brand_kit["version"] = base_version + 1
    validation = core.validate_brand_kit(brand_kit, product_ready=False)
    summary = core.summarize_brand_kit(validation["brand_kit"], raise_on_error=False)
    from lumen_api.brand_kit_sections import carry_kit_sections

    brand_kit = carry_kit_sections(brand_kit, validation["brand_kit"])
    result["diagnostics"] = (
        summary.get("diagnostics") or validation.get("diagnostics", [])
    ) + diagnostics
    result["created"] = publish(
        brand_kit, summary.get("brand_summary") or {}, result["diagnostics"], base_version
    )
    result["published"] = True
    return result
