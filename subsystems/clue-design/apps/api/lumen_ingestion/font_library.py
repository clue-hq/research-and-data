"""Curated open-font library — provisioning (Track B, agents/font-library-v0).

A "library font" is a font that is always present, independent of any brand
kit: the curated families below are materialized from a pinned checkout of
github.com/google/fonts into the content-addressed asset store, measured with
the same fontTools path kit fonts use, and published as a checked-in manifest
(`apps/api/font-library/manifest.json`). The render paths then merge library
faces into the same `{store_root, faces:[{digest, family}]}` spec kit fonts
ride today, so both runtimes shape library text with real bytes.

Two contracts are deliberately inherited from the kit-font machinery:

* **Static instances, one face per weight.** The server FontManager registers
  a typeface at its parsed family + OS/2 weight; a raw variable TTF would
  register only its default instance and silently render bold headlines at
  weight 400. Variable sources are therefore instanced per curated weight at
  provisioning time (all non-wght axes pinned to their fvar defaults).
  Variable-axis support arrives with Typography v1, which rebases on this.
* **Fail-loud glyph coverage.** The archetype baseline sweep shipped tofu
  because a kit font silently lacked "/", "x", and the em-dash. Every library
  face is checked against REQUIRED_GLYPHS at provisioning; a gap is an error,
  not a warning, and the coverage report is stamped into the manifest.

Determinism: same google/fonts commit + same fontTools version => identical
instance bytes => identical sha256 digests => the checked-in manifest is valid
for every environment that runs the provisioning script. The manifest records
both pins so drift fails loudly in `--check` mode.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

JsonObject = Dict[str, Any]

# ---------------------------------------------------------------------------
# Curation — the taste layer. Tone tags and pairing hints are agent-facing:
# the agent chooses from a text inventory, so fonts need usage notes for the
# same reason kit imagery does.
# ---------------------------------------------------------------------------

#: Weight name <-> numeric map used both to locate static files
#: (e.g. "ZillaSlab-Medium.ttf") and to label instanced faces.
WEIGHT_NAMES: Dict[int, str] = {
    100: "Thin",
    200: "ExtraLight",
    300: "Light",
    400: "Regular",
    500: "Medium",
    600: "SemiBold",
    700: "Bold",
    800: "ExtraBold",
    900: "Black",
}


@dataclass(frozen=True)
class CuratedFamily:
    slug: str
    family: str
    directory: str  # relative to the google/fonts checkout root
    category: str  # sans | serif | slab | mono | display
    weights: tuple  # curated numeric weights, validated against the source
    tone: tuple  # agent-facing tone tags
    pairing: str  # one-line pairing hint
    notes: str = ""  # extra agent-facing guidance (caps-only faces etc.)
    #: Curated numeric weights that also get an ITALIC face (A7b). Empty for
    #: families with no italic source (all display faces + a few sans). Each
    #: weight here must appear in `weights` too and lie inside the italic
    #: source's wght range; a MaterializedFace(style="italic") is produced per
    #: entry, after the upright faces.
    italic_weights: tuple = ()


CURATED_FAMILIES: List[CuratedFamily] = [
    # --- Workhorse sans -----------------------------------------------------
    CuratedFamily(
        "inter", "Inter", "ofl/inter", "sans", (400, 500, 600, 700, 800),
        ("neutral", "ui", "systematic"),
        "The default voice; pairs with any display or serif face.",
        "Also the engine's bundled fallback — using it is never a risk.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "dm-sans", "DM Sans", "ofl/dmsans", "sans", (400, 500, 600, 700, 800),
        ("geometric", "friendly", "startup"),
        "Rounded geometry; pairs well with Fraunces or Playfair Display.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "manrope", "Manrope", "ofl/manrope", "sans", (400, 500, 600, 700, 800),
        ("modern", "semi-geometric", "tech"),
        "Crisp product voice; pairs with Newsreader for editorial contrast.",
    ),
    CuratedFamily(
        "sora", "Sora", "ofl/sora", "sans", (400, 500, 600, 700, 800),
        ("techy", "futuristic", "product"),
        "Wide techy counters; strong for SaaS and AI subjects.",
    ),
    CuratedFamily(
        "space-grotesk", "Space Grotesk", "ofl/spacegrotesk", "sans",
        (400, 500, 600, 700),
        ("quirky-grotesque", "tech-editorial", "distinctive"),
        "Distinctive at display sizes; body text works but keep it short.",
    ),
    CuratedFamily(
        "plus-jakarta-sans", "Plus Jakarta Sans", "ofl/plusjakartasans", "sans",
        (400, 500, 600, 700, 800),
        ("warm-geometric", "contemporary", "brandable"),
        "Warm geometric; a safe modern default when Inter feels too plain.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "outfit", "Outfit", "ofl/outfit", "sans", (400, 500, 600, 700, 800),
        ("clean-geometric", "minimal", "display-friendly"),
        "Geometric enough to carry headlines on minimal layouts.",
    ),
    CuratedFamily(
        "work-sans", "Work Sans", "ofl/worksans", "sans", (400, 500, 600, 700, 800),
        ("workhorse", "neutral-warm", "editorial"),
        "Quiet editorial workhorse; pairs with Lora or Source Serif 4.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "archivo", "Archivo", "ofl/archivo", "sans", (400, 500, 600, 700, 800),
        ("grotesque", "sturdy", "poster-capable"),
        "Sturdy grotesque; use Archivo Black for full-impact posters.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "hanken-grotesk", "Hanken Grotesk", "ofl/hankengrotesk", "sans",
        (400, 500, 600, 700, 800),
        ("humanist", "calm", "readable"),
        "Humanist and calm; good for healthcare, finance, trust subjects.",
        italic_weights=(400,),
    ),
    # --- Serif --------------------------------------------------------------
    CuratedFamily(
        "fraunces", "Fraunces", "ofl/fraunces", "serif", (400, 500, 600, 700, 900),
        ("display-serif", "expressive", "warm", "editorial"),
        "Soft old-style display serif; hero headlines over DM Sans or Inter body.",
        italic_weights=(400, 600),
    ),
    CuratedFamily(
        "playfair-display", "Playfair Display", "ofl/playfairdisplay", "serif",
        (400, 500, 600, 700, 800),
        ("high-contrast", "elegant", "luxury"),
        "High-contrast elegance; luxury and fashion headlines, never body.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "lora", "Lora", "ofl/lora", "serif", (400, 500, 600, 700),
        ("readable-serif", "calm", "body"),
        "Calm text serif; body copy under a grotesque display face.",
        italic_weights=(400, 700),
    ),
    CuratedFamily(
        "source-serif-4", "Source Serif 4", "ofl/sourceserif4", "serif",
        (400, 500, 600, 700, 800),
        ("sturdy-serif", "editorial", "body"),
        "Sturdy editorial serif; long copy and pull-quotes.",
        italic_weights=(400, 600),
    ),
    CuratedFamily(
        "newsreader", "Newsreader", "ofl/newsreader", "serif",
        (400, 500, 600, 700, 800),
        ("news-editorial", "refined", "text"),
        "Refined news voice; pairs with Manrope or Archivo.",
        italic_weights=(400, 500),
    ),
    CuratedFamily(
        "instrument-serif", "Instrument Serif", "ofl/instrumentserif", "serif",
        (400,),
        ("display-serif", "fashionable", "condensed-elegant"),
        "Single-weight display serif with a fashionable, condensed elegance.",
        "One weight only (400) — scale with size, not weight.",
        italic_weights=(400,),
    ),
    # --- Slab ---------------------------------------------------------------
    CuratedFamily(
        "zilla-slab", "Zilla Slab", "ofl/zillaslab", "slab", (400, 500, 600, 700),
        ("slab", "friendly-technical"),
        "Friendly technical slab; developer and maker subjects.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "bitter", "Bitter", "ofl/bitter", "slab", (400, 500, 600, 700, 800),
        ("slab", "contemporary", "readable"),
        "Contemporary readable slab; headlines and body both work.",
        italic_weights=(400, 700),
    ),
    # --- Mono ---------------------------------------------------------------
    CuratedFamily(
        "jetbrains-mono", "JetBrains Mono", "ofl/jetbrainsmono", "mono", (400, 700),
        ("code", "technical"),
        "Code voice; terminal snippets, specs, dev-tool ads.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "ibm-plex-mono", "IBM Plex Mono", "ofl/ibmplexmono", "mono", (400, 500, 600, 700),
        ("code", "technical-corporate"),
        "Corporate-technical mono; data, engineering, enterprise subjects.",
        italic_weights=(400,),
    ),
    CuratedFamily(
        "space-mono", "Space Mono", "ofl/spacemono", "mono", (400, 700),
        ("retro-tech", "display-mono", "quirky"),
        "Quirky retro mono; eyebrow labels and display accents, not long copy.",
        italic_weights=(400,),
    ),
    # --- Display / impact ---------------------------------------------------
    CuratedFamily(
        "anton", "Anton", "ofl/anton", "display", (400,),
        ("condensed-impact", "poster", "loud"),
        "Condensed poster impact; huge single-word headlines.",
        "One weight; designed for large sizes and tight leading.",
    ),
    CuratedFamily(
        "bebas-neue", "Bebas Neue", "ofl/bebasneue", "display", (400,),
        ("condensed-caps", "classic-ad", "tall"),
        "The classic tall-caps ad face; all-caps headlines only.",
        "Caps-only design — lowercase input renders as small caps.",
    ),
    CuratedFamily(
        "archivo-black", "Archivo Black", "ofl/archivoblack", "display", (400,),
        ("heavy-impact", "poster", "grotesque"),
        "Maximum-weight grotesque; short shouting headlines.",
        "One weight (visually ~900); the display cut of Archivo.",
    ),
    CuratedFamily(
        "bricolage-grotesque", "Bricolage Grotesque", "ofl/bricolagegrotesque",
        "display", (400, 600, 700, 800),
        ("characterful-grotesque", "editorial-punch"),
        "Characterful grotesque with editorial punch; headlines and stats.",
    ),
    CuratedFamily(
        "unbounded", "Unbounded", "ofl/unbounded", "display", (400, 700, 800),
        ("wide-futuristic", "crypto-tech"),
        "Wide futuristic display; web3/AI/frontier-tech subjects.",
    ),
    CuratedFamily(
        "syne", "Syne", "ofl/syne", "display", (400, 700, 800),
        ("art-house", "wide-display", "distinctive"),
        "Art-house wide display; culture, studios, portfolio subjects.",
    ),
]

# ---------------------------------------------------------------------------
# Glyph coverage — the fail-loud lesson from the archetype baseline sweep
# (kit Aeonik shipped tofu for "/", the multiplication sign, and the em-dash).
# ---------------------------------------------------------------------------

#: Every library face must cover ALL of these. Printable ASCII plus the
#: typographic characters ad copy actually uses.
REQUIRED_GLYPHS: str = (
    "".join(chr(c) for c in range(0x20, 0x7F))  # printable ASCII incl. "/"
    + "×"  # × multiplication sign (the "10×" stat)
    + "—–"  # — em dash, – en dash
    + "‘’“”"  # ‘ ’ “ ” smart quotes
    + "…"  # … ellipsis
    + "•·"  # • bullet, · middle dot
    + "°"  # ° degree
)

#: Coverage gaps here are reported in the manifest but do not fail
#: provisioning — the agent-facing notes can warn instead.
OPTIONAL_GLYPHS: str = "€£¥−→←®©™"


def glyph_coverage(cmap: Dict[int, Any]) -> JsonObject:
    """Coverage report for a font's unicode cmap: which REQUIRED_GLYPHS are
    missing (a provisioning error) and which OPTIONAL_GLYPHS are (a note)."""
    missing_required = [ch for ch in REQUIRED_GLYPHS if ord(ch) not in cmap]
    missing_optional = [ch for ch in OPTIONAL_GLYPHS if ord(ch) not in cmap]
    return {
        "required_ok": not missing_required,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
    }


# ---------------------------------------------------------------------------
# Source resolution + static instancing
# ---------------------------------------------------------------------------


class FontLibraryError(RuntimeError):
    """Loud provisioning failure — a curated family that cannot be
    materialized correctly must stop the run, not degrade silently."""


def _ttfont(data: bytes):
    from fontTools.ttLib import TTFont

    # recalcTimestamp=False keeps head.modified stable => deterministic bytes
    # => stable sha256 digests across environments and re-runs.
    return TTFont(io.BytesIO(data), recalcTimestamp=False, recalcBBoxes=False)


def _find_variable_source(directory: Path, family: str) -> Optional[Path]:
    """The upright variable TTF, e.g. ``Fraunces[SOFT,WONK,opsz,wght].ttf``.
    The bracket glob matches ``[`` immediately after the compact family name,
    so it deliberately EXCLUDES the italic sibling ``{compact}-Italic[...].ttf``
    (the ``-Italic`` breaks the ``[`` adjacency) — see ``_find_italic_source``."""
    compact = family.replace(" ", "")
    candidates = sorted(directory.glob(f"{compact}[[]*wght*[]].ttf"))
    return candidates[0] if candidates else None


def _find_italic_source(directory: Path, family: str) -> Optional[Path]:
    """The italic variable TTF (A7b), e.g.
    ``Fraunces-Italic[SOFT,WONK,opsz,wght].ttf`` or ``Lora-Italic[wght].ttf``.
    Same ``[...wght...]`` bracket shape as the upright source but gated on the
    ``-Italic`` infix; ``_instance_bytes`` pins every non-wght axis (incl.
    Archivo's ``wdth``) to its fvar default, so the same instancer path
    produces a static italic face per curated weight."""
    compact = family.replace(" ", "")
    candidates = sorted(directory.glob(f"{compact}-Italic[[]*wght*[]].ttf"))
    return candidates[0] if candidates else None


def _find_static_source(directory: Path, family: str, weight: int) -> Optional[Path]:
    compact = family.replace(" ", "")
    name = WEIGHT_NAMES.get(weight)
    if name is None:
        return None
    path = directory / f"{compact}-{name}.ttf"
    return path if path.is_file() else None


def _find_static_italic_source(
    directory: Path, family: str, weight: int
) -> Optional[Path]:
    """Static italic face for families with no italic VF (instrument-serif,
    zilla-slab, ibm-plex-mono, space-mono). Google names weight-400 italics
    ``{compact}-Italic.ttf`` and heavier ones ``{compact}-{Weight}Italic.ttf``
    (e.g. ``ZillaSlab-BoldItalic.ttf``). Verified against the pinned clone: all
    four curate weight 400 only, so ``{compact}-Italic.ttf`` is the real file;
    the weighted form is coded for completeness."""
    compact = family.replace(" ", "")
    if weight == 400:
        path = directory / f"{compact}-Italic.ttf"
        return path if path.is_file() else None
    name = WEIGHT_NAMES.get(weight)
    if name is None:
        return None
    path = directory / f"{compact}-{name}Italic.ttf"
    return path if path.is_file() else None


def _instance_bytes(source: bytes, weight: int, family: str) -> bytes:
    """Pin wght to `weight` and every other fvar axis to its default,
    producing a fully static face. instancer updates OS/2.usWeightClass, which
    is what the server FontManager matches on."""
    from fontTools.varLib import instancer

    font = _ttfont(source)
    fvar = font.get("fvar")
    if fvar is None:
        raise FontLibraryError(f"{family}: expected a variable source, got static")
    axes = {axis.axisTag: axis for axis in fvar.axes}
    if "wght" not in axes:
        raise FontLibraryError(f"{family}: variable source has no wght axis")
    wght = axes["wght"]
    if not (wght.minValue <= weight <= wght.maxValue):
        raise FontLibraryError(
            f"{family}: curated weight {weight} outside wght range "
            f"[{wght.minValue}, {wght.maxValue}]"
        )
    pins = {
        tag: (float(weight) if tag == "wght" else axis.defaultValue)
        for tag, axis in axes.items()
    }
    static = instancer.instantiateVariableFont(font, pins, inplace=False)
    buffer = io.BytesIO()
    static.save(buffer)
    return buffer.getvalue()


@dataclass
class MaterializedFace:
    weight: int
    style: str
    bytes_: bytes
    filename: str
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        self.digest = hashlib.sha256(self.bytes_).hexdigest()


def materialize_family(
    fonts_repo: Path, curated: CuratedFamily
) -> tuple[List[MaterializedFace], JsonObject]:
    """Produce one static face per curated weight plus the family's glyph
    coverage report. Raises FontLibraryError on any gap — a partially
    materialized library is worse than a loudly failed run."""
    directory = fonts_repo / curated.directory
    if not directory.is_dir():
        raise FontLibraryError(f"{curated.family}: missing {directory}")

    compact = curated.family.replace(" ", "")
    variable_source = _find_variable_source(directory, curated.family)
    faces: List[MaterializedFace] = []
    for weight in curated.weights:
        if variable_source is not None:
            data = _instance_bytes(
                variable_source.read_bytes(), weight, curated.family
            )
            stem = f"{compact}-{WEIGHT_NAMES[weight]}"
        else:
            static = _find_static_source(directory, curated.family, weight)
            if static is None:
                raise FontLibraryError(
                    f"{curated.family}: no static file for weight {weight} "
                    f"and no variable source in {directory}"
                )
            data = static.read_bytes()
            stem = static.stem
        faces.append(
            MaterializedFace(
                weight=weight, style="normal", bytes_=data, filename=f"{stem}.ttf"
            )
        )

    # A7b: italic faces, after the uprights. VF italic sources are instanced
    # per curated weight (same instancer path as uprights, non-wght axes pinned
    # to fvar defaults); static-only families read the matching -Italic file.
    italic_variable_source = _find_italic_source(directory, curated.family)
    for weight in curated.italic_weights:
        if italic_variable_source is not None:
            data = _instance_bytes(
                italic_variable_source.read_bytes(), weight, curated.family
            )
        else:
            static = _find_static_italic_source(directory, curated.family, weight)
            if static is None:
                raise FontLibraryError(
                    f"{curated.family}: no italic file for weight {weight} "
                    f"and no italic variable source in {directory}"
                )
            data = static.read_bytes()
        stem = f"{compact}-{WEIGHT_NAMES[weight]}Italic"
        faces.append(
            MaterializedFace(
                weight=weight, style="italic", bytes_=data, filename=f"{stem}.ttf"
            )
        )

    coverage = glyph_coverage(_ttfont(faces[0].bytes_).getBestCmap())
    if not coverage["required_ok"]:
        missing = ", ".join(
            f"U+{ord(ch):04X} {ch!r}" for ch in coverage["missing_required"]
        )
        raise FontLibraryError(
            f"{curated.family}: missing required glyphs: {missing} — "
            "a library face that would ship tofu cannot be provisioned"
        )
    # The glyph-coverage gate applies to the first italic face too — a tofu
    # italic (e.g. an emphasis face lacking the em-dash) must fail loudly, not
    # ship. Manifest records the upright coverage; the italic gate is guard-only.
    first_italic = next((f for f in faces if f.style == "italic"), None)
    if first_italic is not None:
        italic_coverage = glyph_coverage(_ttfont(first_italic.bytes_).getBestCmap())
        if not italic_coverage["required_ok"]:
            missing = ", ".join(
                f"U+{ord(ch):04X} {ch!r}"
                for ch in italic_coverage["missing_required"]
            )
            raise FontLibraryError(
                f"{curated.family} (italic): missing required glyphs: {missing} — "
                "a library face that would ship tofu cannot be provisioned"
            )
    return faces, coverage


# ---------------------------------------------------------------------------
# Provisioning — asset store + records + manifest
# ---------------------------------------------------------------------------

LIBRARY_TAG = "font-library"

_LICENSE_RECORD = {
    "name": "OFL-1.1",
    "allow_export": True,
    "allow_modification": True,
    "allow_embedding": True,
    "allow_subsetting": True,
    "source_url": "https://openfontlicense.org",
    "restrictions": [],
}


def face_asset_id(slug: str, weight: int, digest: str, style: str = "normal") -> str:
    """Deterministic: same bytes => same id => idempotent re-provisioning.
    Italic faces carry an ``i`` after the weight (``..._w400i_<digest>``) so
    the id is legible and cannot collide with the upright of the same weight;
    upright ids are unchanged (no suffix), keeping every pre-A7b id stable."""
    suffix = "i" if style == "italic" else ""
    return f"asset_font_lib_{slug.replace('-', '_')}_w{weight}{suffix}_{digest[:12]}"


def provision_family(
    curated: CuratedFamily,
    faces: List[MaterializedFace],
    coverage: JsonObject,
    metrics: Optional[JsonObject],
    ingest: Callable[..., JsonObject],
    create_record: Callable[[JsonObject], JsonObject],
    store_root: str,
    google_fonts_commit: str,
) -> JsonObject:
    """Ingest each face into the asset store + SQLite, returning the family's
    manifest entry. `ingest` is CoreClient.ingest_asset (kwargs subset);
    `create_record` is Repository.create_asset_record."""
    manifest_faces: List[JsonObject] = []
    for face in faces:
        asset_id = face_asset_id(curated.slug, face.weight, face.digest, face.style)
        style_label = " Italic" if face.style == "italic" else ""
        response = ingest(
            store_root=store_root,
            bytes_base64=base64.b64encode(face.bytes_).decode("ascii"),
            asset_id=asset_id,
            label=f"{curated.family} {WEIGHT_NAMES[face.weight]}{style_label} (font library)",
            declared_mime_type="font/ttf",
            filename=face.filename,
            kind="font",
            license=dict(_LICENSE_RECORD),
            provenance={
                "source_label": "google-fonts library provisioning",
                "notes": [
                    f"google/fonts commit {google_fonts_commit}",
                    f"curated family {curated.slug}",
                ],
            },
            source={
                "kind": "url",
                "url": f"https://github.com/google/fonts/tree/{google_fonts_commit}/{curated.directory}",
            },
            tags=["font", LIBRARY_TAG, curated.slug],
        )
        record = (response.get("asset") or {}).get("record") or {}
        if not record.get("id"):
            raise FontLibraryError(
                f"{curated.family}: ingest returned no record for {asset_id}"
            )
        stored_digest = ((record.get("media") or {}).get("digest") or {}).get("value")
        if stored_digest != face.digest:
            raise FontLibraryError(
                f"{curated.family}: store digest {stored_digest} != computed {face.digest}"
            )
        # The helper cannot populate FontAssetMetadata (it never parses font
        # tables); stamp it here so the record is honest about what it holds.
        record["kind"] = "font"
        record["font"] = {
            "family": curated.family,
            "postscript_name": None,
            "weights": [face.weight],
            "styles": [face.style],
            "scripts": ["latin"],
            "embeddable": True,
            "subsettable": True,
        }
        create_record(record)
        manifest_faces.append(
            {
                "weight": face.weight,
                "style": face.style,
                "asset_id": record["id"],
                "digest": face.digest,
                "byte_length": len(face.bytes_),
            }
        )
    return {
        "slug": curated.slug,
        "family": curated.family,
        "category": curated.category,
        "tone": list(curated.tone),
        "pairing": curated.pairing,
        **({"notes": curated.notes} if curated.notes else {}),
        "license": {
            "name": "OFL-1.1",
            "embeddable": True,
            "subsettable": True,
            "source_url": "https://openfontlicense.org",
        },
        **({"metrics": metrics} if metrics else {}),
        "glyph_coverage": {
            "required_ok": True,
            "missing_optional": coverage["missing_optional"],
        },
        "faces": manifest_faces,
    }


def build_manifest(
    families: List[JsonObject], google_fonts_commit: str, fonttools_version: str
) -> JsonObject:
    return {
        "version": 1,
        "provenance": {
            "google_fonts_repo": "https://github.com/google/fonts",
            "google_fonts_commit": google_fonts_commit,
            "fonttools_version": fonttools_version,
            "script": "scripts/provision_font_library.py",
        },
        "families": families,
    }


def write_manifest(manifest: JsonObject, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Agent teaching — the knowledge doc is GENERATED from the manifest so the
# inventory the agent reads can never drift from what the engine can load.
# ---------------------------------------------------------------------------

_AGENT_DOC_PREAMBLE = """\
# The font library

<!-- GENERATED by scripts/provision_font_library.py — edit the curation table
     in apps/api/lumen_ingestion/font_library.py and re-run; do not hand-edit. -->

A curated set of open (OFL) families that is ALWAYS loadable, in every run,
with or without a brand kit. Both the server renderer and the editor load a
library family the moment a scene references it — `font("Fraunces",64,600,left)`
just works.

Rules:

- **Kit fonts first.** When the run has a brand kit, its declared families are
  the brand voice — the library never replaces them for text the kit already
  covers. Reach for the library when the kit lacks a face for a role (e.g. no
  display face for a poster headline) and brand adherence allows a neighbor,
  or for deliberately non-brand surfaces (specimen chrome, code snippets).
- **No-kit runs choose from this list, by tone.** Defaulting everything to
  Inter is a missed decision, not a safe one: pick a voice that matches the
  brief and say so in your direction notes.
- **Exact names, listed weights only.** Family resolution is an exact string
  match on the names below. A weight that is not listed snaps silently to the
  nearest loaded face — use the listed weights.
- Every family below covers the full ad-copy glyph set ("/", "x"-sign, em
  dash, smart quotes); families missing arrow glyphs are flagged in notes.
- Pair one display voice with one workhorse; two display faces on a canvas
  fight each other.
- **Italics exist only for the families and weights in the Italics column** —
  the display faces have none. Asking for italic on a family/weight with no
  italic face renders upright and emits an advisory (LUMS0105); choose an
  emphasis role from a family that lists the italic weight you need.
"""


def render_agent_inventory(manifest: JsonObject) -> str:
    lines = [_AGENT_DOC_PREAMBLE]
    by_category: Dict[str, List[JsonObject]] = {}
    for family in manifest.get("families") or []:
        by_category.setdefault(str(family.get("category")), []).append(family)
    titles = {
        "sans": "Workhorse sans",
        "serif": "Serif",
        "slab": "Slab",
        "mono": "Mono",
        "display": "Display / impact",
    }
    for category in ("sans", "serif", "slab", "mono", "display"):
        families = by_category.get(category)
        if not families:
            continue
        lines.append(f"\n## {titles[category]}\n")
        lines.append("| Family | Weights | Italics | Tone | Use |")
        lines.append("|---|---|---|---|---|")
        for family in families:
            # Filter to upright faces — italic faces reuse curated weights, so
            # counting them here would double-list every italic weight.
            weights = ", ".join(
                str(face["weight"])
                for face in family["faces"]
                if face.get("style", "normal") == "normal"
            )
            italic_weights = [
                str(face["weight"])
                for face in family["faces"]
                if face.get("style") == "italic"
            ]
            italics = ", ".join(italic_weights) if italic_weights else "—"
            tone = ", ".join(family.get("tone") or [])
            use = str(family.get("pairing") or "")
            notes = str(family.get("notes") or "")
            missing = (family.get("glyph_coverage") or {}).get("missing_optional") or []
            arrow_gap = any(ch in ("→", "←") for ch in missing)
            details = " ".join(
                part
                for part in (notes, "No arrow glyphs." if arrow_gap else "")
                if part
            )
            if details:
                use = f"{use} {details}".strip()
            lines.append(
                f"| {family['family']} | {weights} | {italics} | {tone} | {use} |"
            )
    return "\n".join(lines) + "\n"


def write_agent_inventory(manifest: JsonObject, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_agent_inventory(manifest))
