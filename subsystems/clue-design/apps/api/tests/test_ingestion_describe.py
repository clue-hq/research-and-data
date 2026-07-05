from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import sqlite3
from pathlib import Path

import pytest

from lumen_api.core import CoreClient
from lumen_api.database import connect, run_migrations
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
    rows = connection.execute("SELECT COUNT(*) FROM asset_descriptions").fetchone()
    assert rows[0] == 0


# --------------------------------------------------------------------------- #
# Scripted describer → stamping + put_ai rows
# --------------------------------------------------------------------------- #


def test_scripted_describer_stamps_and_persists(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
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

    row = connection.execute(
        "SELECT title, usage, origin, model FROM asset_descriptions WHERE asset_id=?",
        ("asset_ing_a",),
    ).fetchone()
    assert row["title"] == "Title asset_ing_a"
    assert row["usage"] == "Use on light backgrounds."
    assert row["origin"] == "ai"
    assert row["model"]


# --------------------------------------------------------------------------- #
# Cache hit short-circuits the describer
# --------------------------------------------------------------------------- #


def test_cache_hit_skips_describer(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
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
    store = DescriptionStore(connection, now_iso=_frozen_clock())
    store.put_human("asset_ing_h", "Human title", "Human desc.", "Human usage.", ["h"])
    store.put_ai(
        DescribeResult("asset_ing_h", "AI title", "AI desc.", "AI usage.", ["ai"]),
        "some/model",
    )
    row = connection.execute(
        "SELECT title, description, usage, origin FROM asset_descriptions WHERE asset_id=?",
        ("asset_ing_h",),
    ).fetchone()
    assert row["origin"] == "human"
    assert row["title"] == "Human title"
    assert row["description"] == "Human desc."
    assert row["usage"] == "Human usage."


# --------------------------------------------------------------------------- #
# Batching: 17 items → 3 calls of 8/8/1
# --------------------------------------------------------------------------- #


def test_batching_17_items_three_calls(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    asset_ids = [f"asset_ing_{i:02d}" for i in range(17)]
    evidence = _evidence(*asset_ids)
    describer = _ScriptedDescriber()
    apply_descriptions(
        evidence,
        connection=connection,
        describer=describer,
        resolve_bytes=lambda aid: (_png_bytes(), "image/png"),
        reporter=_noop,
    )
    assert describer.calls == 3
    assert describer.batch_sizes == [8, 8, 1]


# --------------------------------------------------------------------------- #
# SVG skipped (no preview renderer in v1)
# --------------------------------------------------------------------------- #


def test_svg_skipped(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
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
    rows = connection.execute("SELECT COUNT(*) FROM asset_descriptions").fetchone()
    assert rows[0] == 0


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
    rows = connection.execute("SELECT COUNT(*) FROM asset_descriptions").fetchone()
    assert rows[0] == 0


# --------------------------------------------------------------------------- #
# Migration idempotence (fresh + reopen)
# --------------------------------------------------------------------------- #


def test_migration_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "api.sqlite3"
    run_migrations(database_path)
    connection = connect(database_path)
    store = DescriptionStore(connection, now_iso=_frozen_clock())
    store.put_ai(DescribeResult("asset_ing_a", "T", "D.", "U.", []), "m")
    connection.close()

    # Re-run migrations on the existing DB and reopen: the row survives.
    run_migrations(database_path)
    reopened = connect(database_path)
    row = reopened.execute(
        "SELECT title FROM asset_descriptions WHERE asset_id=?", ("asset_ing_a",)
    ).fetchone()
    assert row["title"] == "T"


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
    # description = caption + " Usage: " + usage_note
    assert primary["description"] == (
        "A blue wordmark reading Insight. Usage: Use on light backgrounds at 24px min."
    )

    images = result.brand_kit["assets"]["images"]
    img = images["img.1"]
    assert img["title"] == "Clinic hero"
    assert img["description"] == "A bright clinic reception photo. Usage: Crop for banners."
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


# --------------------------------------------------------------------------- #
# Import hygiene: describe pulls neither PIL nor httpx at import time
# --------------------------------------------------------------------------- #


def test_import_pulls_no_pil_or_httpx() -> None:
    script = (
        "import sys, lumen_ingestion.describe as _; "
        "bad = [m for m in ('PIL', 'httpx') if m in sys.modules]; "
        "assert not bad, bad; print('clean')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout
