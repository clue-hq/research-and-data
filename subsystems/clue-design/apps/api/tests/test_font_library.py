"""Font library (Track B): provisioning helpers, runtime manifest access,
the CoreClient library-spec injection, and the GET /font-library endpoint."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api import font_library as runtime_library
from lumen_api.core import CoreClient
from lumen_api.main import (
    brand_kit_font_spec,
    build_web_font_face_css,
    create_app,
)
from lumen_ingestion.font_library import (
    CURATED_FAMILIES,
    REQUIRED_GLYPHS,
    FontLibraryError,
    _find_italic_source,
    _find_variable_source,
    _instance_bytes,
    _static_instance_names,
    _ttfont,
    face_asset_id,
    glyph_coverage,
    render_agent_inventory,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER_REGULAR = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
CHECKED_IN_MANIFEST = REPO_ROOT / "apps" / "api" / "font-library" / "manifest.json"
GOOGLE_FONTS_REPO = REPO_ROOT / ".context" / "google-fonts"


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


def test_face_asset_id_italic_carries_style_token_without_disturbing_uprights() -> None:
    # A7b: italic ids get a `w<weight>i` token; upright ids are byte-identical
    # to pre-A7b (default style="normal", no suffix), so the existing manifest
    # entries never churn.
    digest = "cd" * 32
    upright = face_asset_id("fraunces", 400, digest)
    italic = face_asset_id("fraunces", 400, digest, "italic")
    assert upright == face_asset_id("fraunces", 400, digest, "normal")
    assert upright.startswith("asset_font_lib_fraunces_w400_")
    assert italic.startswith("asset_font_lib_fraunces_w400i_")
    assert upright != italic


def test_curated_italics_are_a_subset_of_curated_weights() -> None:
    # An italic weight must have an upright twin (loading + measure resolve the
    # upright first); an italic outside `weights` could not resolve a base face.
    for family in CURATED_FAMILIES:
        assert set(family.italic_weights) <= set(family.weights), family.slug
        assert list(family.italic_weights) == sorted(set(family.italic_weights)), (
            family.slug
        )


def test_checked_in_manifest_ships_the_curated_italic_faces() -> None:
    """22 italic faces (D4), each stamped style='italic' with an `i` asset id
    and a full-length digest — and the upright count is preserved."""
    manifest = json.loads(CHECKED_IN_MANIFEST.read_text())
    by_slug = {f["slug"]: f for f in manifest["families"]}
    italic_total = 0
    for curated in CURATED_FAMILIES:
        entry = by_slug[curated.slug]
        italic = [f for f in entry["faces"] if f.get("style") == "italic"]
        assert [f["weight"] for f in italic] == list(curated.italic_weights), curated.slug
        for face in italic:
            italic_total += 1
            assert face["style"] == "italic"
            assert f"_w{face['weight']}i_" in face["asset_id"], face["asset_id"]
            assert len(face["digest"]) == 64
    assert italic_total == 22


def test_agent_inventory_has_italics_column() -> None:
    manifest = json.loads(CHECKED_IN_MANIFEST.read_text())
    doc = render_agent_inventory(manifest)
    assert "| Family | Weights | Italics | Tone | Use |" in doc
    # A family with italics lists its italic weights; the preamble addresses
    # italics + the missing-face advisory.
    assert "italic" in doc.lower()
    assert "LUMS0105" in doc
    # Fraunces carries 400 + 600 italics; its row must show both.
    fraunces_row = next(
        line for line in doc.splitlines() if line.startswith("| Fraunces |")
    )
    assert "400, 600" in fraunces_row
    # Display faces carry no italics — the em-dash placeholder appears.
    anton_row = next(line for line in doc.splitlines() if line.startswith("| Anton |"))
    assert "| — |" in anton_row


def test_agent_inventory_weights_column_excludes_italics() -> None:
    # The Weights column must count upright faces only; italic faces reuse
    # curated weights, so an unfiltered column would double-list them.
    manifest = {
        "families": [
            {
                "slug": "x",
                "family": "X",
                "category": "serif",
                "tone": ["t"],
                "pairing": "p",
                "faces": [
                    {"weight": 400, "style": "normal"},
                    {"weight": 700, "style": "normal"},
                    {"weight": 400, "style": "italic"},
                ],
            }
        ]
    }
    row = next(
        line
        for line in render_agent_inventory(manifest).splitlines()
        if line.startswith("| X |")
    )
    # Weights: "400, 700" (uprights), Italics: "400".
    assert "| X | 400, 700 | 400 |" in row


def test_instance_bytes_rejects_static_sources() -> None:
    with pytest.raises(FontLibraryError, match="expected a variable source"):
        _instance_bytes(INTER_REGULAR.read_bytes(), 400, "Inter")


# --- static-instance name hygiene ---------------------------------------------
# instancer.instantiateVariableFont leaves the variable source's name records
# behind: every Hanken weight shipped calling itself "Regular" and every
# Bricolage weight "96pt ExtraBold" — which is what PDF font lists (and a print
# shop's preflight) display for the embedded face.


def test_static_instance_names_ribbi_faces_use_style_linked_records() -> None:
    # The four RIBBI styles carry the style in nameID 2 and omit 16/17.
    for weight, italic, subfamily, ps in (
        (400, False, "Regular", "HankenGrotesk-Regular"),
        (700, False, "Bold", "HankenGrotesk-Bold"),
        (400, True, "Italic", "HankenGrotesk-Italic"),
        (700, True, "Bold Italic", "HankenGrotesk-BoldItalic"),
    ):
        names = _static_instance_names("Hanken Grotesk", weight, italic)
        assert names[1] == "Hanken Grotesk"
        assert names[2] == subfamily
        assert names[4] == f"Hanken Grotesk {subfamily}"
        assert names[6] == ps
        assert 16 not in names and 17 not in names


def test_static_instance_names_non_ribbi_faces_carry_typographic_records() -> None:
    names = _static_instance_names("Bricolage Grotesque", 800, False)
    assert names[1] == "Bricolage Grotesque ExtraBold"
    assert names[2] == "Regular"
    assert names[4] == "Bricolage Grotesque ExtraBold"
    assert names[6] == "BricolageGrotesque-ExtraBold"
    assert names[16] == "Bricolage Grotesque"
    assert names[17] == "ExtraBold"

    italic = _static_instance_names("Fraunces", 600, True)
    assert italic[1] == "Fraunces SemiBold"
    assert italic[2] == "Italic"
    assert italic[6] == "Fraunces-SemiBoldItalic"
    assert italic[17] == "SemiBold Italic"


needs_fonts_repo = pytest.mark.skipif(
    not GOOGLE_FONTS_REPO.is_dir(),
    reason="pinned google-fonts clone not present (.context/google-fonts)",
)


def _instanced_font(family_slug: str, weight: int, italic: bool = False):
    curated = next(f for f in CURATED_FAMILIES if f.slug == family_slug)
    directory = GOOGLE_FONTS_REPO / curated.directory
    finder = _find_italic_source if italic else _find_variable_source
    source = finder(directory, curated.family)
    assert source is not None, f"no variable source for {family_slug}"
    return _ttfont(
        _instance_bytes(source.read_bytes(), weight, curated.family, italic=italic)
    ), curated.family


@needs_fonts_repo
def test_instanced_faces_are_named_after_their_instance() -> None:
    # The two live offenders: Hanken 700 said "Regular", Bricolage 800 said
    # "96pt ExtraBold" (with the same lie at 400/600/700).
    font, _ = _instanced_font("hanken-grotesk", 700)
    name = font["name"]
    assert name.getDebugName(1) == "Hanken Grotesk"
    assert name.getDebugName(2) == "Bold"
    assert name.getDebugName(4) == "Hanken Grotesk Bold"
    assert name.getDebugName(6) == "HankenGrotesk-Bold"
    assert name.getDebugName(16) is None and name.getDebugName(17) is None
    assert name.getDebugName(25) is None  # variations PS prefix must not survive
    assert font["OS/2"].fsSelection & 0x0020  # BOLD
    assert not font["OS/2"].fsSelection & 0x0040  # not REGULAR
    assert font["head"].macStyle == 0b01

    font, _ = _instanced_font("bricolage-grotesque", 800)
    name = font["name"]
    assert name.getDebugName(1) == "Bricolage Grotesque ExtraBold"
    assert name.getDebugName(2) == "Regular"
    assert name.getDebugName(6) == "BricolageGrotesque-ExtraBold"
    assert name.getDebugName(16) == "Bricolage Grotesque"
    assert name.getDebugName(17) == "ExtraBold"
    assert "96pt" not in (name.getDebugName(3) or "")
    assert font["OS/2"].fsSelection & 0x0040  # REGULAR (boldness is usWeightClass)
    assert font["OS/2"].usWeightClass == 800


@needs_fonts_repo
def test_instanced_italic_faces_carry_italic_names_and_bits() -> None:
    font, _ = _instanced_font("hanken-grotesk", 400, italic=True)
    name = font["name"]
    assert name.getDebugName(1) == "Hanken Grotesk"
    assert name.getDebugName(2) == "Italic"
    assert name.getDebugName(6) == "HankenGrotesk-Italic"
    assert font["OS/2"].fsSelection & 0x0001  # ITALIC
    assert font["head"].macStyle == 0b10

    font, _ = _instanced_font("fraunces", 600, italic=True)
    name = font["name"]
    assert name.getDebugName(1) == "Fraunces SemiBold"
    assert name.getDebugName(2) == "Italic"
    assert name.getDebugName(6) == "Fraunces-SemiBoldItalic"
    assert name.getDebugName(17) == "SemiBold Italic"


@needs_fonts_repo
def test_instancing_preserves_use_typo_metrics_bit() -> None:
    # The rewrite owns only the RIBBI bits; USE_TYPO_METRICS (bit 7) comes
    # from the source and changing it would shift line metrics everywhere.
    font, _ = _instanced_font("hanken-grotesk", 400)
    assert font["OS/2"].fsSelection & 0x0080


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
    """Give a manifest face DURABLE bytes in the library workspace (D4).

    The library's faces live in platform storage like every other design byte; `library_font_spec`
    materializes them into the library workspace's engine cache on demand. Seeding the CACHE
    directly would not prove anything about custody — but note the digest here is fixture hex
    (`"a"*64`), not the content address of `b"font-bytes"`, so the row is written under the
    fixture digest deliberately: `library_font_spec` resolves faces by the digest the manifest
    names, never by re-hashing."""
    from clue_design import storage as design_storage
    from clue_storage import storage_from_settings

    from lumen_api.design_store import DesignStoreBridge, default_workspace_id

    workspace_id = default_workspace_id()
    backend = storage_from_settings()
    bridge = DesignStoreBridge(workspace_id)
    key = design_storage.design_storage_key(workspace_id, digest)

    async def _write(conn):
        from clue_storage.artifacts import record_artifact

        await record_artifact(
            conn,
            storage_key=key,
            workspace_id=workspace_id,
            content_sha256=digest,
            media_type="font/ttf",
            size_bytes=len(b"font-bytes"),
            source_key=design_storage.SOURCE_KEY_FONT,
        )
        await backend.put(key, b"font-bytes", media_type="font/ttf")

    bridge._run(_write)


def _destroy_blob(digest: str) -> None:
    """Erase a library face's durable custody (D4) — the "unprovisioned environment" state."""
    from clue_storage import storage_from_settings

    from lumen_api.design_store import DesignBlobStore, default_workspace_id

    DesignBlobStore(storage_from_settings(), default_workspace_id()).delete(digest)


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
    # D4: the spec points the engine at the LIBRARY workspace's materialization cache.
    assert spec["store_root"] == str(
        tmp_path / "store" / runtime_library.library_workspace_id()
    )
    assert spec["faces"] == [
        {"digest": "a" * 64, "family": "DM Sans", "weight": 400},
        {"digest": "b" * 64, "family": "DM Sans", "weight": 700},
    ]


def test_library_font_spec_forwards_per_face_weight_and_style(
    tmp_path: Path, manifest_file: Path
) -> None:
    """Manifest faces carry weight+style; the spec must forward them so the
    helper / web @font-face render each face at its true weight instead of
    collapsing every face to 400/normal. Out-of-range values are dropped."""
    write_manifest_fixture(
        manifest_file,
        [
            {
                "family": "DM Sans",
                "faces": [
                    {"weight": 700, "style": "italic", "digest": "a" * 64, "asset_id": "x"},
                    # Bogus weight/style are omitted (consumer defaults 400/normal).
                    {"weight": 5000, "style": "oblique", "digest": "b" * 64, "asset_id": "y"},
                ],
            }
        ],
    )
    materialize_blob(tmp_path, "a" * 64)
    materialize_blob(tmp_path, "b" * 64)
    spec = runtime_library.library_font_spec()
    assert spec is not None
    assert spec["faces"] == [
        {"digest": "a" * 64, "family": "DM Sans", "weight": 700, "style": "italic"},
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
    assert spec["faces"] == [{"digest": "b" * 64, "family": "DM Sans", "weight": 700}]

    # Nothing durable → no spec at all (library disabled). D4: destroy the DURABLE bytes and
    # the cache mirror the first call materialized — a cache copy alone must not keep a face
    # "provisioned" once its custody is gone.
    runtime_library._spec_cache.update(key=None, spec=None)
    _destroy_blob("b" * 64)
    (
        tmp_path
        / "store"
        / runtime_library.library_workspace_id()
        / "sha256"
        / "bb"
        / ("b" * 64)
    ).unlink()
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
    assert injected["faces"] == [{"digest": "c" * 64, "family": "DM Sans", "weight": 400}]

    # derive_instance shapes and renders bulk artifacts: it MUST receive the
    # library spec (its omission was the silent-Inter bulk-export bug), and
    # the brand_fonts passthrough must survive alongside the injection.
    core.derive_instance(
        {"nodes": {}},
        {"binding_set_id": "bind_test"},
        brand_fonts={"store_root": "/tmp/store", "faces": []},
    )
    assert captured["request"]["library_fonts"]["faces"] == [
        {"digest": "c" * 64, "family": "DM Sans", "weight": 400}
    ]
    assert captured["request"]["brand_fonts"] == {
        "store_root": "/tmp/store",
        "faces": [],
    }

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
    client = make_client(create_app(tmp_path / "engine-cache"))
    payload = client.get("/font-library").json()
    assert payload["families"][0]["family"] == "DM Sans"


def test_font_library_endpoint_empty_when_unprovisioned(
    tmp_path: Path, manifest_file: Path
) -> None:
    client = make_client(create_app(tmp_path / "engine-cache"))
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
        upright = [f for f in entry["faces"] if f.get("style", "normal") == "normal"]
        italic = [f for f in entry["faces"] if f.get("style") == "italic"]
        assert [face["weight"] for face in upright] == list(curated.weights)
        # A7b: italic faces (if any) follow the uprights and match the curation.
        assert [face["weight"] for face in italic] == list(curated.italic_weights)
        assert all(f.get("style") == "italic" for f in italic)
        # Uprights precede italics in face order.
        styles = [f.get("style", "normal") for f in entry["faces"]]
        assert styles == sorted(styles, key=lambda s: s == "italic")
        assert entry["glyph_coverage"]["required_ok"] is True
        for face in entry["faces"]:
            assert len(face["digest"]) == 64


# --- kit font spec: per-face weight/style ------------------------------------


class _NullBlobStore:
    """A blob store with nothing in it — D4 materialization is fail-SOFT, so a spec is still
    produced for faces whose bytes are durably absent (the helper then reports LUMS0101)."""

    workspace_id = "ws_fake"

    def read(self, sha256: str) -> bytes:
        from lumen_api.database import NotFoundError

        raise NotFoundError("design_blob", sha256)


class _FakeAssetRepo:
    """Minimal store stand-in: brand_kit_font_spec only calls
    require_asset_record, which we resolve from a preloaded digest map."""

    def __init__(self, records: dict) -> None:
        self._records = records

    def require_asset_record(self, asset_id: str) -> dict:
        return self._records[asset_id]


def _asset_record(digest: str) -> dict:
    return {"asset": {"media": {"digest": {"algorithm": "sha256", "value": digest}}}}


def _kit_with_faces(faces: list) -> dict:
    return {"assets": {"fonts": {"heading": {"family": "Aeonik", "faces": faces}}}}


def test_brand_kit_font_spec_carries_per_face_weight_and_style() -> None:
    repo = _FakeAssetRepo(
        {"a1": _asset_record("a" * 64), "a2": _asset_record("b" * 64)}
    )
    kit = _kit_with_faces(
        [
            {"asset_id": "a1", "weight": 700, "style": "italic"},
            {"asset_id": "a2", "weight": 300, "style": "normal"},
        ]
    )
    spec = brand_kit_font_spec(repo, kit, _NullBlobStore(), "/store")
    assert spec == {
        "store_root": "/store",
        "faces": [
            {"digest": "a" * 64, "family": "Aeonik", "weight": 700, "style": "italic"},
            {"digest": "b" * 64, "family": "Aeonik", "weight": 300, "style": "normal"},
        ],
    }


def test_brand_kit_font_spec_omits_invalid_weight_and_style() -> None:
    """Out-of-range weight, a bool weight, and a non-css style are dropped —
    the key is omitted so the consumer defaults 400/normal (no invented value).
    A missing weight/style is likewise omitted, not defaulted here."""
    repo = _FakeAssetRepo(
        {
            "a1": _asset_record("a" * 64),
            "a2": _asset_record("b" * 64),
            "a3": _asset_record("c" * 64),
        }
    )
    kit = _kit_with_faces(
        [
            {"asset_id": "a1", "weight": 5000, "style": "oblique"},
            {"asset_id": "a2", "weight": True, "style": "italic"},
            {"asset_id": "a3"},  # no weight/style at all
        ]
    )
    spec = brand_kit_font_spec(repo, kit, _NullBlobStore(), "/store")
    assert spec is not None
    assert spec["faces"] == [
        {"digest": "a" * 64, "family": "Aeonik"},
        {"digest": "b" * 64, "family": "Aeonik", "style": "italic"},
        {"digest": "c" * 64, "family": "Aeonik"},
    ]


# --- web @font-face CSS: per-face weight/style -------------------------------


def test_build_web_font_face_css_emits_enriched_weight_and_style() -> None:
    css = build_web_font_face_css(
        {
            "store_root": "/store",
            "faces": [
                {"digest": "a" * 64, "family": "Aeonik", "weight": 700, "style": "italic"},
            ],
        },
        "https://host/",
    )
    assert css is not None
    assert "font-weight:700" in css
    assert "font-style:italic" in css
    assert "https://host/asset-store/" + "a" * 64 in css


def test_build_web_font_face_css_defaults_legacy_face_to_400_normal() -> None:
    """A spec-less face (no weight/style, e.g. a pre-enrichment kit) still
    renders at the 400/normal fallback."""
    css = build_web_font_face_css(
        {
            "store_root": "/store",
            "faces": [{"digest": "b" * 64, "family": "Aeonik"}],
        },
        "https://host/",
    )
    assert css is not None
    assert "font-weight:400" in css
    assert "font-style:normal" in css


def test_build_web_font_face_css_ignores_out_of_range_weight_style() -> None:
    css = build_web_font_face_css(
        {
            "store_root": "/store",
            "faces": [
                {"digest": "c" * 64, "family": "Aeonik", "weight": 9999, "style": "oblique"},
            ],
        },
        "https://host/",
    )
    assert css is not None
    assert "font-weight:400" in css
    assert "font-style:normal" in css


def test_the_site_offers_every_library_family_with_its_faces_as_asset_store_files() -> None:
    """Site element inspector, plan 2: the checked-in manifest as the site's `libraryFonts`."""
    from lumen_api.font_library import site_library_fonts

    families = site_library_fonts()
    assert families, "the checked-in manifest has families"
    for family in families:
        assert family["category"] in {"sans", "serif", "slab", "mono", "display"}, family
        for face in family["faces"]:
            assert re.fullmatch(r"/asset-store/[0-9a-f]{64}", face["file"]) and face["style"] in {"normal", "italic"}, face
            assert face["asset_id"].startswith("asset_font_lib_"), face
