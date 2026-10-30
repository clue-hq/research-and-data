"""Fast-loop v1 §5.1 — the composed frame payload ("push context, don't fetch it").

WHY. In the 43-minute baseline run the author *discovered* its context: 71
``read_file`` calls, 43 greps and 22 ``ls`` calls, ~75 model calls before the
first preview existed. Every one of those lookups asked the filesystem for
something the harness already held in memory — the brand card, the scene, the
kit's asset manifest, the same four knowledge files every scene turn reads. This
module hands all of it to the author in its opening context instead, so the
first compile can be the author's first or second act.

Acceptance (spec §5.1): a clean flag-on run issues ZERO ``grep``/``glob``/``ls``
calls and reaches its first compile within 3 model calls. The zero-search half
is what this module buys; the tests pin the assertable part — that the composed
payload really carries the brand card, the type ramp, the scene digest, the
asset index and the pinned knowledge inline.

WHAT IS *NOT* HERE. The round direction. It is written per round by the
orchestrator, long after this payload is composed at assembly time, so §5.1's
"round direction" arrives through the other half of the mechanism: the flag-on
orchestrator prompt requires the direction to be written INLINE in the ``task``
description (as well as to ``direction.md`` for the record), which makes it part
of the author's opening context without a lookup. Reading one named file is not
searching; hunting for it is.

BOUNDED BY CONSTRUCTION. Every section has an explicit cap and says so when it
truncates (no silent caps): the scene digest degrades to the summary form past
``MAX_DIGEST_NODES``, the asset index caps at ``MAX_ASSET_ROWS``, and each
pinned file caps at ``MAX_PINNED_CHARS``. The payload rides the author's SYSTEM
prompt, which is assembled once per turn and never mutated — so it is inside the
cache-stable prefix the harness's L1 invariant protects, and it is paid for once
rather than per call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from py_lumen_obs import get_logger

from .brand_card import render_brand_card_text

logger = get_logger("lumen_agent.frame")

JsonObject = dict[str, Any]

#: The default pin set for a scene turn: the four documents the baseline run
#: went back to the disk for over and over. Paths are relative to
#: ``apps/agent_runtime/knowledge_docs/`` (the tree `materialize.py` copies).
#: ~24K characters total, once, in a cached prefix — against 71 file reads.
#: `LUMEN_AGENT_FAST_LOOP_PINNED_KNOWLEDGE` overrides the list; that env var is
#: also the seam a format skill's `pinned_knowledge:` manifest field feeds once
#: pre-dispatch skill selection exists (see the spec's §5.1 as-built note).
DEFAULT_PINNED_KNOWLEDGE: tuple[str, ...] = (
    "knowledge/lumen-dsl/grammar.md",
    "knowledge/lumen-dsl/directives.md",
    "knowledge/design-systems/brand-application.md",
    "knowledge/design/artboard-frame-authoring.md",
)

#: Past this node count the digest degrades to the scene SUMMARY form and tells
#: the author to `inspect` the rest. A 400-node document pinned whole would cost
#: more than the lookups it saves.
MAX_DIGEST_NODES = 120

#: Asset-index rows. Kits run ~13 image slots plus logo variants; 40 covers a
#: realistic kit whole, and an overflow line names what was left out.
MAX_ASSET_ROWS = 40

#: Per-pinned-file character cap. The largest default pin (grammar.md) is ~12K.
MAX_PINNED_CHARS = 24_000

# ---------------------------------------------------------------------------
# The type ramp
# ---------------------------------------------------------------------------

#: The canvas the pilot skill's numbers are written against (`§8`: headline
#: "≥64px on 1080", body "≥22px"). Every floor below is that number expressed as
#: a fraction of the 1080 short edge, so the ramp reproduces the spec's own
#: figures exactly at 1080 and scales honestly off it.
REFERENCE_SHORT_EDGE = 1080.0

#: role → (fraction of the canvas short edge, absolute floor in px).
#: 0.0593 × 1080 = 64. 0.0204 × 1080 = 22. 0.0222 × 1080 = 24.
TYPE_FLOOR_FRACTIONS: dict[str, tuple[float, float]] = {
    "type.display": (0.0593, 32.0),
    "type.headline": (0.0444, 24.0),
    "type.body": (0.0204, 14.0),
    "type.cta": (0.0222, 14.0),
    "type.eyebrow": (0.0130, 11.0),
}

#: The kit's authored sizes are scaled by (short edge / 1080), clamped so a
#: business card does not shrink type to nothing and a billboard does not
#: multiply it past the grid.
TYPE_SCALE_CLAMP = (0.5, 4.0)


def resolve_type_ramp(
    brand_card: Optional[JsonObject],
    *,
    width: Optional[float],
    height: Optional[float],
) -> JsonObject:
    """The kit's type roles RESOLVED onto this canvas.

    A brand card states each role's authored size in the abstract; what the
    author actually needs is "how big is `$type.display` on THIS artboard, and
    what is the floor below which it stops reading". That arithmetic is
    deterministic, so the model should never be doing it — and in the baseline
    run it was doing it badly (an unreadable CTA was one of the two defects a
    render would have caught).

    Returns a dict with the canvas, the scale factor, and one row per role:
    ``kit_size`` (as authored), ``resolved`` (scaled to this canvas) and
    ``floor`` (the legibility floor for this canvas). When the canvas is not yet
    declared — a create turn starts with ZERO pages, the author declares the
    first one — the floors are given as fractions plus the worked 1080 example,
    and the ramp says so rather than inventing dimensions.
    """
    roles = ((brand_card or {}).get("type_roles") or {}) if brand_card else {}
    short_edge = None
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        if width > 0 and height > 0:
            short_edge = float(min(width, height))

    if short_edge is None:
        scale = 1.0
    else:
        raw = short_edge / REFERENCE_SHORT_EDGE
        scale = max(TYPE_SCALE_CLAMP[0], min(TYPE_SCALE_CLAMP[1], raw))

    rows: list[JsonObject] = []
    for role, (fraction, absolute_floor) in TYPE_FLOOR_FRACTIONS.items():
        entry = roles.get(role) if isinstance(roles, dict) else None
        kit_size = (entry or {}).get("size") if isinstance(entry, dict) else None
        row: JsonObject = {
            "role": role,
            "family": (entry or {}).get("family") if isinstance(entry, dict) else None,
            "weight": (entry or {}).get("weight") if isinstance(entry, dict) else None,
            "kit_size": kit_size,
            "floor_fraction_of_short_edge": fraction,
        }
        if short_edge is not None:
            row["floor"] = round(max(fraction * short_edge, absolute_floor))
            if isinstance(kit_size, (int, float)):
                row["resolved"] = round(float(kit_size) * scale)
        else:
            row["floor_at_1080"] = round(max(fraction * REFERENCE_SHORT_EDGE, absolute_floor))
        rows.append(row)

    ramp: JsonObject = {
        "canvas": (
            {"width": width, "height": height, "short_edge": short_edge}
            if short_edge is not None
            else None
        ),
        "scale_vs_1080": round(scale, 3) if short_edge is not None else None,
        "roles": rows,
    }
    if short_edge is None:
        ramp["note"] = (
            "This scene has no page yet, so the ramp cannot be resolved to pixels. "
            "The floors are given as fractions of the canvas SHORT EDGE (and worked "
            "at 1080). Multiply by your declared short edge the moment you write the "
            "page line — do not guess a size that this table can give you exactly."
        )
    return ramp


def _render_type_ramp(ramp: JsonObject) -> str:
    lines: list[str] = []
    canvas = ramp.get("canvas")
    if canvas:
        lines.append(
            f"Canvas {canvas.get('width')}×{canvas.get('height')} "
            f"(short edge {canvas.get('short_edge')}); kit sizes scaled "
            f"×{ramp.get('scale_vs_1080')}."
        )
        lines.append("")
        lines.append(
            "| role | family | weight | kit size | resolved on this canvas "
            "| legibility floor |"
        )
        lines.append("|---|---|---|---|---|---|")
        for row in ramp.get("roles") or []:
            lines.append(
                f"| {row.get('role')} | {row.get('family') or '—'} | "
                f"{row.get('weight') or '—'} | {row.get('kit_size') or '—'} | "
                f"{row.get('resolved') or '—'} | {row.get('floor')} |"
            )
    else:
        lines.append(ramp.get("note") or "")
        lines.append("")
        lines.append("| role | family | weight | kit size | floor (× short edge) | floor at 1080 |")
        lines.append("|---|---|---|---|---|---|")
        for row in ramp.get("roles") or []:
            lines.append(
                f"| {row.get('role')} | {row.get('family') or '—'} | "
                f"{row.get('weight') or '—'} | {row.get('kit_size') or '—'} | "
                f"{row.get('floor_fraction_of_short_edge')} | {row.get('floor_at_1080')} |"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The scene digest
# ---------------------------------------------------------------------------


def build_scene_digest(tools: Any) -> JsonObject:
    """The `inspect` summary form, composed rather than fetched.

    `inspect(view="scene")` plus `inspect(view="page")` for every page — the two
    calls a grounded author makes first — resolved here into one block. Past
    ``MAX_DIGEST_NODES`` the per-page node trees are dropped and the digest says
    so, because a huge document is exactly the case where targeted `inspect`
    beats a wholesale pin.
    """
    summary = tools._scene_summary()
    node_count = len(((tools.scene or {}).get("nodes")) or {})
    digest: JsonObject = {"scene": summary}
    if node_count == 0:
        digest["note"] = (
            "The scene has no nodes yet — this is a CREATE turn. You author the "
            "page and everything on it."
        )
        return digest
    if node_count > MAX_DIGEST_NODES:
        digest["note"] = (
            f"{node_count} nodes exceeds the {MAX_DIGEST_NODES}-node digest cap, so the "
            "per-page node trees are omitted here. Use inspect(view='page', "
            "target=<page_id>) for the subtree you are about to touch — the summary "
            "above is complete, only the tree detail is elided."
        )
        return digest
    pages = (tools.scene or {}).get("pages") or {}
    digest["node_trees"] = {
        page_id: tools._node_tree(page.get("children") or [])
        for page_id, page in pages.items()
    }
    return digest


# ---------------------------------------------------------------------------
# The asset index
# ---------------------------------------------------------------------------


def build_asset_index(tools: Any) -> tuple[list[JsonObject], int]:
    """Every placeable kit asset, with the handle that shows its pixels.

    Returns ``(rows, omitted_count)`` — the same no-silent-caps shape
    ``LumenDesignTools._brand_asset_contact_sheet`` uses.

    P0.1 fixed `view("asset:<id>")` (it returned `asset_missing_file` for every
    durable-storage record), so this index is finally worth handing over: the
    author can LOOK at each candidate instead of choosing blind from metadata
    and being rejected for it a round later.
    """
    card = tools.brand_card or {}
    manifest = (tools.config.brand_kit_assets or {}) if tools.config else {}
    rows: list[JsonObject] = []

    for logo in card.get("logos") or []:
        for variant in logo.get("variants") or []:
            asset_id = variant.get("asset_id")
            if not asset_id:
                continue
            rows.append(
                {
                    "asset_id": asset_id,
                    "kind": "logo",
                    "name": f"{logo.get('logo')} / {variant.get('name') or 'variant'}",
                    "notes": " · ".join(
                        str(part)
                        for part in (
                            variant.get("color_mode"),
                            (
                                "backgrounds: "
                                + ", ".join(logo.get("allowed_backgrounds") or [])
                            )
                            if logo.get("allowed_backgrounds")
                            else None,
                            logo.get("usage_note"),
                        )
                        if part
                    ),
                }
            )

    for image in card.get("images") or []:
        asset_id = image.get("asset_id")
        if not asset_id:
            continue
        rows.append(
            {
                "asset_id": asset_id,
                "kind": "image",
                "name": image.get("title") or image.get("asset") or asset_id,
                "notes": " · ".join(
                    str(part)
                    for part in (
                        image.get("role"),
                        image.get("description"),
                        image.get("usage_note"),
                        ", ".join(image.get("style_tags") or []) or None,
                    )
                    if part
                ),
            }
        )

    # Anything in the by-value manifest the card did not surface (a kit whose
    # card inventory is capped, or an asset with no card entry) still belongs in
    # the index — the manifest is what `use_brand_asset` actually places.
    seen = {row["asset_id"] for row in rows}
    for asset_id, entry in manifest.items():
        if asset_id in seen:
            continue
        record = (entry or {}).get("record") or {}
        rows.append(
            {
                "asset_id": asset_id,
                "kind": record.get("kind") or "asset",
                "name": (entry or {}).get("title") or record.get("label") or asset_id,
                "notes": (entry or {}).get("usage") or "",
            }
        )
    return rows[:MAX_ASSET_ROWS], max(0, len(rows) - MAX_ASSET_ROWS)


def _render_asset_index(rows: list[JsonObject], omitted: int) -> str:
    if not rows:
        return (
            "This kit places no assets (no logo variants, no brand images). Do not "
            "invent an asset id — compose with type, shape and token color."
        )
    lines = [
        'Every row is placeable NOW, and `view("asset:<asset_id>")` returns its real '
        "pixels. LOOK before you place: reject crops with baked-in text, check a "
        "mark's shape against the frame you are putting it in.",
        "",
        "| asset_id | kind | name | notes |",
        "|---|---|---|---|",
    ]
    for row in rows:
        notes = str(row.get("notes") or "—").replace("|", "\\|").replace("\n", " ")
        name = str(row.get("name") or "—").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {row['asset_id']} | {row.get('kind')} | {name} | {notes} |")
    if omitted:
        lines.append("")
        lines.append(
            f"({omitted} further asset(s) exist beyond this index's {MAX_ASSET_ROWS}-row "
            "cap — ask the asset tool for the full manifest if none of the above fits.)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pinned knowledge
# ---------------------------------------------------------------------------


def pinned_knowledge_paths(config: Any) -> tuple[str, ...]:
    """The configured pin list, or :data:`DEFAULT_PINNED_KNOWLEDGE`."""
    raw = getattr(config, "fast_loop_pinned_knowledge", None)
    descriptor = _materialized_scene_view(config)
    if descriptor and not raw:
        return tuple(descriptor["pinned_knowledge"])
    if not raw:
        return DEFAULT_PINNED_KNOWLEDGE
    entries = tuple(part.strip() for part in str(raw).split(",") if part.strip())
    return entries or DEFAULT_PINNED_KNOWLEDGE


def _materialized_scene_view(config: Any) -> dict | None:
    """Inspect delivered view identity; a web turn can carry the scene flag too."""
    workspace = getattr(config, "workspace_root", None)
    if workspace is None:
        return None
    path = Path(workspace) / ".deepagent/knowledge-view.json"
    if not path.is_file():
        return None
    descriptor = json.loads(path.read_text(encoding="utf-8"))
    return descriptor if descriptor.get("view") == "scene" else None


def _knowledge_root() -> Path:
    """The authored knowledge tree — the same anchor `materialize.py` uses.

    Resolved relative to THIS file rather than through ``config.repo_root``, for
    the reason materialize states: ``repo_root`` is a bare temp dir in tests.
    """
    return Path(__file__).resolve().parent.parent / "knowledge_docs"


def build_pinned_knowledge(config: Any) -> list[tuple[str, str]]:
    """``[(virtual_path, text)]`` for each pinned file that exists.

    A missing pin is logged and SKIPPED, never fatal: a bad entry in an env
    override must not take a design turn down, and the author still has the
    read-only knowledge tree at ``/knowledge_docs/`` for anything not pinned.
    """
    scene_view = _materialized_scene_view(config)
    root = Path(config.workspace_root) / "knowledge_docs" if scene_view else _knowledge_root()
    pinned: list[tuple[str, str]] = []
    for relative in pinned_knowledge_paths(config):
        if scene_view and (
            Path(relative).is_absolute() or ".." in Path(relative).parts
            or relative not in scene_view["knowledge"]
        ):
            raise RuntimeError(f"Pin is outside the selected scene view: {relative}")
        source = root / relative
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as error:
            logger.warning(
                "frame_pin_unreadable", path=str(source), error=f"{type(error).__name__}"
            )
            continue
        if len(text) > MAX_PINNED_CHARS:
            text = (
                text[:MAX_PINNED_CHARS]
                + f"\n\n[... truncated at {MAX_PINNED_CHARS} chars — read "
                f"/knowledge_docs/{relative} for the rest ...]\n"
            )
        pinned.append((f"/knowledge_docs/{relative}", text))
    return pinned


# ---------------------------------------------------------------------------
# The payload
# ---------------------------------------------------------------------------

_HEADER = """COMPOSED FRAME PAYLOAD (fast loop §5.1) — everything below is ALREADY RESOLVED
for this turn. It was composed for you, not left on disk for you to find.

THE RULE THIS REPLACES: do not `ls`, `glob` or `grep` for context. The brand
card, the resolved type ramp, the live scene, the placeable asset index and the
knowledge files this work needs are all inline below. Your round's direction
arrives inline in the delegation that woke you. Reading one NAMED file (a
previous round's critique.json, a skill you were told to use) is fine; hunting
the filesystem for something in this payload is a wasted call and a wasted
minute."""


def render_ad_dna_card_text(card: JsonObject) -> str:
    """The ad-DNA card as the author reads it: a labelled paragraph, not a schema dump.

    Brand Ad Assets W4. Labelled ADVISORY in the words themselves. The brand card next to it
    carries rules the run must honour — tokens, logo policy, type roles; this one carries an
    OBSERVATION about ads the brand already published, and if that difference is not visible in
    the text the author will read a description as a specification.

    The card is free prose by ruling (2026-08-26), so this renders the prose as prose. No group
    names are shown (founder ruling 2026-10-30), even from an older card that still holds them.
    """
    lines = [
        "This is how the ads this brand has already published look, described from the "
        "creatives themselves.",
        "",
        "It is context, not a rule. Nothing here overrides the brand card, the format skill "
        "in force, or what the person actually asked for. Where the description and the brand "
        "card disagree, the brand card wins.",
        "",
        str(card.get("prose") or "").strip(),
    ]
    return "\n".join(lines)


def render_pregenerated_assets_text(
    assets: list[Any], library: JsonObject | None = None
) -> str:
    """The lane's pre-generated grounds, named so the author knows they exist.

    W5/R2-D. These images were generated at onboarding from the very description above, and
    every one of them was already viewable and placeable by id. What was missing was any
    sentence anywhere that said so: the asset index next to this block lists the brand KIT's
    assets, and the library's ids appeared only inside `view`'s honest-miss text — which the
    author reaches only by guessing an id wrong first. So a whole turn ran, made its own
    ground, and never learned that twelve were waiting.

    ``library`` is this turn's asset-library manifest. When it is present, only ids actually in
    it are listed — advertising an id the author would then fail to open would be a worse
    failure than the silence it replaces, and the manifest is what `view` and placement resolve
    against. An empty result renders nothing at all, so the honest cases stay quiet.

    Advisory in the words themselves, like its neighbour. There is no gate here and nothing
    counts how many get used; a ground that does not suit the brief should be ignored.
    """
    rows = []
    for entry in assets or ():
        if not isinstance(entry, dict):
            continue
        asset_id = str(entry.get("asset_id") or "").strip()
        if not asset_id:
            continue
        if library is not None and asset_id not in library:
            continue
        described = str(entry.get("shape") or "").strip()
        rows.append(f"- `{asset_id}`" + (f" — {described}" if described else ""))
    if not rows:
        return ""

    lines = [
        "These background images were made for this brand ahead of time, from the description "
        "above.",
        "",
        "You can look at any of them with `view(\"asset:<id>\")` and place one the same way you "
        "place any library asset.",
        "",
        "Using one is optional. Pick one only if it suits the brief. Making your own ground "
        "instead is fine, and so is using no image at all.",
        "",
        *rows,
    ]
    return "\n".join(lines)


def short_description(text: str | None, limit: int = 300) -> str:
    """The first two sentences of an asset's description, capped at ``limit``; ``""`` for none."""
    words = " ".join(str(text or "").split())
    if not words:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", words)
    return " ".join(sentences[:2])[:limit]


def _cell(value: Any, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    if limit is not None:
        text = text[:limit]
    return text.replace("|", "\\|") or "—"


#: Founder-approved wording (2026-10-30, reference ads spec §5.6). ``{count}`` = rows listed.
BRAND_ADS_HEADING = (
    "## The brand's ads\n"
    "These are the brand's own published ads and any images the team marked as ads — {count} in all.\n"
    "Open any of them with `view(\"asset:<id>\")` to see the picture and its full description\n"
    "(layout, text, typography, hierarchy). Look through several before you design, and pick\n"
    "ones that fit this request; you don't need to use the same ones as last time.\n"
)

_BRAND_AD_SOURCES = {"linkedin_ad": "LinkedIn ad", "marked_by_person": "marked as an ad"}


def render_brand_ads_text(ads: list[Any], library: JsonObject | None) -> str:
    """Every ad of the brand this turn can open, as a table under the approved heading.

    Spec 2026-10-30 (reference ads §5.5). Only ids in this turn's library are listed — the same
    rule as the backgrounds below, because the library is what ``view`` resolves against. An
    empty result renders nothing at all.
    """
    rows = []
    for ad in ads or ():
        if not isinstance(ad, dict):
            continue
        asset_id = str(ad.get("asset_id") or "").strip()
        if not asset_id or library is None or asset_id not in library:
            continue
        width, height = ad.get("width"), ad.get("height")
        cells = [
            f"`{asset_id}`",
            _BRAND_AD_SOURCES.get(str(ad.get("from")), "—"),
            _cell(ad.get("headline")),
            _cell(ad.get("commentary"), 200),
            _cell(ad.get("title")),
            _cell(short_description(ad.get("description")) or "no description yet"),
            f"{width}×{height}" if width and height else "—",
        ]
        rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    return (
        BRAND_ADS_HEADING.format(count=len(rows))
        + "\n| asset id | from | headline | post copy | title | short description | size |\n"
        + "|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


def build_frame_payload(tools: Any) -> str:
    """The whole §5.1 block, appended to the flag-on author system prompt."""
    scene_candidate = getattr(tools.config, "scene_skill_bundle", "legacy") == "candidate"
    sections: list[str] = [
        "COMPOSED FRAME PAYLOAD — the brand card, authored type context, initial "
        "scene, placeable asset index and selected mechanics below are already "
        "resolved for this turn. Reuse them instead of hunting for duplicates. "
        "The validated direction is creative-direction.json in the run workspace. "
        "Read other relevant skills and source_assets.json when they answer a "
        "specific unresolved choice; the inline payload is not the full source "
        "catalog or a limit on later discovery. Inspect current state after mutations."
        if scene_candidate else _HEADER
    ]

    card = tools.brand_card
    if card:
        sections.append("## BRAND CARD\n\n" + render_brand_card_text(card))
    else:
        sections.append(
            "## BRAND CARD\n\nThis run has NO attached brand kit. Use raw values "
            "(`font(...)`, hex fills) — token references would be undefined here."
        )

    # W4: the brand's published-ad styles, described. Absent unless the ad-assets lane is on
    # AND populated AND distilled, so a turn without one is byte-identical to a pre-W4 turn.
    ad_card = (tools.config.ad_dna_card if tools.config else None) or None
    if ad_card:
        sections.append(
            "## THE BRAND'S PUBLISHED-AD STYLES, DESCRIBED (advisory)\n\n"
            + render_ad_dna_card_text(ad_card)
        )
    # W5/R2-D: and the grounds that were pre-generated FROM that description. Same block, same
    # advisory posture, same absence rule — no lane, no imagery, or nothing reachable in this
    # turn's library and the section is not composed at all.
    pregenerated = (tools.config.ad_pregenerated_assets if tools.config else None) or None
    if pregenerated:
        rendered = render_pregenerated_assets_text(
            pregenerated, tools.config.asset_library if tools.config else None
        )
        if rendered:
            sections.append(
                "## BACKGROUNDS ALREADY MADE FOR THIS BRAND (advisory)\n\n" + rendered
            )

    page_id = next(iter((tools.scene or {}).get("pages") or {}), None)
    width, height = tools._page_dimensions(page_id)
    if scene_candidate:
        sections.append(
            "## TYPE MEASUREMENT\n\n"
            "The brand card above carries authored type families, weights and sizes. "
            "Those sizes are source context, not canvas-derived legibility floors. "
            "Choose hierarchy from the inspected reference and actual copy; measure "
            "line breaks and visible readability at the intended placement size. "
            "Use knowledge/scene/components.md and knowledge/scene/placement.md."
        )
    else:
        ramp = resolve_type_ramp(card, width=width, height=height)
        sections.append("## TYPE RAMP — resolved for this canvas\n\n" + _render_type_ramp(ramp))

    digest = build_scene_digest(tools)
    sections.append(
        "## SCENE DIGEST (live, as of this turn's start)\n\n```json\n"
        + json.dumps(digest, indent=2)
        + "\n```"
    )

    rows, omitted = build_asset_index(tools)
    sections.append("## ASSET INDEX\n\n" + _render_asset_index(rows, omitted))

    pinned = build_pinned_knowledge(tools.config)
    if pinned:
        blocks = [
            "## PINNED KNOWLEDGE (inlined — do not go read these again)",
            "",
            "Pinned for this turn: " + ", ".join(path for path, _ in pinned) + ".",
        ]
        for path, text in pinned:
            blocks.append(f"\n### {path}\n\n{text}")
        sections.append("\n".join(blocks))

    return "\n\n".join(sections)
