# WOFF2 Font Decode at Ingestion (Option A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Founder rules for this repo's SDD (2026-09-02):** every implementer subagent is an **Opus** subagent; all review, verification, and decision-making is done by the orchestrating Fable session; a subagent that meets a decision reports it and stops. Commit locally, never push, no AI attribution in commits.

**Goal:** Every font asset in the design store carries plain TTF/OTF bytes, so the Skia raster, the SVG embedder, the subsetter, and the browser's CanvasKit all read the brand's real font; WOFF/WOFF2 wrappers are removed once at ingestion and put back only where a web page wants them.

**Architecture:** One Python chokepoint, `CoreClient.ingest_asset`, decodes any WOFF/WOFF2 payload to sfnt with fontTools before the bytes reach the Rust helper, rewriting the declared MIME, filename, and provenance note. The Rust engine, the `/assets/{id}/bytes` route, the brand-kit font spec, and the browser editor are untouched: they already speak TTF/OTF. The website export lane re-encodes sfnt to WOFF2 at export/publish time (deterministic, content-addressed, idempotent), and a one-time backfill script brings the 369 stored WOFF/WOFF2 assets onto the same invariant.

**Tech Stack:** Python 3.12, fontTools 4.63 (+ `brotli` for WOFF2), FastAPI test client, pytest, psycopg 3, Postgres, the `lumen-api-helper` release binary. No Rust, TypeScript, migration, or env-flag changes.

**Spec:** This plan is the spec. The investigation it argues from is in the session record and summarized in §"Why this shape" below; the founder ruling is "proceed with option A" (2026-09-02).

## Why this shape (read before implementing)

- **What was wrong.** 367 of 517 stored font assets (47 workspaces) are WOFF2 and 2 are WOFF. `crates/lumen-skia/src/embed.rs::parse_fs_type` only reads raw sfnt, so the SVG exporter refuses every one of them (`export.font_embed_unsupported_container`), CanvasKit in the browser cannot load them (`loadCanvasKit.ts` says so), and Skia on Linux (FreeType without the `freetype-woff2` feature) would fail to parse them. macOS only works because CoreText happens to read WOFF2. Verified live: the release helper shapes Apollo's "Season Mix VF" WOFF2 for PNG on this Mac but fails the SVG export on the container check.
- **Decoding is lossless.** WOFF2 is a Brotli-compressed wrapper around the same sfnt tables. fontTools writes the identical tables back out. Variable fonts stay variable.
- **Why not two blobs plus a pointer on the record.** `lumen-core/src/assets.rs::AssetRecord` (and `AssetMediaMetadata`) has no unknown-field map, so any pointer added to `media` is silently dropped whenever the record round-trips through the Rust helper (scene `assets` tables, validate/export). A mapping table would need a migration plus a branch at every consumer. Making the PRIMARY bytes sfnt needs zero consumer changes.
- **Where the web lane gets WOFF2 back.** `web_export._gather_fonts` already reads face bytes by digest and sniffs the extension; it re-encodes sfnt → WOFF2 there and registers the result content-addressed, so the zip and the hosted `/asset-store/{digest}` URL both ship WOFF2. Re-encoding is deterministic with `recalcTimestamp=False`, so repeated publishes converge on one blob.
- **Why the chokepoint is `CoreClient.ingest_asset`.** Every font byte enters through it: the harvest evidence builder, the upload analyzer, the PDF capture, the `POST /assets` route, and the font-library provisioning all call it. The Rust helper refuses a declared MIME that contradicts the sniffed bytes (`ingest.mime_mismatch`), so the chokepoint must rewrite `declared_mime_type` alongside the bytes.
- **Idempotency.** Asset ids stay content-derived from the ORIGINAL bytes (`asset_ing_<sha16>`), so a re-harvest converges on the same row; the row's digest becomes the decoded bytes' sha256, which is stable because decoding is deterministic.

## Rulings taken in this plan (founder may override)

- **R1** Primary font bytes become sfnt; the original WOFF2 blob is not referenced after backfill (it is left on disk, content-addressed, and the record's provenance note records its sha256, so the change is reversible by hand).
- **R2** A WOFF/WOFF2 payload that fontTools cannot decode is **refused** at ingestion (`ingest.font_decode_failed`) rather than stored as-is: bytes no engine can read are not a font asset. Harvest already reports refused ingests as LUMI0515 warnings; the upload route returns 400.
- **R3** The re-encoded WOFF2 blob is registered under `SOURCE_KEY_ASSET`.
- **R4** The OS/2 fsType license gate in `embed.rs` is out of scope (it blocks nothing in stored data; separate ruling).

## Global Constraints

- Run every Python test from `subsystems/clue-design` with the env sourced and the documented path: `cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest <file> -v`. Never run `pytest` without sourcing `.env` (it hits an un-migrated default DB).
- Tests use the shared colombo Postgres (`CLUE_DATABASE_URL` in `.env`) under per-test `ws_test_*` workspaces; blob bytes go to per-test tmp dirs. After any run that exercised ingestion jobs, check `SELECT count(*) FROM design_agent_run WHERE status='running' AND workspace_id LIKE 'ws_test_%'` is 0 (none of this plan's tests seed agent runs; the check is hygiene).
- `LUMEN_CORE_HELPER` in `.env` points at the release helper; the tests that go through the real `CoreClient` need it built (`cargo build -p lumen-api-helper --release` if missing).
- No Rust, no TypeScript, no Alembic migration, no new env flag. `.env.example` parity rule therefore has nothing to add.
- Line length 100, Python 3.12 typing (`X | None` is fine in new files; match the surrounding file's style when editing). `subsystems/clue-design` is excluded from root ruff, but keep imports sorted and no unused names.
- Commit after each task with a message stating what and why. No `Co-Authored-By`, no AI footer. Never push.
- Do not run the backfill script with `--apply` against any database except in Task 6's test (per-test workspace) and the operator step in Task 7, which the orchestrator runs.

---

### Task 1: Font container helpers and the `brotli` dependency

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/font_containers.py`
- Modify: `subsystems/clue-design/apps/api/pyproject.toml` (dependencies list, after `"fonttools>=4.53,<5",`)
- Modify: `uv.lock` (regenerated by `uv lock`; do not hand-edit)
- Test: `subsystems/clue-design/apps/api/tests/test_font_containers.py`

**Interfaces:**
- Consumes: `fonts/Inter-Regular.ttf` (repo root of the design subsystem; OFL-licensed, already a test fixture for `test_ingestion_font_metrics.py`).
- Produces (later tasks import these exact names):
  - `FontContainer = Literal["woff2", "woff", "ttf", "otf"]`
  - `SFNT_MIME: dict[str, str]` = `{"ttf": "font/ttf", "otf": "font/otf"}`
  - `WEB_CONTAINERS: tuple[str, ...]` = `("woff2", "woff")`
  - `class FontContainerError(ValueError)`
  - `sniff_font_container(data: bytes) -> FontContainer | None`
  - `@dataclass(frozen=True) class DecodedFont: data: bytes; container: FontContainer; mime_type: str; source_container: FontContainer; source_sha256: str`
  - `decode_web_font(data: bytes) -> DecodedFont | None` (None when `data` is not WOFF/WOFF2; raises `FontContainerError` when it is but cannot be decoded)
  - `encode_woff2(data: bytes) -> bytes` (identity for WOFF2 input; raises for non-font input)
  - `sfnt_filename(filename: str | None, container: FontContainer) -> str | None`
  - `decode_note(decoded: DecodedFont) -> str`

- [ ] **Step 1: Declare `brotli` and lock it**

`brotli 1.2.0` is installed in `.venv` today but is NOT in `uv.lock` (it was added ad hoc), so a `uv sync` could remove it and every WOFF2 decode would fail with `ImportError`. In `subsystems/clue-design/apps/api/pyproject.toml`, directly after the line `"fonttools>=4.53,<5",` add:

```toml
    # WOFF/WOFF2 decode + encode at ingestion / web export (option A, 2026-09-02). fontTools
    # needs this at runtime for `flavor="woff2"`; it was only ever present by accident before.
    "brotli>=1.1,<2",
```

Then, from the repo root:

```bash
uv lock
grep -n '^name = "brotli"' uv.lock
uv sync --inexact
.venv/bin/python -c "import brotli, fontTools; print(brotli.__version__, fontTools.version)"
```

Expected: the grep prints one `name = "brotli"` line; the python line prints a version pair.

- [ ] **Step 2: Write the failing tests**

Create `subsystems/clue-design/apps/api/tests/test_font_containers.py`:

```python
"""Font container normalization (option A, 2026-09-02).

The invariant these pin: a font asset's primary bytes are always a single sfnt face. WOFF and
WOFF2 are lossless wrappers; decoding one yields the same tables, deterministically.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from lumen_api.font_containers import (
    SFNT_MIME,
    WEB_CONTAINERS,
    DecodedFont,
    FontContainerError,
    decode_note,
    decode_web_font,
    encode_woff2,
    sfnt_filename,
    sniff_font_container,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def as_flavor(data: bytes, flavor: str) -> bytes:
    font = TTFont(BytesIO(data), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = flavor
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def glyph_order(data: bytes) -> list[str]:
    return TTFont(BytesIO(data)).getGlyphOrder()


@pytest.fixture(scope="module")
def inter_ttf() -> bytes:
    return INTER.read_bytes()


@pytest.fixture(scope="module")
def inter_woff2(inter_ttf: bytes) -> bytes:
    return as_flavor(inter_ttf, "woff2")


@pytest.fixture(scope="module")
def inter_woff(inter_ttf: bytes) -> bytes:
    return as_flavor(inter_ttf, "woff")


def test_sniff_recognizes_every_container_and_nothing_else(
    inter_ttf: bytes, inter_woff2: bytes, inter_woff: bytes
) -> None:
    assert sniff_font_container(inter_ttf) == "ttf"
    assert sniff_font_container(inter_woff2) == "woff2"
    assert sniff_font_container(inter_woff) == "woff"
    assert sniff_font_container(b"OTTO" + b"\x00" * 12) == "otf"
    assert sniff_font_container(b"true" + b"\x00" * 12) == "ttf"
    assert sniff_font_container(TINY_PNG) is None
    assert sniff_font_container(b"") is None
    assert WEB_CONTAINERS == ("woff2", "woff")
    assert SFNT_MIME == {"ttf": "font/ttf", "otf": "font/otf"}


def test_decode_woff2_yields_the_same_ttf_tables(inter_ttf: bytes, inter_woff2: bytes) -> None:
    decoded = decode_web_font(inter_woff2)
    assert isinstance(decoded, DecodedFont)
    assert decoded.container == "ttf"
    assert decoded.mime_type == "font/ttf"
    assert decoded.source_container == "woff2"
    assert decoded.source_sha256 == hashlib.sha256(inter_woff2).hexdigest()
    assert decoded.data[:4] == b"\x00\x01\x00\x00"
    source = TTFont(BytesIO(inter_ttf))
    result = TTFont(BytesIO(decoded.data))
    assert result["head"].unitsPerEm == source["head"].unitsPerEm
    assert result.getGlyphOrder() == source.getGlyphOrder()
    assert result["OS/2"].fsType == source["OS/2"].fsType
    assert result["hhea"].ascent == source["hhea"].ascent


def test_decode_woff1_yields_ttf(inter_ttf: bytes, inter_woff: bytes) -> None:
    decoded = decode_web_font(inter_woff)
    assert decoded is not None
    assert decoded.source_container == "woff"
    assert decoded.container == "ttf"
    assert glyph_order(decoded.data) == glyph_order(inter_ttf)


def test_decode_is_deterministic(inter_woff2: bytes) -> None:
    first = decode_web_font(inter_woff2)
    second = decode_web_font(inter_woff2)
    assert first is not None and second is not None
    assert first.data == second.data


def test_sfnt_and_non_font_bytes_pass_through_as_none(inter_ttf: bytes) -> None:
    assert decode_web_font(inter_ttf) is None
    assert decode_web_font(b"OTTO" + b"\x00" * 12) is None
    assert decode_web_font(TINY_PNG) is None
    assert decode_web_font(b"") is None


def test_corrupt_web_font_raises() -> None:
    with pytest.raises(FontContainerError):
        decode_web_font(b"wOF2" + b"\x00" * 96)
    with pytest.raises(FontContainerError):
        decode_web_font(b"wOFF" + b"\x11" * 96)


def test_encode_woff2_round_trips_and_is_identity_for_woff2(
    inter_ttf: bytes, inter_woff2: bytes
) -> None:
    encoded = encode_woff2(inter_ttf)
    assert encoded[:4] == b"wOF2"
    assert len(encoded) < len(inter_ttf)
    assert encode_woff2(encoded) is encoded
    back = decode_web_font(encoded)
    assert back is not None
    assert glyph_order(back.data) == glyph_order(inter_ttf)
    assert encode_woff2(inter_ttf) == encoded  # deterministic


def test_encode_woff2_refuses_non_font_bytes() -> None:
    with pytest.raises(FontContainerError):
        encode_woff2(TINY_PNG)
    with pytest.raises(FontContainerError):
        encode_woff2(b"wOFF" + b"\x11" * 96)


def test_sfnt_filename_swaps_only_web_extensions() -> None:
    assert sfnt_filename("season_mix_vf-s.p.100nk5~lg13~z.woff2", "ttf") == (
        "season_mix_vf-s.p.100nk5~lg13~z.ttf"
    )
    assert sfnt_filename("Brand.WOFF", "otf") == "Brand.otf"
    assert sfnt_filename("Brand.ttf", "ttf") == "Brand.ttf"
    assert sfnt_filename("no-extension", "ttf") == "no-extension"
    assert sfnt_filename(None, "ttf") is None
    assert sfnt_filename("", "ttf") == ""


def test_decode_note_names_source_and_target(inter_woff2: bytes) -> None:
    decoded = decode_web_font(inter_woff2)
    assert decoded is not None
    note = decode_note(decoded)
    assert note.startswith("font container decoded at ingestion: woff2 -> ttf")
    assert decoded.source_sha256 in note
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_font_containers.py -v
```

Expected: collection error `ModuleNotFoundError: No module named 'lumen_api.font_containers'`.

- [ ] **Step 4: Write the module**

Create `subsystems/clue-design/apps/api/lumen_api/font_containers.py`:

```python
"""Font container normalization for the design asset store (option A, 2026-09-02).

INVARIANT: a font asset's primary bytes are always a single sfnt face, TTF or CFF-OTF.

WOFF and WOFF2 are compressed wrappers around exactly those bytes. Every reader of stored
fonts speaks sfnt and none of them speaks WOFF2: Skia via FreeType (the Linux raster; the
macOS dev box only works because CoreText happens to read WOFF2), the SVG embedder and its
fsType license read (`crates/lumen-skia/src/embed.rs::parse_fs_type`), the klippa subsetter,
and CanvasKit in the browser editor. Before this module, 367 of 517 stored brand faces were
WOFF2, so the SVG export refused them every round and the browser canvas shaped their text in
the Inter fallback.

So the wrapper is removed ONCE, where bytes enter (`CoreClient.ingest_asset`), and put back
only where a web page wants it (`web_export`). Decoding is lossless (same tables) and, with
`recalcTimestamp=False` / `recalcBBoxes=False`, byte-deterministic, which is what keeps the
content-addressed store idempotent across re-ingests and backfills.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Literal, Optional

FontContainer = Literal["woff2", "woff", "ttf", "otf"]

#: Leading magic → container. `true` is the legacy Apple TrueType tag.
_MAGIC: tuple[tuple[bytes, FontContainer], ...] = (
    (b"wOF2", "woff2"),
    (b"wOFF", "woff"),
    (b"OTTO", "otf"),
    (b"\x00\x01\x00\x00", "ttf"),
    (b"true", "ttf"),
)

#: The MIME the asset record carries for each stored (sfnt) container.
SFNT_MIME: dict[str, str] = {"ttf": "font/ttf", "otf": "font/otf"}

#: The wrappers this module removes.
WEB_CONTAINERS: tuple[str, ...] = ("woff2", "woff")


class FontContainerError(ValueError):
    """A WOFF/WOFF2 payload that cannot be decoded, or sfnt bytes that cannot be encoded."""


def sniff_font_container(data: bytes) -> Optional[FontContainer]:
    """The container the leading magic bytes name, or ``None`` for anything else."""
    head = data[:4]
    for magic, container in _MAGIC:
        if head == magic:
            return container
    return None


@dataclass(frozen=True)
class DecodedFont:
    """One web font unwrapped to sfnt."""

    data: bytes
    container: FontContainer
    mime_type: str
    source_container: FontContainer
    source_sha256: str


def _open_font(data: bytes):
    from fontTools.ttLib import TTFont

    # Both recalc flags OFF: the tables are already correct, and touching `head.modified`
    # would make the same input produce different bytes on every run.
    return TTFont(BytesIO(data), recalcTimestamp=False, recalcBBoxes=False)


def decode_web_font(data: bytes) -> Optional[DecodedFont]:
    """Unwrap WOFF/WOFF2 to sfnt. ``None`` when ``data`` is not a web container.

    Raises :class:`FontContainerError` when the payload claims to be WOFF/WOFF2 but cannot be
    decoded, or decodes to something that is not a single sfnt face.
    """
    source = sniff_font_container(data)
    if source not in WEB_CONTAINERS:
        return None
    try:
        font = _open_font(data)
        font.flavor = None
        out = BytesIO()
        font.save(out)
    except Exception as error:  # noqa: BLE001 — fontTools raises a zoo of types
        raise FontContainerError(
            f"{source} font could not be decoded to sfnt: {type(error).__name__}: {error}"
        ) from error
    decoded = out.getvalue()
    container = sniff_font_container(decoded)
    if container not in SFNT_MIME:
        raise FontContainerError(
            f"{source} font decoded to an unexpected container {container!r}"
        )
    return DecodedFont(
        data=decoded,
        container=container,
        mime_type=SFNT_MIME[container],
        source_container=source,
        source_sha256=hashlib.sha256(data).hexdigest(),
    )


def encode_woff2(data: bytes) -> bytes:
    """Wrap sfnt bytes as WOFF2. Identity for WOFF2 input; refuses anything else."""
    container = sniff_font_container(data)
    if container == "woff2":
        return data
    if container not in SFNT_MIME:
        raise FontContainerError(
            f"cannot encode {container or 'non-font'} bytes as WOFF2; sfnt (TTF/OTF) required"
        )
    try:
        font = _open_font(data)
        font.flavor = "woff2"
        out = BytesIO()
        font.save(out)
    except Exception as error:  # noqa: BLE001
        raise FontContainerError(
            f"sfnt font could not be encoded as WOFF2: {type(error).__name__}: {error}"
        ) from error
    return out.getvalue()


def sfnt_filename(filename: Optional[str], container: FontContainer) -> Optional[str]:
    """``x.woff2`` / ``x.woff`` → ``x.<container>``; any other name is returned unchanged."""
    if not filename:
        return filename
    stem, dot, ext = filename.rpartition(".")
    if dot and ext.lower() in WEB_CONTAINERS:
        return f"{stem}.{container}"
    return filename


def decode_note(decoded: DecodedFont) -> str:
    """The provenance note the record carries so the source bytes stay traceable."""
    return (
        "font container decoded at ingestion: "
        f"{decoded.source_container} -> {decoded.container} "
        f"(source sha256:{decoded.source_sha256})"
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_font_containers.py -v
```

Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_api/font_containers.py subsystems/clue-design/apps/api/tests/test_font_containers.py subsystems/clue-design/apps/api/pyproject.toml uv.lock
git commit -m "feat(design-api): font container helpers — lossless WOFF/WOFF2 <-> sfnt, deterministic

Every reader of stored fonts (Skia/FreeType, the SVG embedder, klippa, CanvasKit) speaks
sfnt and none speaks WOFF2, yet 367/517 stored brand faces are WOFF2. This adds the
decode/encode primitives option A builds on and declares brotli, which fontTools needs for
WOFF2 and which was only present in the venv by accident."
```

---

### Task 2: Decode at the one ingestion chokepoint (`CoreClient.ingest_asset`)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/font_containers.py` (append `NormalizedIngest`, `INGEST_FONT_DECODE_FAILED`, `normalize_ingest_font`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/core.py:149-190` (`CoreClient.ingest_asset`)
- Test: `subsystems/clue-design/apps/api/tests/test_core_ingest_font_normalization.py`

**Interfaces:**
- Consumes: Task 1's `decode_web_font`, `sniff_font_container`, `sfnt_filename`, `decode_note`, `FontContainerError`, `WEB_CONTAINERS`; `CoreError(code, message, diagnostics=None)` from `lumen_api.core`.
- Produces:
  - `INGEST_FONT_DECODE_FAILED = "ingest.font_decode_failed"`
  - `@dataclass(frozen=True) class NormalizedIngest: bytes_base64: str; declared_mime_type: str | None; filename: str | None; provenance: dict | None; decoded: DecodedFont | None; refusal: dict | None`
  - `normalize_ingest_font(*, bytes_base64: str, declared_mime_type: str | None, filename: str | None, provenance: dict | None) -> NormalizedIngest`
  - `CoreClient.ingest_asset(...)` keeps its exact signature; for a WOFF/WOFF2 payload the helper receives sfnt bytes, `declared_mime_type` = `font/ttf` or `font/otf`, a `.ttf`/`.otf` filename, and a provenance note; for an undecodable web font it raises `CoreError(INGEST_FONT_DECODE_FAILED, ...)` when `raise_on_error` else returns `{"ok": False, "error": {"code": INGEST_FONT_DECODE_FAILED, "message": ...}, "diagnostics": []}` without calling the helper.

- [ ] **Step 1: Write the failing tests**

Create `subsystems/clue-design/apps/api/tests/test_core_ingest_font_normalization.py`:

```python
"""`CoreClient.ingest_asset` is the ONE chokepoint every font byte passes through — the harvest
evidence builder, the upload analyzer, the PDF capture, `POST /assets`, and the font-library
provisioning all call it. Option A (2026-09-02) decodes WOFF/WOFF2 there, so no caller and
no consumer has to know the wrapper ever existed.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from lumen_api.core import CoreClient, CoreError
from lumen_api.font_containers import (
    INGEST_FONT_DECODE_FAILED,
    decode_web_font,
    normalize_ingest_font,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture(scope="module")
def inter_ttf() -> bytes:
    return INTER.read_bytes()


@pytest.fixture(scope="module")
def inter_woff2(inter_ttf: bytes) -> bytes:
    font = TTFont(BytesIO(inter_ttf), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = "woff2"
    out = BytesIO()
    font.save(out)
    return out.getvalue()


class RecordingClient(CoreClient):
    """A CoreClient whose helper call is captured instead of executed."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict] = []

    def _run(self, request, raise_on_error=True):  # type: ignore[override]
        self.requests.append(request)
        return {"ok": True, "asset": {"record": {"id": request["asset_id"]}}}


# --- normalize_ingest_font (pure) -----------------------------------------------------------


def test_normalize_decodes_a_woff2_payload_and_rewrites_mime_filename_provenance(
    inter_woff2: bytes,
) -> None:
    normalized = normalize_ingest_font(
        bytes_base64=b64(inter_woff2),
        declared_mime_type="font/woff2",
        filename="inter.woff2",
        provenance={"created_by": "test", "notes": ["kept"]},
    )
    assert normalized.refusal is None
    assert normalized.decoded is not None
    decoded = base64.b64decode(normalized.bytes_base64)
    assert decoded[:4] == b"\x00\x01\x00\x00"
    expected = decode_web_font(inter_woff2)
    assert expected is not None and decoded == expected.data
    assert normalized.declared_mime_type == "font/ttf"
    assert normalized.filename == "inter.ttf"
    assert normalized.provenance is not None
    assert normalized.provenance["created_by"] == "test"
    assert normalized.provenance["notes"][0] == "kept"
    assert normalized.provenance["notes"][1].startswith(
        "font container decoded at ingestion: woff2 -> ttf"
    )


def test_normalize_leaves_sfnt_and_non_font_payloads_byte_identical(
    inter_ttf: bytes,
) -> None:
    for payload, mime, name in (
        (inter_ttf, "font/ttf", "inter.ttf"),
        (TINY_PNG, "image/png", "dot.png"),
    ):
        encoded = b64(payload)
        normalized = normalize_ingest_font(
            bytes_base64=encoded, declared_mime_type=mime, filename=name, provenance=None
        )
        assert normalized.bytes_base64 is encoded
        assert normalized.declared_mime_type == mime
        assert normalized.filename == name
        assert normalized.provenance is None
        assert normalized.decoded is None
        assert normalized.refusal is None


def test_normalize_creates_provenance_when_the_caller_passed_none(inter_woff2: bytes) -> None:
    normalized = normalize_ingest_font(
        bytes_base64=b64(inter_woff2), declared_mime_type=None, filename=None, provenance=None
    )
    assert normalized.provenance == {"notes": [normalized.provenance["notes"][0]]}
    assert normalized.filename is None
    assert normalized.declared_mime_type == "font/ttf"


def test_normalize_refuses_an_undecodable_web_font() -> None:
    normalized = normalize_ingest_font(
        bytes_base64=b64(b"wOF2" + b"\x00" * 96),
        declared_mime_type="font/woff2",
        filename="broken.woff2",
        provenance=None,
    )
    assert normalized.decoded is None
    assert normalized.refusal is not None
    assert normalized.refusal["code"] == INGEST_FONT_DECODE_FAILED
    assert "broken.woff2" in normalized.refusal["message"]


def test_normalize_tolerates_a_payload_the_helper_would_refuse_anyway() -> None:
    # Not valid base64: the helper reports that; the normalizer must not raise first.
    normalized = normalize_ingest_font(
        bytes_base64="@@@not-base64@@@", declared_mime_type=None, filename=None, provenance=None
    )
    assert normalized.bytes_base64 == "@@@not-base64@@@"
    assert normalized.refusal is None


# --- CoreClient.ingest_asset (captured helper call) ------------------------------------------


def test_ingest_asset_hands_the_helper_sfnt_bytes_for_a_woff2_payload(
    inter_woff2: bytes,
) -> None:
    client = RecordingClient()
    response = client.ingest_asset(
        store_root="/tmp/unused",
        bytes_base64=b64(inter_woff2),
        asset_id="asset_test_woff2",
        label="Inter web",
        declared_mime_type="font/woff2",
        filename="inter.woff2",
        kind="font",
        tags=["font"],
        provenance={"created_by": "lumen_ingestion", "notes": []},
    )
    assert response["ok"] is True
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request["action"] == "ingest_asset"
    assert base64.b64decode(request["bytes_base64"])[:4] == b"\x00\x01\x00\x00"
    assert request["declared_mime_type"] == "font/ttf"
    assert request["filename"] == "inter.ttf"
    assert request["kind"] == "font"
    assert request["tags"] == ["font"]
    assert request["provenance"]["created_by"] == "lumen_ingestion"
    assert any("decoded at ingestion" in note for note in request["provenance"]["notes"])


def test_ingest_asset_passes_sfnt_and_images_through_untouched(inter_ttf: bytes) -> None:
    client = RecordingClient()
    ttf_b64 = b64(inter_ttf)
    png_b64 = b64(TINY_PNG)
    client.ingest_asset("/tmp/unused", ttf_b64, "asset_ttf", "ttf", "font/ttf", "inter.ttf")
    client.ingest_asset("/tmp/unused", png_b64, "asset_png", "png", "image/png", "dot.png")
    assert client.requests[0]["bytes_base64"] is ttf_b64
    assert client.requests[0]["declared_mime_type"] == "font/ttf"
    assert client.requests[0]["provenance"] is None
    assert client.requests[1]["bytes_base64"] is png_b64
    assert client.requests[1]["declared_mime_type"] == "image/png"


def test_ingest_asset_refuses_an_undecodable_web_font_without_calling_the_helper() -> None:
    client = RecordingClient()
    refused = client.ingest_asset(
        "/tmp/unused",
        b64(b"wOF2" + b"\x00" * 96),
        "asset_broken",
        "broken",
        "font/woff2",
        "broken.woff2",
        raise_on_error=False,
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] == INGEST_FONT_DECODE_FAILED
    assert refused["diagnostics"] == []
    assert client.requests == []
    with pytest.raises(CoreError) as raised:
        client.ingest_asset(
            "/tmp/unused",
            b64(b"wOF2" + b"\x00" * 96),
            "asset_broken",
            "broken",
            "font/woff2",
            "broken.woff2",
        )
    assert raised.value.code == INGEST_FONT_DECODE_FAILED
    assert client.requests == []


# --- the real helper --------------------------------------------------------------------------


def test_real_helper_stores_the_decoded_face(tmp_path: Path, inter_woff2: bytes) -> None:
    """End to end through the release helper: the record and the cached bytes are sfnt."""
    core = CoreClient()
    response = core.ingest_asset(
        store_root=str(tmp_path),
        bytes_base64=b64(inter_woff2),
        asset_id="asset_test_decoded_face",
        label="Inter web (decoded)",
        declared_mime_type="font/woff2",
        filename="inter.woff2",
        kind="font",
        provenance={"created_by": "test", "notes": []},
        raise_on_error=False,
    )
    assert response.get("ok"), response
    record = response["asset"]["record"]
    expected = decode_web_font(inter_woff2)
    assert expected is not None
    digest = hashlib.sha256(expected.data).hexdigest()
    assert record["media"]["mime_type"] == "font/ttf"
    assert record["media"]["digest"]["value"] == digest
    assert record["media"]["filename"] == "inter.ttf"
    assert record["media"]["byte_length"] == len(expected.data)
    assert any("decoded at ingestion" in note for note in record["provenance"]["notes"])
    cached = tmp_path / "sha256" / digest[:2] / digest
    assert cached.read_bytes() == expected.data
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_core_ingest_font_normalization.py -v
```

Expected: `ImportError: cannot import name 'INGEST_FONT_DECODE_FAILED' from 'lumen_api.font_containers'`.

- [ ] **Step 3: Append the ingest normalizer to `font_containers.py`**

Add these imports at the top of `font_containers.py` (keep them sorted): `import base64`, `import binascii`, and `from typing import Any` (alongside the existing `Literal, Optional`). Then append at the end of the file:

```python
# ---------------------------------------------------------------------------------------------
# Ingestion chokepoint
# ---------------------------------------------------------------------------------------------

#: The refusal code an undecodable WOFF/WOFF2 ingest returns. Bytes no engine can read are not
#: a font asset (ruling R2, 2026-09-02); the harvest lane already reports refused ingests as
#: LUMI0515 warnings and `POST /assets` returns 400.
INGEST_FONT_DECODE_FAILED = "ingest.font_decode_failed"


@dataclass(frozen=True)
class NormalizedIngest:
    """`CoreClient.ingest_asset`'s arguments after font normalization.

    Exactly one of the two outcomes is set for a web font: ``decoded`` (bytes, MIME, filename
    and provenance rewritten) or ``refusal`` (``{"code", "message"}``; nothing rewritten). Any
    other payload comes back untouched, ``bytes_base64`` being the very same object.
    """

    bytes_base64: str
    declared_mime_type: Optional[str]
    filename: Optional[str]
    provenance: Optional[dict[str, Any]]
    decoded: Optional[DecodedFont]
    refusal: Optional[dict[str, str]]


def _leading_bytes(bytes_base64: str) -> bytes:
    # Eight base64 characters decode to six bytes — enough for every magic above — so an image
    # payload is never decoded whole just to learn it is not a font.
    head = bytes_base64[:8] if len(bytes_base64) >= 8 else bytes_base64
    try:
        return base64.b64decode(head, validate=True)
    except (binascii.Error, ValueError):
        return b""


def normalize_ingest_font(
    *,
    bytes_base64: str,
    declared_mime_type: Optional[str],
    filename: Optional[str],
    provenance: Optional[dict[str, Any]],
) -> NormalizedIngest:
    """Rewrite an ingest call so a WOFF/WOFF2 payload reaches the helper as sfnt.

    The helper refuses a declared MIME that contradicts the sniffed bytes
    (``ingest.mime_mismatch``), so the MIME is rewritten with the bytes; the filename keeps
    its stem and gets the real extension; the provenance gains one note naming the source
    container and its sha256 so the original stays traceable.
    """
    untouched = NormalizedIngest(
        bytes_base64, declared_mime_type, filename, provenance, decoded=None, refusal=None
    )
    if sniff_font_container(_leading_bytes(bytes_base64)) not in WEB_CONTAINERS:
        return untouched
    try:
        raw = base64.b64decode(bytes_base64, validate=True)
    except (binascii.Error, ValueError):
        return untouched  # the helper reports malformed base64 exactly as it always has
    try:
        decoded = decode_web_font(raw)
    except FontContainerError as error:
        return NormalizedIngest(
            bytes_base64,
            declared_mime_type,
            filename,
            provenance,
            decoded=None,
            refusal={
                "code": INGEST_FONT_DECODE_FAILED,
                "message": f"{filename or 'font'}: {error}",
            },
        )
    if decoded is None:  # the six-byte sniff and the full decode disagree only on garbage
        return untouched
    stamped = dict(provenance or {})
    notes = list(stamped.get("notes") or [])
    notes.append(decode_note(decoded))
    stamped["notes"] = notes
    return NormalizedIngest(
        base64.b64encode(decoded.data).decode("ascii"),
        decoded.mime_type,
        sfnt_filename(filename, decoded.container),
        stamped,
        decoded=decoded,
        refusal=None,
    )
```

- [ ] **Step 4: Wire the chokepoint in `CoreClient.ingest_asset`**

In `subsystems/clue-design/apps/api/lumen_api/core.py`, add the import near the other `lumen_api` imports at the top of the file:

```python
from lumen_api.font_containers import normalize_ingest_font
```

Then replace the body of `ingest_asset` (currently `return self._run({...})`, lines ~166-190) so the method reads:

```python
    def ingest_asset(
        self,
        store_root: str,
        bytes_base64: str,
        asset_id: str,
        label: str,
        declared_mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        kind: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        license: Optional[JsonObject] = None,
        provenance: Optional[JsonObject] = None,
        source: Optional[JsonObject] = None,
        tags: Optional[List[str]] = None,
        max_bytes: Optional[int] = None,
        raise_on_error: bool = True,
    ) -> JsonObject:
        # Option A (2026-09-02): the ONE chokepoint every font byte passes through — harvest,
        # uploads, PDF capture, `POST /assets`, font-library provisioning. A WOFF/WOFF2 payload
        # is unwrapped to sfnt HERE, before the Rust helper sniffs it, so the stored primary
        # bytes are always TTF/OTF (see `font_containers.py` for why that invariant matters).
        # `max_bytes` is checked by the helper against the DECODED size, which can be 2-3x the
        # wrapper; that is the honest number for what the store keeps.
        normalized = normalize_ingest_font(
            bytes_base64=bytes_base64,
            declared_mime_type=declared_mime_type,
            filename=filename,
            provenance=provenance,
        )
        if normalized.refusal is not None:
            if raise_on_error:
                raise CoreError(normalized.refusal["code"], normalized.refusal["message"])
            return {"ok": False, "error": dict(normalized.refusal), "diagnostics": []}
        return self._run(
            {
                "action": "ingest_asset",
                "store_root": store_root,
                "bytes_base64": normalized.bytes_base64,
                "asset_id": asset_id,
                "label": label,
                "declared_mime_type": normalized.declared_mime_type,
                "filename": normalized.filename,
                "kind": kind,
                "uploaded_by": uploaded_by,
                "license": license,
                "provenance": normalized.provenance,
                "source": source,
                "tags": tags,
                "max_bytes": max_bytes,
            },
            raise_on_error=raise_on_error,
        )
```

Keep every other key exactly as the current code passes it (compare against the existing request dict before deleting it; the current call may pass `raise_on_error` differently — preserve the existing `_run` call convention).

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_core_ingest_font_normalization.py apps/api/tests/test_font_containers.py -v
```

Expected: all pass (the real-helper test needs `LUMEN_CORE_HELPER` to resolve; if it reports the binary is missing, run `cargo build -p lumen-api-helper --release` from `subsystems/clue-design` and re-run).

- [ ] **Step 6: Run the existing ingest-adjacent suites to prove nothing regressed**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_ingestion_asset_slurp.py apps/api/tests/test_asset_custody.py apps/api/tests/test_font_library.py -q
```

Expected: all pass (these suites use stub cores or TTF payloads, which the chokepoint passes through untouched).

- [ ] **Step 7: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_api/font_containers.py subsystems/clue-design/apps/api/lumen_api/core.py subsystems/clue-design/apps/api/tests/test_core_ingest_font_normalization.py
git commit -m "feat(design-api): decode WOFF/WOFF2 to sfnt at the ingest_asset chokepoint

CoreClient.ingest_asset is the one call every font byte passes through (harvest, uploads,
PDF capture, POST /assets, font-library provisioning). A web-font payload now reaches the
Rust helper as TTF/OTF with its MIME, filename and provenance rewritten, so the stored
primary bytes are always sfnt and no consumer has to know the wrapper existed. An
undecodable web font is refused (ingest.font_decode_failed) rather than stored."
```

---

### Task 3: Integration proof — the pipeline and the upload route persist sfnt

**Files:**
- Test: `subsystems/clue-design/apps/api/tests/test_ingestion_font_decode.py`
- Modify (only if the tests expose a gap): `subsystems/clue-design/apps/api/lumen_api/main.py` (`POST /assets`, ~line 6559) or `subsystems/clue-design/apps/api/lumen_ingestion/pipeline.py::_RecordingCore` (~line 240)

**Interfaces:**
- Consumes: Task 2's chokepoint; the `client`, `design_storage`, `workspace_id`, `make_client`, `wait_for_ingestion_job` fixtures/helpers from `tests/conftest.py`; the website-ingestion monkeypatch pattern from `tests/test_ingestion_ui_api.py::test_capture_layer_assets_are_persisted_as_records` (lines ~320-420); `HybridRepository.require_asset_record(asset_id) -> {"asset": record, ...}`.
- Produces: nothing new; this task is the end-to-end evidence that both production entry points now store sfnt.

- [ ] **Step 1: Write the failing tests**

Create `subsystems/clue-design/apps/api/tests/test_ingestion_font_decode.py`:

```python
"""Option A (2026-09-02), end to end: a WOFF2 font that enters through the two production doors
— the website-ingestion pipeline (`_RecordingCore` → durable custody → registry) and
`POST /assets` — is stored, recorded, and served as TTF.
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fontTools.ttLib import TTFont

from conftest import make_client, wait_for_ingestion_job
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
EVIDENCE_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "ingestion" / "evidence_website_insight.json"
)
SFNT_TTF_MAGIC = b"\x00\x01\x00\x00"


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


@pytest.fixture(scope="module")
def inter_ttf() -> bytes:
    return INTER.read_bytes()


@pytest.fixture(scope="module")
def inter_woff2(inter_ttf: bytes) -> bytes:
    font = TTFont(BytesIO(inter_ttf), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = "woff2"
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def glyph_order(data: bytes) -> list[str]:
    return TTFont(BytesIO(data)).getGlyphOrder()


def assert_stored_as_ttf(client: TestClient, asset_id: str, inter_ttf: bytes) -> None:
    stored = HybridRepository().require_asset_record(asset_id)["asset"]
    media = stored["media"]
    assert media["mime_type"] == "font/ttf", media
    assert media["filename"].endswith(".ttf"), media
    assert any(
        "decoded at ingestion: woff2 -> ttf" in note
        for note in stored["provenance"]["notes"]
    ), stored["provenance"]
    served = client.get(f"/assets/{asset_id}/bytes")
    assert served.status_code == 200, served.text
    assert served.headers["content-type"].startswith("font/ttf")
    assert served.content[:4] == SFNT_TTF_MAGIC
    assert glyph_order(served.content) == glyph_order(inter_ttf)
    assert media["digest"]["value"] == __import__("hashlib").sha256(served.content).hexdigest()


def test_website_ingestion_persists_a_harvested_woff2_face_as_ttf(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, inter_ttf: bytes, inter_woff2: bytes
) -> None:
    from lumen_api import main as main_module
    from lumen_ingestion.evidence import BrandEvidence
    from lumen_ingestion.pipeline import run_website_ingestion

    asset_id = "asset_ing_fontdecode01"
    ingested: list[dict] = []

    async def fake_capture(url, *, reporter, force_render=False, page_urls=None):
        class Outcome:
            tier = "static"
            escalated = False
            escalation_reason = None
            diagnostics: list[dict] = []

        return Outcome()

    def fake_build_evidence(outcome, *, core, store_root, reporter):
        # The exact call `lumen_ingestion.capture.evidence_builder._call_ingest` makes for a
        # harvested webfont, with real WOFF2 bytes.
        response = core.ingest_asset(
            store_root=store_root,
            bytes_base64=base64.b64encode(inter_woff2).decode("ascii"),
            asset_id=asset_id,
            label="inter-var.woff2",
            declared_mime_type="font/woff2",
            filename="inter-var.woff2",
            kind="font",
            provenance={
                "created_by": "lumen_ingestion",
                "created_at": "2026-09-02T00:00:00+00:00",
                "source_label": "website",
                "confidence": 0.7,
                "notes": [],
            },
            source={
                "kind": "website",
                "url": "https://record-fix.example/fonts/inter-var.woff2",
                "captured_at": "2026-09-02T00:00:00+00:00",
            },
            tags=["brand-ingestion", "font"],
            max_bytes=15 * 1024 * 1024,
            raise_on_error=False,
        )
        assert response.get("ok"), response
        ingested.append(response["asset"]["record"])
        return BrandEvidence.model_validate(json.loads(EVIDENCE_FIXTURE.read_text()))

    async def passthrough(url: str) -> str:
        return url

    monkeypatch.setattr(main_module, "_resolve_guard_url", lambda: passthrough)
    monkeypatch.setattr(
        main_module,
        "run_website_ingestion",
        lambda cache_dir, job_id, *, workspace_id, storage=None, expected_generation=None: (
            run_website_ingestion(
                cache_dir,
                job_id,
                capture=fake_capture,
                build_evidence=fake_build_evidence,
                workspace_id=workspace_id,
                storage=storage,
                expected_generation=expected_generation,
            )
        ),
    )

    post = client.post("/brand-kits/ingest/website", json={"url": "https://record-fix.example"})
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    wait_for_ingestion_job(client, job_id)
    job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert job["status"] == "succeeded", job

    assert [record["id"] for record in ingested] == [asset_id]
    assert ingested[0]["media"]["mime_type"] == "font/ttf"
    assert_stored_as_ttf(client, asset_id, inter_ttf)


def test_upload_route_persists_a_woff2_font_as_ttf(
    client: TestClient, inter_ttf: bytes, inter_woff2: bytes
) -> None:
    response = client.post(
        "/assets",
        files={"file": ("inter.woff2", inter_woff2, "font/woff2")},
        data={"label": "Inter web upload", "kind": "font"},
    )
    assert response.status_code == 200, response.text
    asset = response.json()["asset"]
    assert asset["media"]["mime_type"] == "font/ttf", asset
    assert_stored_as_ttf(client, asset["id"], inter_ttf)


def test_upload_route_refuses_an_undecodable_woff2(client: TestClient) -> None:
    response = client.post(
        "/assets",
        files={"file": ("broken.woff2", b"wOF2" + b"\x00" * 96, "font/woff2")},
        data={"label": "broken", "kind": "font"},
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "ingest.font_decode_failed"
```

- [ ] **Step 2: Run the tests**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_ingestion_font_decode.py -v
```

Expected: the two "persists as ttf" tests pass on the strength of Task 2 (the pipeline and the route both call `CoreClient.ingest_asset`). The refusal test may FAIL if `POST /assets` renders the refusal without a `code` — read the route's `if not result.get("ok", False):` branch (main.py ~6600-6635): it already builds `detail={"code": error.get("code"), "message": ..., "diagnostics": ...}` with status 400 for anything but `ingest.too_large`. If the test still fails, the response JSON shape is the thing to fix in the TEST (print `response.json()`), not the route: this task changes no production behavior beyond Task 2.

If `asset["media"]` is absent from the public record (the route returns `public_asset_record(stored["asset"])`, main.py ~6524), assert the MIME through `assert_stored_as_ttf` only and drop the `asset["media"]` line; report which shape you found.

- [ ] **Step 3: Run the neighbouring suites**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_ingestion_ui_api.py apps/api/tests/test_asset_store_serving.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add subsystems/clue-design/apps/api/tests/test_ingestion_font_decode.py
git commit -m "test(design-api): harvested and uploaded WOFF2 faces are stored and served as TTF

End-to-end evidence for option A through both production doors: the website-ingestion
pipeline (_RecordingCore → custody → registry) and POST /assets."
```

---

### Task 4: Engine regression — the SVG export embeds a decoded brand face

**Files:**
- Test: `subsystems/clue-design/apps/api/tests/test_export_decoded_web_font.py`

**Interfaces:**
- Consumes: `CoreClient.new_scene(document_id, title)`, `CoreClient.compile_dsl_into_scene(scene, source)`, `CoreClient.export_preview(scene, export_format, page_ids, profile, raise_on_error, brand_fonts)` (all existing; the DSL and profile shapes are copied from `tests/test_export_parity.py::build_scene` / `export_bytes`); the helper's `brand_fonts` spec `{"store_root": str, "faces": [{"digest", "family", "weight", "style"}]}` whose bytes live at `store_root/sha256/{digest[:2]}/{digest}`; Task 1's `decode_web_font`.
- Produces: the regression pin for the live defect (WOFF2 face → `export.font_embed_unsupported_container`) and its resolution (decoded face → `@font-face` embedded).

- [ ] **Step 1: Write the tests**

Create `subsystems/clue-design/apps/api/tests/test_export_decoded_web_font.py`:

```python
"""The engine-side half of option A (2026-09-02).

Red case, pinned on purpose: hand the exporter the WOFF2 bytes a brand kit used to store and
the SVG export refuses them (`export.font_embed_unsupported_container`) — the defect that left
~71% of brand fonts un-embeddable and, through P0.4's gate, un-checkpointed. Green case: the
same face decoded to sfnt at ingestion embeds as `@font-face` and shapes without a fallback.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from lumen_api.core import CoreClient
from lumen_api.font_containers import decode_web_font

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"

#: One page, one text run, in a family that exists ONLY as the brand face registered below —
#: so an embedded `@font-face` for it can only have come from the brand_fonts spec.
DSL = """
page page_font size(600,200,px)
  headline text "Decoded web font" p(40,40) s(520,120) font("InterWeb",40,400,left) fill(#111827)
"""

PROFILE = {
    "name": "decoded_face_svg",
    "format": "svg",
    "pdf_intent": None,
    "raster": None,
    "include_bleed": False,
    "embed_fonts": True,
}


@pytest.fixture(scope="module")
def core() -> CoreClient:
    return CoreClient()


@pytest.fixture(scope="module")
def inter_woff2() -> bytes:
    font = TTFont(BytesIO(INTER.read_bytes()), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = "woff2"
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def build_scene(core: CoreClient) -> dict:
    fresh = core.new_scene("doc_decoded_web_font", "Decoded web font fixture")
    compiled = core.compile_dsl_into_scene(fresh, DSL)
    compile_output = (compiled.get("dsl") or {}).get("compile_output") or {}
    errors = [
        entry
        for entry in compile_output.get("diagnostics") or []
        if entry.get("diagnostic", {}).get("severity") == "error"
    ]
    assert not errors, f"fixture DSL must compile clean: {errors}"
    return compiled["scene"]


def store_face(root: Path, data: bytes) -> str:
    """Place bytes where the helper's brand-font loader looks: sha256/{ab}/{digest}."""
    digest = hashlib.sha256(data).hexdigest()
    path = root / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest


def brand_fonts(root: Path, digest: str) -> dict:
    return {
        "store_root": str(root),
        "faces": [{"digest": digest, "family": "InterWeb", "weight": 400, "style": "normal"}],
    }


def export(core: CoreClient, scene: dict, export_format: str, spec: dict) -> dict:
    return core.export_preview(
        scene,
        export_format=export_format,
        page_ids=["page_font"],
        profile={**PROFILE, "format": export_format, "name": f"decoded_face_{export_format}"},
        raise_on_error=False,
        brand_fonts=spec,
    )


def artifact_text(response: dict) -> str:
    artifacts = response["export"]["artifacts"]
    assert artifacts, response
    return bytes(int(value) & 0xFF for value in artifacts[0]["bytes"]).decode("utf-8")


def test_the_woff2_face_still_refuses_svg_embedding_red_case(
    core: CoreClient, tmp_path: Path, inter_woff2: bytes
) -> None:
    scene = build_scene(core)
    digest = store_face(tmp_path, inter_woff2)
    response = export(core, scene, "svg", brand_fonts(tmp_path, digest))
    assert response.get("ok") is False, response
    assert response["error"]["code"] == "export.font_embed_unsupported_container"
    assert "SVG font embedding failed" in response["error"]["message"]


def test_the_decoded_face_embeds_in_svg_and_shapes_without_fallback(
    core: CoreClient, tmp_path: Path, inter_woff2: bytes
) -> None:
    decoded = decode_web_font(inter_woff2)
    assert decoded is not None
    scene = build_scene(core)
    digest = store_face(tmp_path, decoded.data)
    spec = brand_fonts(tmp_path, digest)

    svg = export(core, scene, "svg", spec)
    assert svg.get("ok"), svg
    text = artifact_text(svg)
    assert "@font-face" in text
    assert "InterWeb" in text
    assert "data:font/ttf;base64," in text

    png = export(core, scene, "png", spec)
    assert png.get("ok"), png
    diagnostics = list(png.get("diagnostics") or []) + list(
        png["export"].get("diagnostics") or []
    )
    fallbacks = [d for d in diagnostics if d.get("code") in ("LUMS0100", "LUMS0101")]
    assert not fallbacks, fallbacks
```

- [ ] **Step 2: Run the tests**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_export_decoded_web_font.py -v
```

Expected: both pass. If the red case returns `ok: True`, the helper binary predates the container check or the face was not loaded; print the response and stop — that is a finding for the orchestrator, not something to paper over. If the green case's `@font-face` names the intrinsic family (`Inter`) rather than the alias, relax the family assertion to `"Inter" in text` and report the exact `@font-face` line found.

- [ ] **Step 3: Commit**

```bash
git add subsystems/clue-design/apps/api/tests/test_export_decoded_web_font.py
git commit -m "test(design-api): pin the WOFF2 SVG-embed refusal and prove the decoded face embeds

The live defect (export.font_embed_unsupported_container on every WOFF2 brand face) and
its resolution (the same face decoded to sfnt embeds as @font-face and shapes without a
LUMS0100/0101 fallback), driven through the release helper."
```

---

### Task 5: The website lane ships WOFF2 again (re-encode at export/publish)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_export.py` (imports; `_gather_fonts` ~lines 367-437; add `_web_face_bytes`)
- Modify: `subsystems/clue-design/apps/api/tests/test_web_export.py` (`seed_font_asset` gains a `mime_type` parameter; two new tests)

**Interfaces:**
- Consumes: Task 1's `encode_woff2`, `sniff_font_container`, `SFNT_MIME`, `FontContainerError`; `DesignBlobStore.register(data, *, media_type, source_key) -> str`; `SOURCE_KEY_ASSET` from `clue_design.storage`; the existing `_FontFace(digest, family, weight, style, ext, data)` and `_font_ext(data)`.
- Produces: `_web_face_bytes(blobs, digest, data) -> tuple[bytes, str, str, str | None]` returning `(bytes_to_ship, ext, digest_to_name, warning_or_None)`. Both the zip (`fonts/{digest[:12]}.{ext}`) and the hosted page (`/asset-store/{digest}`) therefore name the WOFF2 blob.

- [ ] **Step 1: Extend the seed helper and write the failing tests**

In `tests/test_web_export.py`, change `seed_font_asset` so the MIME and extension are parameters (existing callers keep working):

```python
def seed_font_asset(
    client: TestClient, asset_id: str, data: bytes, mime_type: str = "font/woff2"
) -> str:
    # D4: the export reads face bytes from DURABLE storage, so seed them through the seam.
    digest = make_blob_store(client.app).register(
        data, media_type=mime_type, source_key=SOURCE_KEY_ASSET
    ) and hashlib.sha256(data).hexdigest()
    ext = mime_type.rsplit("/", 1)[-1]
    record = {
        "id": asset_id,
        "label": asset_id,
        "kind": "font",
        "status": "ready",
        "source": {"kind": "uploaded"},
        "media": {
            "mime_type": mime_type,
            "digest": {"algorithm": "sha256", "value": digest},
            "filename": f"{asset_id}.{ext}",
            "byte_length": len(data),
            "location": None,
        },
    }
    store = HybridRepository()
    store.create_asset_record(record)
    return digest
```

Then append two tests at the end of the font-gate section (after `test_the_publish_manifest_names_the_basis_a_family_embeds_under`), adding `from io import BytesIO` and `from fontTools.ttLib import TTFont` to the file's imports and `INTER_TTF_PATH = REPO_ROOT / "fonts" / "Inter-Regular.ttf"` next to `ACME_KIT_PATH` (if `REPO_ROOT` is not defined in this file, define it as `Path(__file__).resolve().parents[3]`):

```python
def _glyph_order(data: bytes) -> list[str]:
    return TTFont(BytesIO(data)).getGlyphOrder()


def test_export_ships_a_stored_sfnt_face_as_woff2(client: TestClient) -> None:
    """Option A (2026-09-02): the store keeps sfnt; the page gets WOFF2 back, content-addressed."""
    inter = INTER_TTF_PATH.read_bytes()
    seed_font_asset(client, "asset_font_sfnt", inter, mime_type="font/ttf")
    seed_font_asset(client, "asset_font_sfnt_locked", b"wOF2" + b"\x11" * 96)
    create_font_kit(client, "asset_font_sfnt", "asset_font_sfnt_locked")

    document = create_web_document(
        client, brand_kit_ref={"id": "kit_export_fonts", "version": 1}
    )
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    files, html, manifest = export_zip(client, document["id"])

    shipped = [name for name in files if name.startswith("fonts/")]
    assert len(shipped) == 1, shipped
    assert shipped[0].endswith(".woff2"), shipped
    data = files[shipped[0]]
    assert data[:4] == b"wOF2"
    assert len(data) < len(inter)
    back = TTFont(BytesIO(data))
    back.flavor = None
    out = BytesIO()
    back.save(out)
    assert _glyph_order(out.getvalue()) == _glyph_order(inter)
    assert shipped[0] == f"fonts/{hashlib.sha256(data).hexdigest()[:12]}.woff2"
    assert "Export Sans" in manifest["font_families_included"]


def test_publish_names_the_woff2_blob_on_the_digest_route(
    client: TestClient, workspace_id: str
) -> None:
    inter = INTER_TTF_PATH.read_bytes()
    seed_font_asset(client, "asset_font_pub_sfnt", inter, mime_type="font/ttf")
    seed_font_asset(client, "asset_font_pub_sfnt_locked", b"wOF2" + b"\x11" * 96)
    create_font_kit(client, "asset_font_pub_sfnt", "asset_font_pub_sfnt_locked")
    document = create_web_document(
        client, brand_kit_ref={"id": "kit_export_fonts", "version": 1}
    )
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "sfnt-to-woff2"}
    )
    assert published.status_code == 200, published.text

    served = client.get(f"/w/{workspace_id}/p/sfnt-to-woff2")
    assert served.status_code == 200, served.text
    sha_of_ttf = hashlib.sha256(inter).hexdigest()
    assert f"/asset-store/{sha_of_ttf}" not in served.text
    marker = "/asset-store/"
    start = served.text.index(marker) + len(marker)
    woff2_digest = served.text[start : start + 64]
    assert len(woff2_digest) == 64
    blob = client.get(f"/asset-store/{woff2_digest}")
    assert blob.status_code == 200, blob.text
    assert blob.content[:4] == b"wOF2"
    assert hashlib.sha256(blob.content).hexdigest() == woff2_digest
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_web_export.py -k "sfnt_face_as_woff2 or woff2_blob_on_the_digest_route" -v
```

Expected: both FAIL (`fonts/<digest12>.ttf` is shipped; the page names the TTF digest).

- [ ] **Step 3: Implement `_web_face_bytes` and use it in `_gather_fonts`**

In `web_export.py`, add to the imports (keep the existing import groups' order):

```python
from clue_design.storage import SOURCE_KEY_ASSET
from lumen_api.font_containers import SFNT_MIME, FontContainerError, encode_woff2, sniff_font_container
```

(`hashlib` is already imported for `_font_ext`'s neighbours; if not, add `import hashlib`.) Add this function directly above `_gather_fonts`:

```python
def _web_face_bytes(
    blobs: DesignBlobStore, digest: str, data: bytes
) -> Tuple[bytes, str, str, Optional[str]]:
    """``(bytes_to_ship, ext, digest_to_name, warning)`` for one face on a web page.

    Option A (2026-09-02) keeps every stored font as sfnt; a page wants the compressed wrapper
    back. The re-encode is byte-deterministic, so registering it content-addressed is idempotent
    across publishes, and the hosted page's ``/asset-store/{digest}`` then names the WOFF2 blob
    (that route serves any registered digest). Bytes that are not sfnt — a legacy face the
    backfill has not reached, or a test's fake payload — pass through untouched; an encode
    failure ships the sfnt with a warning rather than dropping the face.
    """
    if sniff_font_container(data) not in SFNT_MIME:
        return data, _font_ext(data), digest, None
    try:
        woff2 = encode_woff2(data)
    except FontContainerError as error:
        return (
            data,
            _font_ext(data),
            digest,
            f"font face {digest[:12]} shipped as {_font_ext(data)}: WOFF2 encode failed ({error})",
        )
    blobs.register(woff2, media_type="font/woff2", source_key=SOURCE_KEY_ASSET)
    return woff2, "woff2", hashlib.sha256(woff2).hexdigest(), None
```

In `_gather_fonts`, replace the tail of the per-face loop — from `seen.add(digest)` through the `faces.append(_FontFace(...))` call — with:

```python
            seen.add(digest)
            data, ext, shipped_digest, note = _web_face_bytes(blobs, digest, data)
            if note is not None:
                warnings.append(note)
            faces.append(
                _FontFace(
                    digest=shipped_digest,
                    family=family,
                    weight=_valid_weight(face.get("weight")),
                    style=_valid_style(face.get("style")),
                    ext=ext,
                    data=data,
                )
            )
```

(`seen` still keys on the STORED digest so a face referenced twice is gathered once.)

- [ ] **Step 4: Run the whole web export suite**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_web_export.py -v
```

Expected: all pass, including the pre-existing fake-`wOF2` tests (pass-through branch).

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_api/web_export.py subsystems/clue-design/apps/api/tests/test_web_export.py
git commit -m "feat(design-api): web export re-encodes stored sfnt faces to WOFF2, content-addressed

The store now keeps fonts as sfnt (option A); the page wants the compressed wrapper. The
zip and the hosted /asset-store URL both name a deterministically re-encoded WOFF2 blob;
non-sfnt bytes pass through so legacy faces and fake test payloads are unaffected."
```

---

### Task 6: Backfill the stored WOFF/WOFF2 assets

**Files:**
- Create: `subsystems/clue-design/scripts/decode_stored_web_fonts.py`
- Test: `subsystems/clue-design/apps/api/tests/test_decode_stored_web_fonts.py`

**Interfaces:**
- Consumes: Task 1's `decode_web_font`, `decode_note`, `FontContainerError`; the `design_asset` and `artifact` tables (DDL: `design_asset(asset_id, workspace_id, mime_type, digest_value, byte_length, filename, record_json, updated_at)` with no triggers; `artifact(storage_key, workspace_id, content_sha256, media_type, size_bytes, source_key)` with `storage_key = '{ws}/design/{sha}'` enforced by CHECK and unique); the `flatten_stored_fragments.py` conventions (psycopg, `CLUE_DATABASE_URL` + `CLUE_STORAGE_FS_ROOT`, dry-run default, `--apply`, row-before-blob custody).
- Produces: `decode_stored_web_fonts(conn, storage_root: Path, *, workspace_id: str | None = None, apply: bool = False) -> Summary` with `Summary(decoded: int, relabelled: int, skipped: int, missing: int, failed: int)`; a CLI `main()` with `--apply`, `--workspace`.

- [ ] **Step 1: Write the failing test**

Create `subsystems/clue-design/apps/api/tests/test_decode_stored_web_fonts.py`:

```python
"""The one-time backfill that brings already-stored WOFF/WOFF2 font assets onto option A's
invariant (primary bytes are sfnt). Idempotent, dry-run by default, reversible by provenance.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from io import BytesIO
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from fontTools.ttLib import TTFont

from clue_design.storage import SOURCE_KEY_ASSET, design_location, design_storage_key
from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
SCRIPT = REPO_ROOT / "scripts" / "decode_stored_web_fonts.py"


def load_script():
    spec = importlib.util.spec_from_file_location("decode_stored_web_fonts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "design-storage"


@pytest.fixture()
def client(tmp_path: Path, storage_root: Path) -> TestClient:
    from clue_storage import FsStorage

    app = create_app(tmp_path / "engine-cache", storage=FsStorage(storage_root))
    return make_client(app)


@pytest.fixture()
def conn():
    dsn = (
        os.environ["CLUE_DATABASE_URL"]
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )
    with psycopg.connect(dsn) as connection:
        yield connection


def inter_as(flavor: str) -> bytes:
    font = TTFont(BytesIO(INTER.read_bytes()), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = flavor
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def seed_web_font(client: TestClient, asset_id: str, data: bytes, mime_type: str) -> str:
    """A font asset exactly as ingestion stored it before option A: WOFF2 bytes, WOFF2 record."""
    key = make_blob_store(client.app).register(
        data, media_type=mime_type, source_key=SOURCE_KEY_ASSET
    )
    digest = hashlib.sha256(data).hexdigest()
    assert key == design_storage_key(os.environ["LUMEN_DEV_WORKSPACE_ID"], digest)
    record = {
        "id": asset_id,
        "label": f"{asset_id}.woff2",
        "kind": "font",
        "status": "ready",
        "source": {"kind": "website", "url": "https://example.test/font.woff2"},
        "media": {
            "mime_type": mime_type,
            "digest": {"algorithm": "sha256", "value": digest},
            "filename": f"{asset_id}.woff2",
            "byte_length": len(data),
            "location": design_location(key),
        },
        "provenance": {"created_by": "lumen_ingestion", "notes": []},
        "tags": ["brand-ingestion", "font"],
    }
    HybridRepository().create_asset_record(record)
    return digest


def test_dry_run_changes_nothing(client: TestClient, conn, storage_root: Path) -> None:
    woff2 = inter_as("woff2")
    digest = seed_web_font(client, "asset_backfill_dry", woff2, "font/woff2")
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    summary = load_script().decode_stored_web_fonts(
        conn, storage_root, workspace_id=workspace_id, apply=False
    )
    assert summary.decoded == 1 and summary.missing == 0 and summary.failed == 0
    stored = HybridRepository().require_asset_record("asset_backfill_dry")["asset"]
    assert stored["media"]["digest"]["value"] == digest
    assert stored["media"]["mime_type"] == "font/woff2"


def test_apply_decodes_relabels_and_is_idempotent(
    client: TestClient, conn, storage_root: Path
) -> None:
    woff2 = inter_as("woff2")
    old_digest = seed_web_font(client, "asset_backfill_apply", woff2, "font/woff2")
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    script = load_script()

    first = script.decode_stored_web_fonts(conn, storage_root, workspace_id=workspace_id, apply=True)
    assert first.decoded == 1 and first.failed == 0 and first.missing == 0

    repo = HybridRepository()
    stored = repo.require_asset_record("asset_backfill_apply")["asset"]
    media = stored["media"]
    new_digest = media["digest"]["value"]
    assert new_digest != old_digest
    assert media["mime_type"] == "font/ttf"
    assert media["filename"] == "asset_backfill_apply.ttf"
    assert media["location"]["opaque_ref"] == f"{workspace_id}/design/{new_digest}"
    assert media["byte_length"] == (storage_root / workspace_id / "design" / new_digest).stat().st_size
    notes = stored["provenance"]["notes"]
    assert any("decoded at ingestion: woff2 -> ttf" in note for note in notes)
    assert any(f"backfill previous digest sha256:{old_digest}" in note for note in notes)

    row = conn.execute(
        "SELECT mime_type, digest_value, byte_length, filename FROM design_asset"
        " WHERE asset_id = %s AND workspace_id = %s",
        ("asset_backfill_apply", workspace_id),
    ).fetchone()
    assert row == ("font/ttf", new_digest, media["byte_length"], "asset_backfill_apply.ttf")

    assert repo.has_readable_bytes(new_digest)
    served = client.get("/assets/asset_backfill_apply/bytes")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("font/ttf")
    assert served.content[:4] == b"\x00\x01\x00\x00"
    assert TTFont(BytesIO(served.content)).getGlyphOrder() == TTFont(INTER).getGlyphOrder()
    # The original blob is untouched (reversible by hand from the provenance note).
    assert (storage_root / workspace_id / "design" / old_digest).read_bytes() == woff2

    second = script.decode_stored_web_fonts(conn, storage_root, workspace_id=workspace_id, apply=True)
    assert second.decoded == 0 and second.failed == 0


def test_missing_blob_is_reported_not_fatal(client: TestClient, conn, storage_root: Path) -> None:
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    digest = "ab" * 32
    HybridRepository().create_asset_record(
        {
            "id": "asset_backfill_missing",
            "label": "missing.woff2",
            "kind": "font",
            "status": "ready",
            "source": {"kind": "uploaded"},
            "media": {
                "mime_type": "font/woff2",
                "digest": {"algorithm": "sha256", "value": digest},
                "filename": "missing.woff2",
                "byte_length": 10,
                "location": design_location(design_storage_key(workspace_id, digest)),
            },
        }
    )
    summary = load_script().decode_stored_web_fonts(
        conn, storage_root, workspace_id=workspace_id, apply=True
    )
    assert summary.missing == 1 and summary.decoded == 0


def test_corrupt_blob_is_reported_not_fatal(client: TestClient, conn, storage_root: Path) -> None:
    seed_web_font(client, "asset_backfill_corrupt", b"wOF2" + b"\x00" * 96, "font/woff2")
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    summary = load_script().decode_stored_web_fonts(
        conn, storage_root, workspace_id=workspace_id, apply=True
    )
    assert summary.failed == 1 and summary.decoded == 0
    stored = HybridRepository().require_asset_record("asset_backfill_corrupt")["asset"]
    assert stored["media"]["mime_type"] == "font/woff2"  # left exactly as it was
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_decode_stored_web_fonts.py -v
```

Expected: `FileNotFoundError` / `AssertionError` from `load_script()` (the script does not exist).

- [ ] **Step 3: Write the script**

Create `subsystems/clue-design/scripts/decode_stored_web_fonts.py`:

```python
"""One-time migration: decode already-stored WOFF/WOFF2 font assets to sfnt (option A).

Fonts ingested BEFORE 2026-09-02 were stored exactly as harvested — 367 WOFF2 and 2 WOFF faces
across 47 workspaces on the dev store — and none of the engines that read stored fonts speaks
WOFF2 (the SVG embedder refused every one of them; CanvasKit in the browser cannot load them;
FreeType on Linux cannot parse them). New ingests are decoded at the chokepoint
(``lumen_api.font_containers`` via ``CoreClient.ingest_asset``); this script brings existing
rows up to the same invariant so they don't have to be re-ingested.

Reversible by construction: the OLD blob is content-addressed and is NOT deleted — the record's
``provenance.notes`` gains ``backfill previous digest sha256:<old>``, so pointing the row back is
one UPDATE. Idempotent: a row whose bytes already sniff as sfnt is skipped (or, when only the
label lies, relabelled), and decoding is byte-deterministic, so re-runs converge.

A design blob is only readable when its CUSTODY ROW exists (the DAL resolves the digest through
the ``artifact`` table before touching bytes), so ``--apply`` writes the row before the file —
the same shape ``flatten_stored_fragments.py`` learned live on 2026-08-29.

Usage (repo root, env carrying CLUE_DATABASE_URL + CLUE_STORAGE_FS_ROOT):
    .venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py            # dry run
    .venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py --apply
    .venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py --workspace ws_x
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psycopg

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parent / "apps/api"))

from lumen_api.font_containers import (  # noqa: E402
    SFNT_MIME,
    FontContainerError,
    decode_note,
    decode_web_font,
    sfnt_filename,
    sniff_font_container,
)

WEB_MIMES = ("font/woff2", "font/woff", "application/font-woff2", "application/font-woff")


@dataclass
class Summary:
    decoded: int = 0
    relabelled: int = 0
    skipped: int = 0
    missing: int = 0
    failed: int = 0


def _select_rows(conn, workspace_id: Optional[str]):
    sql = (
        "SELECT asset_id, workspace_id, digest_value, mime_type, filename, record_json"
        " FROM design_asset WHERE kind = 'font' AND mime_type = ANY(%(mimes)s)"
    )
    params: dict = {"mimes": list(WEB_MIMES)}
    if workspace_id:
        sql += " AND workspace_id = %(ws)s"
        params["ws"] = workspace_id
    sql += " ORDER BY workspace_id, asset_id"
    return conn.execute(sql, params).fetchall()


def _mirror_custody_row(conn, *, workspace_id: str, old: str, new: str, media_type: str, size: int):
    conn.execute(
        "INSERT INTO artifact"
        " (storage_key, workspace_id, content_sha256, media_type, size_bytes, source_key)"
        " SELECT %(key)s, workspace_id, %(digest)s, %(media_type)s, %(size)s, source_key"
        " FROM artifact"
        " WHERE content_sha256 = %(old)s AND workspace_id = %(ws)s"
        "   AND NOT EXISTS ("
        "     SELECT 1 FROM artifact"
        "     WHERE content_sha256 = %(digest)s AND workspace_id = %(ws)s)"
        " LIMIT 1",
        {
            "key": f"{workspace_id}/design/{new}",
            "digest": new,
            "media_type": media_type,
            "size": size,
            "old": old,
            "ws": workspace_id,
        },
    )


def _update_row(
    conn,
    *,
    asset_id: str,
    workspace_id: str,
    record: dict,
    mime_type: str,
    digest: str,
    byte_length: int,
    filename: Optional[str],
) -> None:
    conn.execute(
        "UPDATE design_asset SET mime_type = %s, digest_value = %s, byte_length = %s,"
        " filename = %s, record_json = %s, updated_at = now()"
        " WHERE asset_id = %s AND workspace_id = %s",
        (mime_type, digest, byte_length, filename, json.dumps(record), asset_id, workspace_id),
    )


def decode_stored_web_fonts(
    conn,
    storage_root: Path,
    *,
    workspace_id: Optional[str] = None,
    apply: bool = False,
) -> Summary:
    summary = Summary()
    for asset_id, ws, digest, mime_type, filename, record in _select_rows(conn, workspace_id):
        record = dict(record or {})
        blob_path = Path(storage_root) / ws / "design" / str(digest)
        if not digest or not blob_path.is_file():
            print(f"MISSING BLOB {ws}/{asset_id}: {digest} — left untouched")
            summary.missing += 1
            continue
        data = blob_path.read_bytes()
        container = sniff_font_container(data)
        media = dict(record.get("media") or {})
        provenance = dict(record.get("provenance") or {})
        notes = list(provenance.get("notes") or [])

        if container in SFNT_MIME:
            # The bytes are already sfnt; only the label lied. Relabel, keep the digest.
            new_mime = SFNT_MIME[container]
            new_name = sfnt_filename(filename, container)
            print(f"RELABEL {ws}/{asset_id}: {mime_type} -> {new_mime} (bytes already sfnt)")
            if apply:
                media["mime_type"] = new_mime
                media["filename"] = new_name
                notes.append(f"backfill relabelled {mime_type} -> {new_mime}; bytes were already sfnt")
                provenance["notes"] = notes
                record["media"], record["provenance"] = media, provenance
                _update_row(
                    conn,
                    asset_id=asset_id,
                    workspace_id=ws,
                    record=record,
                    mime_type=new_mime,
                    digest=digest,
                    byte_length=len(data),
                    filename=new_name,
                )
            summary.relabelled += 1
            continue

        try:
            decoded = decode_web_font(data)
        except FontContainerError as error:
            print(f"FAILED {ws}/{asset_id}: {error} — left untouched")
            summary.failed += 1
            continue
        if decoded is None:
            print(f"SKIP {ws}/{asset_id}: bytes sniff as {container!r}, not a web font")
            summary.skipped += 1
            continue

        new_digest = hashlib.sha256(decoded.data).hexdigest()
        new_name = sfnt_filename(filename, decoded.container)
        print(
            f"{ws}/{asset_id}: {digest[:12]} ({decoded.source_container},{len(data)}B)"
            f" -> {new_digest[:12]} ({decoded.container},{len(decoded.data)}B)"
        )
        if apply:
            new_path = blob_path.with_name(new_digest)
            _mirror_custody_row(
                conn,
                workspace_id=ws,
                old=digest,
                new=new_digest,
                media_type=decoded.mime_type,
                size=len(decoded.data),
            )
            if not new_path.exists():
                new_path.write_bytes(decoded.data)
                new_path.chmod(0o600)
            media["mime_type"] = decoded.mime_type
            media["digest"] = {"algorithm": "sha256", "value": new_digest}
            media["byte_length"] = len(decoded.data)
            media["filename"] = new_name
            media["location"] = {
                "provider": "clue-storage",
                "opaque_ref": f"{ws}/design/{new_digest}",
                "url": None,
            }
            notes.append(decode_note(decoded))
            notes.append(f"backfill previous digest sha256:{digest}")
            provenance["notes"] = notes
            record["media"], record["provenance"] = media, provenance
            _update_row(
                conn,
                asset_id=asset_id,
                workspace_id=ws,
                record=record,
                mime_type=decoded.mime_type,
                digest=new_digest,
                byte_length=len(decoded.data),
                filename=new_name,
            )
        summary.decoded += 1
    if apply:
        conn.commit()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write blobs and update rows")
    parser.add_argument("--workspace", default=None, help="limit to one workspace id")
    args = parser.parse_args()
    database_url = os.environ.get("CLUE_DATABASE_URL", "")
    storage_root = os.environ.get("CLUE_STORAGE_FS_ROOT", "")
    if not database_url or not storage_root:
        print("CLUE_DATABASE_URL and CLUE_STORAGE_FS_ROOT are required", file=sys.stderr)
        return 2
    if not Path(storage_root).is_absolute():
        print("CLUE_STORAGE_FS_ROOT must be absolute (see .env.example)", file=sys.stderr)
        return 2
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    with psycopg.connect(dsn) as conn:
        summary = decode_stored_web_fonts(
            conn, Path(storage_root), workspace_id=args.workspace, apply=args.apply
        )
    mode = "applied" if args.apply else "dry run — nothing written"
    print(
        f"{mode}: {summary.decoded} decoded, {summary.relabelled} relabelled,"
        f" {summary.skipped} skipped, {summary.missing} missing blobs, {summary.failed} failed"
    )
    return 1 if (summary.missing or summary.failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Note on the `provider` string: the test asserts `opaque_ref` only; the provider must be the one `clue_design.storage.design_location` writes (`DESIGN_LOCATION_PROVIDER`, which is `"clue-storage"` — confirm with `grep -n DESIGN_LOCATION_PROVIDER subsystems/design/clue_design/storage.py` and use that exact value).

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_decode_stored_web_fonts.py -v
```

Expected: 4 passed. If the psycopg `record_json` comes back as a `str` rather than a `dict`, wrap it with `json.loads` in `decode_stored_web_fonts` (psycopg 3 returns jsonb as `dict` by default; report if it does not).

- [ ] **Step 5: Dry-run against the colombo dev store (read-only) and paste the summary line**

```bash
set -a; source .env; set +a; .venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py | tail -3
```

Expected: a summary such as `dry run — nothing written: N decoded, 0 relabelled, 0 skipped, M missing blobs, 0 failed` (on 2026-09-02 the store held 369 WOFF/WOFF2 rows; some digests are absent on this box because other worktrees' `.artifacts` roots hold them — `missing` is expected to be non-zero here and is per-environment). Do NOT pass `--apply`; the orchestrator does that in Task 7.

- [ ] **Step 6: Commit**

```bash
git add subsystems/clue-design/scripts/decode_stored_web_fonts.py subsystems/clue-design/apps/api/tests/test_decode_stored_web_fonts.py
git commit -m "feat(design): backfill script decodes stored WOFF/WOFF2 font assets to sfnt

Dry-run by default, --apply writes the custody row before the blob (the DAL resolves
digests through the artifact table), relabels rows whose bytes were already sfnt, leaves the
original blob in place, and records the previous digest in provenance so a row can be
pointed back by hand. Idempotent: re-runs decode nothing."
```

---

### Task 7: Close-out — run the backfill on dev, record the state, keep the streaming excuse honest

**Files:**
- Create: `_memory/2026-09-02-woff2-decode-at-ingestion.md`
- Modify: `_memory/README.md` (one index line, matching the existing entries' shape)
- Modify: `CLAUDE.md` (one backlog bullet under "Backlog / known caveats")
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/render.py:141-148` and `.../tools/substrate.py:5116-5150` (comment-only: point the Task 4b excuse at this plan and its removal condition)

**Interfaces:**
- Consumes: everything above; the operator step needs the design API (`:8060`) and fleet worker restarted afterwards so their in-process caches see nothing stale (they read by digest, so this is belt-and-braces).

- [ ] **Step 1: Full API suite in the background, focused suites inline**

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_font_containers.py apps/api/tests/test_core_ingest_font_normalization.py apps/api/tests/test_ingestion_font_decode.py apps/api/tests/test_export_decoded_web_font.py apps/api/tests/test_web_export.py apps/api/tests/test_decode_stored_web_fonts.py -q
```

Expected: all pass. Then start the full `apps/api/tests` run in the background (never inline; see the design-suite rule) and check its result before declaring the plan done:

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime nohup ../../.venv/bin/python -m pytest apps/api/tests -q -p no:cacheprovider > /tmp/colombo-api-tests-woff2.log 2>&1 &
```

- [ ] **Step 2: Operator step (orchestrator only): apply the backfill on the colombo dev store**

```bash
set -a; source .env; set +a
.venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py | tail -1
.venv/bin/python subsystems/clue-design/scripts/decode_stored_web_fonts.py --apply | tail -1
psql "$CLUE_DATABASE_URL" -Atc "select mime_type, count(*) from design_asset where kind='font' group by 1 order by 2 desc"
```

Expected after `--apply`: the WOFF2/WOFF counts fall to exactly the `missing` count reported (rows whose blobs are not on this box are left as they were), and `font/ttf` / `font/otf` rise by the decoded count. Then restart the colombo design API and fleet worker by PID (colombo ports only: 8060 / 8052; never 3020/8010/8020/8030).

- [ ] **Step 3: Live proof on the Apollo document**

Open the Apollo test document (`doc_1c35a98d45435c7bb8d19408bb9e03e8`) in the editor at `:3033`; the headline must render in Season Mix rather than Inter (compare against a pre-backfill screenshot if one is at hand). Then trigger one design turn and confirm in the worker log that the canonical SVG export no longer reports `SVG font embedding failed` for that run (`grep -c "SVG font embedding failed" <worker log>` on the new run = 0). Record both observations in the memory note.

- [ ] **Step 4: Point the Task 4b excuse at its removal condition**

In `render.py` (the TASK 4b comment block, ~lines 141-148) append one line to the comment:

```python
    # OPTION A (2026-09-02, docs/superpowers/plans/2026-09-02-woff2-font-decode-at-ingestion.md)
    # removes the cause: fonts are stored as sfnt. This excuse stays until the backfill has
    # run on every environment; after that it should be deleted, not kept as belt-and-braces.
```

In `substrate.py` next to `SVG_FONT_EMBEDDING_REFUSAL_MARKER` (~line 5116), append to the comment:

```python
# Since option A (2026-09-02) new ingests never store WOFF2, so this marker only fires for
# faces the backfill (scripts/decode_stored_web_fonts.py) has not reached. Delete the excuse
# once every environment has been backfilled.
```

Run the runtime's own tests for the touched files:

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests -q -k "checkpoint_acceptance or render_gate or font_embedding"
```

Expected: pass (comment-only change).

- [ ] **Step 5: Memory note, index, CLAUDE.md bullet**

Create `_memory/2026-09-02-woff2-decode-at-ingestion.md` with these sections, each filled from what actually happened (counts from the real dry-run / apply lines, the live-proof observations, the full-suite result from `/tmp/colombo-api-tests-woff2.log`):

```markdown
# 2026-09-02 — WOFF2 fonts decoded at ingestion (option A)

## What changed
- `lumen_api/font_containers.py`: lossless WOFF/WOFF2 <-> sfnt (deterministic; brotli now declared).
- `CoreClient.ingest_asset` decodes web fonts before the Rust helper (MIME/filename/provenance rewritten; undecodable → `ingest.font_decode_failed`).
- `web_export._gather_fonts` re-encodes stored sfnt to WOFF2 (zip + hosted `/asset-store/{digest}`), content-addressed.
- `scripts/decode_stored_web_fonts.py` backfill; applied on colombo dev: <paste summary line>.

## Why
<three sentences: the 367/517 finding, the three consumers that only read sfnt, why primary-bytes-sfnt beat a two-blob pointer (Rust record drops unknown fields).>

## Verified
- Focused suites: <counts>. Full `apps/api/tests`: <result>.
- Live: Apollo doc renders Season Mix on the canvas; new design turn's canonical SVG has no font-embedding refusal.

## Follow-ups
- Run the backfill on every other environment (istanbul/nashville worktrees' DBs, staging) before deleting the Task 4b checkpoint excuse (`render.py` / `substrate.py`).
- Rows reported `missing` on this box: <count>; they belong to other worktrees' `.artifacts` roots.
- Rulings still open: fsType license gate (R4), pre-D-F2 kits' `license.embeddable=false` backfill.
```

Add one line to `_memory/README.md` in the same shape as its neighbours pointing at the new note. Add one bullet to `CLAUDE.md`'s "Backlog / known caveats" list:

```markdown
- **[design×fonts] Font assets are stored as sfnt since 2026-09-02 (option A).** `CoreClient.ingest_asset` decodes WOFF/WOFF2 to TTF/OTF; the web lane re-encodes to WOFF2 at export/publish; `scripts/decode_stored_web_fonts.py` backfills existing rows (dry-run default). **Owner action per environment:** run the backfill with `--apply`, then delete the Task 4b checkpoint excuse (`agent_runtime/lumen_agent/tools/render.py` / `substrate.py::SVG_FONT_EMBEDDING_REFUSAL_MARKER`) once every environment is backfilled. The OS/2 fsType license gate in `lumen-skia/src/embed.rs` is unchanged (it blocks nothing in stored data). Plan: `docs/superpowers/plans/2026-09-02-woff2-font-decode-at-ingestion.md`; context `_memory/2026-09-02-woff2-decode-at-ingestion.md`.
```

- [ ] **Step 6: Commit**

```bash
git add _memory/2026-09-02-woff2-decode-at-ingestion.md _memory/README.md CLAUDE.md subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/render.py subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py
git commit -m "docs(memory+claude): option A close-out — WOFF2 decoded at ingestion, backfill applied on dev

Records the change, the dev backfill result, the live proof on the Apollo document, and
the per-environment owner action before the Task 4b checkpoint excuse can be deleted."
```

---

## Self-review notes (done at authoring)

- **Coverage.** Decode primitives (T1), the single ingestion chokepoint covering all five callers (T2), end-to-end proof through the two production doors (T3), the engine-side red/green pin (T4), the web lane keeping WOFF2 (T5), the backfill for the 369 stored rows (T6), operator apply + live proof + records + the 4b excuse's removal condition (T7). No Rust, TypeScript, migration, or env changes anywhere, matching the founder's "zero Rust changes" framing.
- **Consumers deliberately untouched, with the reason:** `brand_kit_font_spec` (engine bytes by primary digest), `/assets/{id}/bytes` (serves the primary), `kitFonts.ts` (fetches by asset id), `font_metrics.py` (fontTools opens either container), the fsType gate (R4).
- **Names used across tasks are consistent:** `decode_web_font`, `encode_woff2`, `sniff_font_container`, `sfnt_filename`, `decode_note`, `SFNT_MIME`, `WEB_CONTAINERS`, `FontContainerError`, `DecodedFont`, `normalize_ingest_font`, `NormalizedIngest`, `INGEST_FONT_DECODE_FAILED`, `_web_face_bytes`, `decode_stored_web_fonts`, `Summary`.
- **Known soft spots an implementer must report rather than patch around:** the public record shape in T3 (`asset["media"]` presence), the `@font-face` family naming in T4 (alias vs intrinsic), the `DESIGN_LOCATION_PROVIDER` literal in T6, and psycopg's jsonb return type in T6.
