"""Font library (Track B): provisioning helpers, runtime manifest access,
the CoreClient library-spec injection, and the GET /font-library endpoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen_api import font_library as runtime_library
from lumen_api.core import CoreClient
from lumen_api.main import create_app
from lumen_ingestion.font_library import (
    CURATED_FAMILIES,
    REQUIRED_GLYPHS,
    FontLibraryError,
    _instance_bytes,
    _ttfont,
    face_asset_id,
    glyph_coverage,
    render_agent_inventory,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER_REGULAR = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
CHECKED_IN_MANIFEST = REPO_ROOT / "apps" / "api" / "font-library" / "manifest.json"


# --- provisioning helpers ---------------------------------------------------


def test_curation_is_well_formed() -> None:
    slugs = [family.slug for family in CURATED_FAMILIES]
    assert len(slugs) == len(set(slugs)), "duplicate curation slugs"
    for family in CURATED_FAMILIES:
        assert family.weights, family.slug
        assert family.tone, family.slug
        assert family.category in {"sans", "serif", "slab", "mono", "display"}
        assert list(family.weights) == sorted(set(family.weights)), family.slug


def test_required_glyphs_cover_the_sweep_tofu_set() -> None:
    # The archetype baseline sweep shipped tofu for exactly these — they must
    # never leave the required set.
    for ch in ("/", "×", "—"):
        assert ch in REQUIRED_GLYPHS


def test_glyph_coverage_reports_missing_required() -> None:
    cmap = {ord(ch): "g" for ch in REQUIRED_GLYPHS if ch != "×"}
    report = glyph_coverage(cmap)
    assert report["required_ok"] is False
    assert report["missing_required"] == ["×"]

    full = {ord(ch): "g" for ch in REQUIRED_GLYPHS}
    assert glyph_coverage(full)["required_ok"] is True


def test_bundled_inter_covers_required_glyphs() -> None:
    report = glyph_coverage(_ttfont(INTER_REGULAR.read_bytes()).getBestCmap())
    assert report["required_ok"] is True, report["missing_required"]


def test_face_asset_id_is_deterministic_and_slug_safe() -> None:
    digest = "ab" * 32
    assert face_asset_id("dm-sans", 700, digest) == face_asset_id("dm-sans", 700, digest)
    assert face_asset_id("dm-sans", 700, digest).startswith("asset_font_lib_dm_sans_w700_")


def test_instance_bytes_rejects_static_sources() -> None:
    with pytest.raises(FontLibraryError, match="expected a variable source"):
        _instance_bytes(INTER_REGULAR.read_bytes(), 400, "Inter")


# --- runtime manifest access -------------------------------------------------


@pytest.fixture()
def manifest_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "manifest.json"
    monkeypatch.setattr(
        runtime_library.settings, "lumen_font_library_manifest_path", path
    )
    monkeypatch.setattr(
        runtime_library.settings, "lumen_asset_store_root", tmp_path / "store"
    )
    runtime_library._cache.update(path=None, mtime=None, manifest=None)
    runtime_library._spec_cache.update(key=None, spec=None)
    return path


def materialize_blob(tmp_path: Path, digest: str) -> None:
    blob = tmp_path / "store" / "sha256" / digest[:2] / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"font-bytes")


def write_manifest_fixture(path: Path, families: list) -> None:
    path.write_text(json.dumps({"version": 1, "families": families}))


def test_missing_manifest_disables_the_library(manifest_file: Path) -> None:
    assert runtime_library.manifest() is None
    assert runtime_library.library_font_spec() is None


def test_broken_manifest_disables_the_library(manifest_file: Path) -> None:
    manifest_file.write_text("{not json")
    assert runtime_library.manifest() is None
    assert runtime_library.library_font_spec() is None


def test_library_font_spec_flattens_materialized_faces(
    tmp_path: Path, manifest_file: Path
) -> None:
    write_manifest_fixture(
        manifest_file,
        [
            {
                "family": "DM Sans",
                "faces": [
                    {"weight": 400, "digest": "a" * 64, "asset_id": "x"},
                    {"weight": 700, "digest": "b" * 64, "asset_id": "y"},
                ],
            },
            {"family": "Empty Family", "faces": []},
        ],
    )
    materialize_blob(tmp_path, "a" * 64)
    materialize_blob(tmp_path, "b" * 64)
    spec = runtime_library.library_font_spec()
    assert spec is not None
    assert spec["store_root"] == str(tmp_path / "store")
    assert spec["faces"] == [
        {"digest": "a" * 64, "family": "DM Sans"},
        {"digest": "b" * 64, "family": "DM Sans"},
    ]


def test_library_font_spec_skips_unmaterialized_faces(
    tmp_path: Path, manifest_file: Path
) -> None:
    """A checked-in manifest over an unprovisioned store (fresh clone, test
    tmp dir) must degrade to the pre-library behavior — promising bytes the
    helper cannot read would spray LUMS0101 over every request whose kit
    merely mentions a library family name."""
    write_manifest_fixture(
        manifest_file,
        [
            {
                "family": "DM Sans",
                "faces": [
                    {"weight": 400, "digest": "a" * 64, "asset_id": "x"},
                    {"weight": 700, "digest": "b" * 64, "asset_id": "y"},
                ],
            }
        ],
    )
    materialize_blob(tmp_path, "b" * 64)
    spec = runtime_library.library_font_spec()
    assert spec is not None
    assert spec["faces"] == [{"digest": "b" * 64, "family": "DM Sans"}]

    # Nothing materialized → no spec at all (library disabled).
    runtime_library._spec_cache.update(key=None, spec=None)
    (tmp_path / "store" / "sha256" / "bb" / ("b" * 64)).unlink()
    assert runtime_library.library_font_spec() is None


def test_manifest_cache_refreshes_on_mtime_change(manifest_file: Path) -> None:
    import os

    write_manifest_fixture(manifest_file, [{"family": "A", "faces": []}])
    first = runtime_library.manifest()
    assert first is not None and first["families"][0]["family"] == "A"

    write_manifest_fixture(manifest_file, [{"family": "B", "faces": []}])
    # Force a distinct mtime even on coarse filesystems.
    stat = manifest_file.stat()
    os.utime(manifest_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = runtime_library.manifest()
    assert second is not None and second["families"][0]["family"] == "B"


# --- CoreClient injection ----------------------------------------------------


def test_core_client_injects_library_fonts_into_shaping_actions(
    manifest_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_manifest_fixture(
        manifest_file,
        [{"family": "DM Sans", "faces": [{"weight": 400, "digest": "c" * 64}]}],
    )
    materialize_blob(manifest_file.parent, "c" * 64)
    captured: dict = {}

    def fake_run(command, input, **kwargs):  # noqa: A002 - subprocess signature
        captured["request"] = json.loads(input)

        class Result:
            returncode = 0
            stdout = json.dumps({"ok": True, "diagnostics": []})
            stderr = ""

        return Result()

    monkeypatch.setattr("lumen_api.core.subprocess.run", fake_run)
    core = CoreClient()

    core.preflight_scene({"nodes": {}}, None)
    injected = captured["request"]["library_fonts"]
    assert injected["faces"] == [{"digest": "c" * 64, "family": "DM Sans"}]

    # Non-shaping actions are untouched.
    core.validate_scene({"nodes": {}})
    assert "library_fonts" not in captured["request"]

    # An explicit value (including None) is never overridden.
    core._run({"action": "preflight_scene", "library_fonts": None})
    assert captured["request"]["library_fonts"] is None


# --- endpoint ----------------------------------------------------------------


def test_font_library_endpoint_serves_manifest(
    tmp_path: Path, manifest_file: Path
) -> None:
    write_manifest_fixture(
        manifest_file,
        [{"family": "DM Sans", "slug": "dm-sans", "faces": [], "tone": ["geometric"]}],
    )
    client = TestClient(create_app(tmp_path / "api.sqlite3"))
    payload = client.get("/font-library").json()
    assert payload["families"][0]["family"] == "DM Sans"


def test_font_library_endpoint_empty_when_unprovisioned(
    tmp_path: Path, manifest_file: Path
) -> None:
    client = TestClient(create_app(tmp_path / "api.sqlite3"))
    assert client.get("/font-library").json() == {"version": 1, "families": []}


def test_checked_in_agent_inventory_matches_manifest() -> None:
    """The agent-facing inventory doc is generated from the manifest — a
    hand-edit or a stale regeneration would teach the agent fonts the engine
    cannot load (or hide ones it can)."""
    manifest = json.loads(CHECKED_IN_MANIFEST.read_text())
    doc = (
        REPO_ROOT
        / "apps/agent_runtime/knowledge_docs/knowledge/design/font-library.md"
    )
    assert doc.read_text() == render_agent_inventory(manifest)


def test_checked_in_manifest_matches_curation() -> None:
    """The committed manifest must stay in lockstep with the curation table —
    regenerate via scripts/provision_font_library.py after editing either."""
    manifest = json.loads(CHECKED_IN_MANIFEST.read_text())
    by_slug = {family["slug"]: family for family in manifest["families"]}
    assert set(by_slug) == {family.slug for family in CURATED_FAMILIES}
    for curated in CURATED_FAMILIES:
        entry = by_slug[curated.slug]
        assert entry["family"] == curated.family
        assert [face["weight"] for face in entry["faces"]] == list(curated.weights)
        assert entry["glyph_coverage"]["required_ok"] is True
        for face in entry["faces"]:
            assert len(face["digest"]) == 64
