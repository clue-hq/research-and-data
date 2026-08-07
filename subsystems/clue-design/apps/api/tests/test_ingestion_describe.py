from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import sqlite3
from pathlib import Path

import pytest

from lumen_api.core import CoreClient
from lumen_api.database import connect, run_migrations
from lumen_api.design_store import HybridRepository
from lumen_ingestion import normalize_evidence
from lumen_ingestion.describe import (
    DescribeItem,
    DescribeResult,
    DescriptionStore,
    NullDescriber,
    apply_descriptions,
)
from lumen_ingestion.evidence import (
    BrandEvidence,
    EvidencePointer,
    ImageEvidence,
    LogoEvidence,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _noop(stage: str, progress: float) -> None:
    return None


def _frozen_clock():
    ticks = iter(f"2026-01-01T00:00:{s:02d}+00:00" for s in range(60))

    def now_iso() -> str:
        return next(ticks)

    return now_iso


def _connection(tmp_path: Path) -> sqlite3.Connection:
    database_path = tmp_path / "api.sqlite3"
    run_migrations(database_path)
    return connect(database_path)


def _register(connection: sqlite3.Connection, *asset_ids: str) -> None:
    """D2.3: descriptions live on ``design_asset_description``, which is FK'd 1:1 to the
    registry row in the SAME workspace (SQLite omitted that FK). Every asset a test describes
    therefore needs a registry row first — which is also the production order, since the
    pipeline persists records before the describe pass."""
    repo = HybridRepository(connection)
    for asset_id in asset_ids:
        digest = hashlib.sha256(asset_id.encode()).hexdigest()
        repo.create_asset_record(
            {
                "id": asset_id,
                "label": asset_id,
                "kind": "image",
                "status": "ready",
                "tags": [],
                "media": {
                    "mime_type": "image/png",
                    "byte_length": 1,
                    "filename": f"{asset_id}.png",
                    "digest": {"algorithm": "sha256", "value": digest},
                    "location": {"provider": "local-store", "opaque_ref": f"sha256/{digest}"},
                },
            }
        )


def _stored(connection: sqlite3.Connection, asset_id: str) -> dict:
    """The persisted description row (Postgres since D2.3) — the ported ``asset_descriptions``
    SELECT the SQLite-era assertions used."""
    return DescriptionStore(connection).get_many([asset_id]).get(asset_id) or {}


def _description_count(connection: sqlite3.Connection, *asset_ids: str) -> int:
    return len(DescriptionStore(connection).get_many(list(asset_ids)))


def _pointer() -> EvidencePointer:
    return EvidencePointer(source="upload", locator="upload :: x.png")


def _png_bytes(size: int = 16) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (size, size), (10, 20, 30))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _evidence(*asset_ids: str, kind: str = "logo") -> BrandEvidence:
    logos = []
    images = []
    for asset_id in asset_ids:
        if kind == "logo":
            logos.append(LogoEvidence(asset_id=asset_id, pointer=_pointer()))
        else:
            images.append(
                ImageEvidence(asset_id=asset_id, kind_hint="photo", pointer=_pointer())
            )
    return BrandEvidence(
        source={"kind": "logo_file", "confidence": 0.8},
        logos=logos,
        images=images,
    )


class _ScriptedDescriber:
    """Returns a canned DescribeResult per item; records call count + batch sizes."""

    def __init__(self) -> None:
        self.calls = 0
        self.batch_sizes: list[int] = []
        self.seen_ids: list[str] = []

    def describe(self, items):
        self.calls += 1
        self.batch_sizes.append(len(items))
        results = []
        for item in items:
            self.seen_ids.append(item.asset_id)
            results.append(
                DescribeResult(
                    asset_id=item.asset_id,
                    title=f"Title {item.asset_id}",
                    description=f"A caption for {item.asset_id}.",
                    usage="Use on light backgrounds.",
                    tags=["mark", "brand"],
                )
            )
        return results


class _CountingNull:
    def __init__(self) -> None:
        self.calls = 0

    def describe(self, items):
        self.calls += 1
        return [None] * len(items)


class _ReasonedNull:
    """A describer that returns nothing but records WHY (as OpenRouterDescriber
    does), so the orchestrator can thread the reason into LUMI0803."""

    active = True

    def __init__(self, reason: str) -> None:
        self.last_failure_reason = reason

    def describe(self, items):
        return [None] * len(items)


# --------------------------------------------------------------------------- #
# NullDescriber no-op
# --------------------------------------------------------------------------- #


def test_null_describer_returns_all_none() -> None:
    items = [
        DescribeItem("a", "logo", "", None, "ctx"),
        DescribeItem("b", "photo", "", None, "ctx"),
    ]
    assert NullDescriber().describe(items) == [None, None]


def test_apply_with_null_describer_is_noop(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    _register(connection, "asset_ing_a")
    evidence = _evidence("asset_ing_a")
    resolved = {"asset_ing_a": (_png_bytes(), "image/png")}
    result = apply_descriptions(
        evidence,
        connection=connection,
        describer=NullDescriber(),
        resolve_bytes=lambda aid: resolved.get(aid),
        reporter=_noop,
    )
    assert result.logos[0].title is None
    assert result.logos[0].description is None
    # No rows written.
    assert _description_count(connection, "asset_ing_a") == 0


# --------------------------------------------------------------------------- #
# Scripted describer → stamping + put_ai rows
# --------------------------------------------------------------------------- #


def test_scripted_describer_stamps_and_persists(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    _register(connection, "asset_ing_a")
    evidence = _evidence("asset_ing_a")
    resolved = {"asset_ing_a": (_png_bytes(), "image/png")}
    describer = _ScriptedDescriber()
    result = apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: resolved.get(aid),
        reporter=_noop,
    )
    logo = result.logos[0]
    assert logo.title == "Title asset_ing_a"
    assert logo.description == "A caption for asset_ing_a."
    assert logo.usage_note == "Use on light backgrounds."
    assert logo.tags == ["mark", "brand"]

    row = _stored(connection, "asset_ing_a")
    assert row["title"] == "Title asset_ing_a"
    assert row["usage"] == "Use on light backgrounds."
    assert row["origin"] == "ai"
    assert row["model"]


# --------------------------------------------------------------------------- #
# Cache hit short-circuits the describer
# --------------------------------------------------------------------------- #


def test_cache_hit_skips_describer(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    _register(connection, "asset_ing_cached")
    store = DescriptionStore(connection, now_iso=_frozen_clock())
    store.put_ai(
        DescribeResult("asset_ing_cached", "Cached", "Cached desc.", "Cached usage.", ["x"]),
        "some/model",
    )
    evidence = _evidence("asset_ing_cached")
    describer = _CountingNull()
    result = apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        reporter=_noop,
    )
    # Cached id stamped from the store; describer never invoked.
    assert describer.calls == 0
    assert result.logos[0].title == "Cached"
    assert result.logos[0].description == "Cached desc."
    assert result.logos[0].usage_note == "Cached usage."


# --------------------------------------------------------------------------- #
# Human row protection
# --------------------------------------------------------------------------- #


def test_put_ai_never_overwrites_human(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    _register(connection, "asset_ing_h")
    store = DescriptionStore(connection, now_iso=_frozen_clock())
    store.put_human("asset_ing_h", "Human title", "Human desc.", "Human usage.", ["h"])
    store.put_ai(
        DescribeResult("asset_ing_h", "AI title", "AI desc.", "AI usage.", ["ai"]),
        "some/model",
    )
    row = _stored(connection, "asset_ing_h")
    assert row["origin"] == "human"
    assert row["title"] == "Human title"
    assert row["description"] == "Human desc."
    assert row["usage"] == "Human usage."


# --------------------------------------------------------------------------- #
# Batching: 17 items → 3 calls of 8/8/1
# --------------------------------------------------------------------------- #


def test_per_item_isolation_17_items_17_calls(tmp_path: Path) -> None:
    # Imagery slice 1: one describe call PER asset — a timeout or malformed
    # image costs exactly one caption, never a batch (the old batch-of-8 lost
    # 7 innocent descriptions per failure; the cache makes per-image latency a
    # once-per-lifetime cost).
    connection = _connection(tmp_path)
    asset_ids = [f"asset_ing_{i:02d}" for i in range(17)]
    _register(connection, *asset_ids)
    evidence = _evidence(*asset_ids)
    describer = _ScriptedDescriber()
    apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        reporter=_noop,
    )
    assert describer.calls == 17
    assert describer.batch_sizes == [1] * 17


# --------------------------------------------------------------------------- #
# SVG skipped (no preview renderer in v1)
# --------------------------------------------------------------------------- #


def test_svg_skipped(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    _register(connection, "asset_ing_svg")
    evidence = _evidence("asset_ing_svg")
    svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    describer = _ScriptedDescriber()
    result = apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: (svg_bytes, "image/svg+xml"),
        reporter=_noop,
    )
    assert describer.calls == 0
    assert result.logos[0].title is None
    assert _description_count(connection, "asset_ing_svg") == 0


# --------------------------------------------------------------------------- #
# Unresolvable bytes are skipped
# --------------------------------------------------------------------------- #


def test_unresolvable_bytes_skipped(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    evidence = _evidence("asset_ing_missing")
    describer = _ScriptedDescriber()
    result = apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: None,
        reporter=_noop,
    )
    assert describer.calls == 0
    assert result.logos[0].title is None


# --------------------------------------------------------------------------- #
# Describer failure → skip silently, evidence unchanged
# --------------------------------------------------------------------------- #


def test_describer_failure_leaves_evidence_unchanged(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    _register(connection, "asset_ing_a")
    evidence = _evidence("asset_ing_a")

    class _Boom:
        def describe(self, items):
            raise RuntimeError("model down")

    result = apply_descriptions(
        evidence,
        connection=connection,
        describer=_Boom(),
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        reporter=_noop,
    )
    assert result.logos[0].title is None
    assert _description_count(connection, "asset_ing_a") == 0


# --------------------------------------------------------------------------- #
# Migration idempotence (fresh + reopen)
# --------------------------------------------------------------------------- #


def test_migration_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "api.sqlite3"
    run_migrations(database_path)
    connection = connect(database_path)
    _register(connection, "asset_ing_a")
    store = DescriptionStore(connection, now_iso=_frozen_clock())
    store.put_ai(DescribeResult("asset_ing_a", "T", "D.", "U.", []), "m")
    connection.close()

    # Re-run the SQLite migrations and reopen: the description (Postgres since D2.3, keyed on
    # the workspace rather than this file) is unaffected and still readable.
    run_migrations(database_path)
    reopened = connect(database_path)
    assert _stored(reopened, "asset_ing_a")["title"] == "T"


# --------------------------------------------------------------------------- #
# Import hygiene: describe pulls neither PIL nor httpx at import time
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# emit.py stamping: title/description/style_tags on kit assets
# --------------------------------------------------------------------------- #

_CREATED_AT = "2026-07-05"


def _stamped_evidence() -> BrandEvidence:
    return BrandEvidence(
        source={"kind": "logo_file", "asset_id": "asset_ing_logo", "filename": "logo.png", "confidence": 0.8},
        colors=[
            {
                "value": "#3B5BDB",
                "weight": 2.0,
                "theme": "light",
                "role_hints": ["accent"],
                "pointer": {"source": "upload", "locator": "upload :: logo.png"},
            }
        ],
        logos=[
            LogoEvidence(
                asset_id="asset_ing_logo",
                usage_hint="primary",
                title="Primary wordmark",
                description="A blue wordmark reading Insight.",
                usage_note="Use on light backgrounds at 24px min.",
                tags=["wordmark", "blue"],
                pointer=_pointer(),
            )
        ],
        images=[
            ImageEvidence(
                asset_id="asset_ing_img",
                kind_hint="photo",
                title="Clinic hero",
                description="A bright clinic reception photo.",
                usage_note="Crop for banners.",
                tags=["photo", "hero"],
                pointer=_pointer(),
            )
        ],
    )


def _normalize(evidence: BrandEvidence):
    return normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_ingest_stamp",
        version=1,
        name="Stamped kit",
        created_at=_CREATED_AT,
    )


def test_emit_stamps_title_description_and_style_tags() -> None:
    result = _normalize(_stamped_evidence())
    logos = result.brand_kit["assets"]["logos"]
    primary = logos["primary"]
    assert primary["title"] == "Primary wordmark"
    # Imagery slice 1: usage guidance is its OWN field — never folded into the
    # description a downstream cap can eat.
    assert primary["description"] == "A blue wordmark reading Insight."
    assert primary["usage_note"] == "Use on light backgrounds at 24px min."

    images = result.brand_kit["assets"]["images"]
    img = images["img.1"]
    assert img["title"] == "Clinic hero"
    assert img["description"] == "A bright clinic reception photo."
    assert img["usage_note"] == "Crop for banners."
    # tags merged into style_tags (deduped, sorted, after existing []).
    assert img["style_tags"] == ["hero", "photo"]


def test_emit_omits_fields_when_absent() -> None:
    # Evidence without descriptions → keys OMITTED (not null) from kit JSON.
    evidence = BrandEvidence(
        source={"kind": "logo_file", "asset_id": "asset_ing_logo", "filename": "logo.png", "confidence": 0.8},
        logos=[LogoEvidence(asset_id="asset_ing_logo", usage_hint="primary", pointer=_pointer())],
        images=[ImageEvidence(asset_id="asset_ing_img", kind_hint="photo", pointer=_pointer())],
    )
    result = _normalize(evidence)
    primary = result.brand_kit["assets"]["logos"]["primary"]
    assert "title" not in primary
    assert "description" not in primary
    img = result.brand_kit["assets"]["images"]["img.1"]
    assert "title" not in img
    assert "description" not in img
    assert img["style_tags"] == []


# --------------------------------------------------------------------------- #
# Engine round-trip: stamped kit validates (proves the new Rust fields)
# --------------------------------------------------------------------------- #


def test_stamped_kit_round_trip_validates() -> None:
    if not os.environ.get("LUMEN_CORE_HELPER"):
        pytest.skip("LUMEN_CORE_HELPER not set")
    result = _normalize(_stamped_evidence())
    core = CoreClient()
    validated = core.validate_brand_kit(result.brand_kit, product_ready=False)
    assert validated["ok"] is True
    errors = [d for d in validated.get("diagnostics", []) if d.get("severity") == "error"]
    assert errors == []
    # Imagery slice 1 keystone: usage_note is a FIRST-CLASS engine field — it
    # must survive the typed validation round trip (an untyped extra would be
    # silently dropped on re-serialize, exactly the class this slice kills).
    kit = validated["brand_kit"]
    assert kit["assets"]["logos"]["primary"]["usage_note"] == (
        "Use on light backgrounds at 24px min."
    )
    assert kit["assets"]["images"]["img.1"]["usage_note"] == "Crop for banners."


# --------------------------------------------------------------------------- #
# Imagery slice 1: per-item isolation, named diagnostics, SVG seam, summary
# --------------------------------------------------------------------------- #


class _FailsOnDescriber(_ScriptedDescriber):
    """Scripted describer that raises for one specific asset id."""

    def __init__(self, failing_asset_id: str) -> None:
        super().__init__()
        self.failing_asset_id = failing_asset_id

    def describe(self, items):
        if any(item.asset_id == self.failing_asset_id for item in items):
            self.calls += 1
            raise TimeoutError("simulated per-image timeout")
        return super().describe(items)


def test_one_failing_item_does_not_sink_the_rest(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    _register(connection, "asset_a", "asset_b", "asset_c")
    evidence = _evidence("asset_a", "asset_b", "asset_c")
    describer = _FailsOnDescriber("asset_b")
    sink: list[dict] = []
    result = apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        reporter=_noop,
        diagnostics=sink,
    )
    titles = {logo.asset_id: logo.title for logo in result.logos}
    assert titles["asset_a"] == "Title asset_a"
    assert titles["asset_c"] == "Title asset_c"
    assert titles["asset_b"] is None
    failures = [d for d in sink if d["code"] == "LUMI0803"]
    assert len(failures) == 1
    assert "asset_b" in failures[0]["message"]
    assert failures[0]["severity"] == "warning"


def test_every_undescribed_asset_gets_a_named_diagnostic(tmp_path: Path) -> None:
    # LUMI0805 for unresolvable bytes; LUMI0804 for an SVG with no rasterizer.
    connection = _connection(tmp_path)
    _register(connection, "asset_missing", "asset_svg")
    evidence = _evidence("asset_missing", "asset_svg")
    svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'

    def resolve(asset_id: str):
        if asset_id == "asset_missing":
            return None
        return (svg_bytes, "image/svg+xml")

    sink: list[dict] = []
    apply_descriptions(
        evidence,
        connection=connection,
        describer=_ScriptedDescriber(),
        resolve_bytes=resolve,
        reporter=_noop,
        diagnostics=sink,
    )
    codes = {d["code"] for d in sink}
    assert codes == {"LUMI0805", "LUMI0804"}
    by_code = {d["code"]: d["message"] for d in sink}
    assert "asset_missing" in by_code["LUMI0805"]
    assert "asset_svg" in by_code["LUMI0804"]


def test_svg_described_through_rasterize_seam(tmp_path: Path) -> None:
    # With the engine-rasterizer seam supplied, an SVG is described like any
    # raster — no diagnostic, row persisted.
    connection = _connection(tmp_path)
    _register(connection, "asset_svg")
    evidence = _evidence("asset_svg")
    svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    sink: list[dict] = []
    result = apply_descriptions(
        evidence,
        connection=connection,
        describer=_ScriptedDescriber(),
        resolve_bytes=lambda aid: (svg_bytes, "image/svg+xml"),
        reporter=_noop,
        rasterize_svg=lambda aid: _png_bytes(),
        diagnostics=sink,
    )
    assert result.logos[0].title == "Title asset_svg"
    assert sink == []


def test_inactive_describer_skips_misses_without_failure_spam(tmp_path: Path) -> None:
    # Describe OFF (NullDescriber.active=False) is OFF — zero calls, zero
    # diagnostics, not N per-asset failures.
    connection = _connection(tmp_path)
    _register(connection, "asset_a", "asset_b")
    evidence = _evidence("asset_a", "asset_b")
    describer = _CountingNull()
    describer.active = False
    sink: list[dict] = []
    apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        reporter=_noop,
        diagnostics=sink,
    )
    assert describer.calls == 0
    assert sink == []


def test_reporter_carries_described_summary(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    _register(connection, "asset_a", "asset_b", "asset_c")
    evidence = _evidence("asset_a", "asset_b", "asset_c")
    stages: list[str] = []

    def reporter(stage: str, progress: float) -> None:
        stages.append(stage)

    apply_descriptions(
        evidence,
        connection=connection,
        describer=_FailsOnDescriber("asset_c"),
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        reporter=reporter,
    )
    assert stages[-1] == "Asset descriptions: 2/3 (2 new, 0 cached, 1 failed)"


# --------------------------------------------------------------------------- #
# Imagery slice 1: kit-level backfill (describe_kit_assets)
# --------------------------------------------------------------------------- #


def _backfill_kit() -> dict:
    return {
        "id": "brand_kit_backfill",
        "version": 3,
        "assets": {
            "logos": {
                "primary": {
                    "usage": "primary",
                    "variants": [{"asset_id": "asset_logo", "name": "full_color"}],
                }
            },
            "images": {
                "img.1": {"asset_id": "asset_photo", "role": "photo"},
                "img.2": {"asset_id": "asset_photo_described", "role": "photo"},
            },
        },
    }


def test_describe_kit_assets_backfills_and_counts(tmp_path: Path) -> None:
    from lumen_ingestion.describe import describe_kit_assets

    connection = _connection(tmp_path)
    _register(connection, "asset_logo", "asset_photo", "asset_photo_described")
    # One asset already described (any origin) → cache hit, no model call.
    DescriptionStore(connection, now_iso=_frozen_clock()).put_human(
        "asset_photo_described",
        "Existing title",
        "Existing caption.",
        "Existing guidance.",
        ["photo"],
    )
    kit = _backfill_kit()
    describer = _ScriptedDescriber()
    sink: list[dict] = []
    counts = describe_kit_assets(
        kit,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        diagnostics=sink,
        brand_name="Backfill Brand",
    )
    assert counts == {
        "total": 3,
        "cached": 1,
        "described": 2,
        "failed": 0,
        "failures": {},
    }
    assert sink == []
    # Misses stamped from fresh describe results — usage_note its own field.
    logo = kit["assets"]["logos"]["primary"]
    assert logo["title"] == "Title asset_logo"
    assert logo["usage_note"] == "Use on light backgrounds."
    img = kit["assets"]["images"]["img.1"]
    assert img["description"] == "A caption for asset_photo."
    # Cache hit stamped from the store (human row protected and reused).
    cached_img = kit["assets"]["images"]["img.2"]
    assert cached_img["title"] == "Existing title"
    assert cached_img["usage_note"] == "Existing guidance."


def test_describe_kit_assets_inactive_describer_only_stamps_cache(
    tmp_path: Path,
) -> None:
    from lumen_ingestion.describe import describe_kit_assets

    connection = _connection(tmp_path)
    _register(connection, "asset_logo", "asset_photo", "asset_photo_described")
    DescriptionStore(connection, now_iso=_frozen_clock()).put_human(
        "asset_photo_described", "Existing title", None, None, []
    )
    kit = _backfill_kit()
    describer = _CountingNull()
    describer.active = False
    counts = describe_kit_assets(
        kit,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
    )
    assert describer.calls == 0
    assert counts == {
        "total": 3,
        "cached": 1,
        "described": 0,
        "failed": 0,
        "failures": {},
    }
    assert kit["assets"]["images"]["img.2"]["title"] == "Existing title"
    assert "title" not in kit["assets"]["images"]["img.1"]


# --------------------------------------------------------------------------- #
# Imagery slice 1: emit dedups images by asset id
# --------------------------------------------------------------------------- #


def test_emit_dedups_images_by_asset_id() -> None:
    evidence = BrandEvidence(
        source={"kind": "logo_file", "asset_id": "asset_ing_logo", "filename": "logo.png", "confidence": 0.8},
        logos=[LogoEvidence(asset_id="asset_ing_logo", usage_hint="primary", pointer=_pointer())],
        images=[
            ImageEvidence(
                asset_id="asset_dup",
                kind_hint="photo",
                tags=["hero"],
                pointer=_pointer(),
            ),
            ImageEvidence(
                asset_id="asset_other",
                kind_hint="photo",
                pointer=_pointer(),
            ),
            ImageEvidence(
                asset_id="asset_dup",
                kind_hint="photo",
                tags=["dashboard"],
                pointer=_pointer(),
            ),
        ],
    )
    result = _normalize(evidence)
    images = result.brand_kit["assets"]["images"]
    # One entry per unique asset — the live kit carried one asset under four
    # img.N keys, diluting the agent's image inventory.
    asset_ids = [entry["asset_id"] for entry in images.values()]
    assert sorted(asset_ids) == ["asset_dup", "asset_other"]
    assert set(images.keys()) == {"img.1", "img.2"}
    # The duplicate's tags still contribute to the surviving entry.
    dup_entry = next(e for e in images.values() if e["asset_id"] == "asset_dup")
    assert set(dup_entry["style_tags"]) == {"dashboard", "hero"}


# --------------------------------------------------------------------------- #
# Import hygiene: describe pulls neither PIL nor httpx at import time
# --------------------------------------------------------------------------- #


def test_import_pulls_no_pil_or_httpx() -> None:
    script = (
        "import sys, lumen_ingestion.describe as _; "
        "bad = [m for m in ('PIL', 'httpx') if m in sys.modules]; "
        "assert not bad, bad; print('clean')"
    )
    api_root = Path(__file__).resolve().parents[1]
    repo_root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(api_root), str(repo_root)])}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(api_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


# --------------------------------------------------------------------------- #
# Describe failures carry the reason (LUMI0803 no longer says bare "nothing")
# --------------------------------------------------------------------------- #


def test_apply_diagnostic_carries_the_failure_reason(tmp_path: Path) -> None:
    """When the describer records WHY it returned nothing, that reason is
    threaded into the LUMI0803 diagnostic instead of a bare 'returned
    nothing'."""
    connection = _connection(tmp_path)
    _register(connection, "asset_a")
    evidence = _evidence("asset_a")
    reason = "HTTP 429 (attempt 2): rate limited by upstream"
    sink: list[dict] = []
    apply_descriptions(
        evidence,
        connection=connection,
        describer=_ReasonedNull(reason),
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        reporter=_noop,
        diagnostics=sink,
    )
    failures = [d for d in sink if d["code"] == "LUMI0803"]
    assert len(failures) == 1
    assert reason in failures[0]["message"]


def test_backfill_summary_and_diagnostic_carry_the_reason(tmp_path: Path) -> None:
    """The kit-backfill path threads the failure reason into BOTH the LUMI0803
    diagnostic message AND the job summary (counts['failures'][asset_id])."""
    from lumen_ingestion.describe import describe_kit_assets

    connection = _connection(tmp_path)
    kit = {
        "assets": {
            "logos": {
                "primary": {"variants": [{"asset_id": "asset_logo"}]},
            },
            "images": {},
        }
    }
    reason = "HTTP 500 (attempt 2): upstream boom"
    sink: list[dict] = []
    counts = describe_kit_assets(
        kit,
        connection=connection,
        describer=_ReasonedNull(reason),
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        diagnostics=sink,
    )
    assert counts["failed"] == 1
    assert counts["failures"] == {"asset_logo": reason}
    failures = [d for d in sink if d["code"] == "LUMI0803"]
    assert len(failures) == 1
    assert reason in failures[0]["message"]


def test_openrouter_invoke_captures_http_status_and_body(monkeypatch) -> None:
    """OpenRouterDescriber._invoke records the HTTP status + a bounded body
    excerpt on failure, so the reason is available to the orchestrator."""
    from lumen_ingestion.describe import (
        FAILURE_EXCERPT_MAX,
        OpenRouterDescriber,
    )

    describer = OpenRouterDescriber()
    describer.enabled = True
    describer.api_key = "test-key"

    class _Resp:
        status_code = 503
        text = "upstream unavailable " + "x" * 1000

        def json(self):  # pragma: no cover - not reached on the 5xx path
            return {}

    def _fake_post(*args, **kwargs):
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", _fake_post)
    item = DescribeItem(
        asset_id="asset_a",
        kind="logo",
        image_b64="",
        filename=None,
        context="brand: X",
    )
    results = describer.describe([item])
    assert results == [None]
    assert describer.last_failure_reason is not None
    assert "HTTP 503" in describer.last_failure_reason
    assert "upstream unavailable" in describer.last_failure_reason
    # Bounded: the excerpt never floods the diagnostic.
    assert len(describer.last_failure_reason) <= FAILURE_EXCERPT_MAX + 40


def test_openrouter_invoke_captures_exception(monkeypatch) -> None:
    """A network exception is captured as class + message, not silently
    swallowed into a bare None."""
    from lumen_ingestion.describe import OpenRouterDescriber

    describer = OpenRouterDescriber()
    describer.enabled = True
    describer.api_key = "test-key"

    def _boom(*args, **kwargs):
        raise ConnectionError("connection reset by peer")

    import httpx

    monkeypatch.setattr(httpx, "post", _boom)
    item = DescribeItem(
        asset_id="asset_a", kind="logo", image_b64="", filename=None, context="x"
    )
    results = describer.describe([item])
    assert results == [None]
    assert describer.last_failure_reason is not None
    assert "ConnectionError" in describer.last_failure_reason
    assert "connection reset by peer" in describer.last_failure_reason
