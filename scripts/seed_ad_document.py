"""AD2.2 — seed the realistic ad scene document every later AD task is TDD'd against.

Why this exists
---------------
Phase AD2/AD3/AD4 adapters (`scene-hydrate`, `scene-writes`, the canvas) are proven
against REAL harvested scene bytes, never hand-written shapes (the W2.2 law inherited
from the website-editor lane). That needs a document in the dev DB whose tree exercises
every contract schema at once — Frame / AutoLayout / Text / Image / Rect / Ellipse /
Group / Line — and that looks like a plausible LinkedIn ad rather than a test grid, so
AD2.3 can hold the platform canvas and the standalone editor side by side and compare.

This is the productionized sibling of the AD0.5 exit-audit scratch seeder
(`.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/seed_ad0_audit_doc.py`),
which planted an EMPTY scene. Two deliberate differences:

* **The engine validates the scene, not this script.** The document is created through
  the design API's ``POST /documents``, whose scene path runs ``core.validate_scene``
  (the Rust contract validator) and stores the value the ENGINE returns. So the bytes
  that land in `design_document.current_scene_json` — and therefore the bytes AD2.2
  harvests into the fixture file — are engine-normalized, not this file's literals.
  A hand-authored blob inserted straight into Postgres would look like a harvest while
  actually being a hand-written shape.
* **The leg rows are still direct SQL.** The design API has no route that mints an
  `agent_thread` / `execution` / `design_leg`, and `open_design_leg` refuses
  ``doc_kind="scene"`` outright (v1 keeps the ad flow editor-first —
  `design_leg_scene_creation_unsupported`). So the leg arrangement is copied from the
  AD0.5 seeder, deterministic ids and all.

  **[SUPERSEDED 2026-08-23 — genad ruling 1 REVERSES the refusal: `open_design_leg@3`
  now births scene documents itself, at a ratified format and brand-stamped, so a
  chat-born ad no longer needs a seeder at all. Plan:
  `docs/superpowers/plans/2026-08-23-chat-driven-ad-creation.md`. THIS SCRIPT STAYS
  VALID — a birth mints a single ratified-format page, while this seeder plants the
  richer harvested tree (Frame / AutoLayout / Text / Image / Rect / Ellipse / Group /
  Line) that the AD2–AD4 adapters are TDD'd against. Only the reason the leg rows are
  hand-written has changed: it is now the missing `agent_thread`/`execution` mint, not
  a scene-creation refusal.]**

Every id below is deterministic, so a re-run reports the existing rows instead of
minting a second document/leg. ``--recreate`` tears the seeded rows down first.

Setup
-----
* The design API must be running (``uvicorn lumen_api.main:app --port 8010``), pointed
  at the same Postgres as ``CLUE_DATABASE_URL``.
* Env (pass inline; do NOT create a repo-root `.env` — that breaks the test suites):

      set -a; source ../istanbul/.env; set +a; \
        .venv/bin/python scripts/seed_ad_document.py

  ``CLUE_DATABASE_URL``  — required, the platform DB (asyncpg URL).
  ``CLUE_DESIGN_API_URL`` — optional, defaults to http://127.0.0.1:8010.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# --- the dev-DB anchors (same workspace/project as the AD0.5 seeder) ----------
WORKSPACE_ID = "ws_8040294627e146ae93f753ec0d3e1726"  # "Insight Health"
PROJECT_ID = "prj_79aa603b3c3853898045e3cfa414e136"  # "Untitled project"
DOCUMENT_ID = "doc_ad22linkedinsquare00000000001"
THREAD_ID = "thr_ad22_linkedin_square"
TITLE = "Insight Health — LinkedIn square ad"
EXECUTION_ID = uuid.uuid5(uuid.NAMESPACE_URL, "ad2.2-linkedin-square-execution")
LEG_ID = uuid.uuid5(uuid.NAMESPACE_URL, "ad2.2-linkedin-square-leg")
_ZERO_SHA = "0" * 64

# The workspace's latest APPROVED brand kit. Attaching it is what makes the headline's
# token fill (`$text.inverse`) resolve to a real colour on the canvas instead of falling
# through to the renderer's 4-bucket string heuristic.
BRAND_KIT_ID = "brand_kit_ing_813df4f30f2d429a853dbccae2277a5a"  # "Stripe"
BRAND_KIT_VERSION = 6

# A REAL raster asset already in this workspace's asset store, bytes and all
# (860x712 image/jpeg, digest below serves 200 from GET /asset-store/{digest}).
# The Image node points at it so AD2.3's passthrough proof has real bytes to load.
ASSET_ID = "asset_ing_2b0928ca4f3a3c70"
ASSET_DIGEST = "2b0928ca4f3a3c70c5c2fed22996f0428da219c953a14e71567b73c1d8af937a"

PAGE_ID = "page_linkedin_square"
# 1200x1200 — the ad-inspector contract's CORRECTED LinkedIn-square preset (§1.1). The
# engine's own `PagePreset::LinkedinAd` is the 1200x627 banner, so the honest preset
# value here is `custom`; the inspector's preset select matches on SIZE, not on this
# field, which is exactly the exact-match case AD2.4 needs.
PAGE_WIDTH = 1200.0
PAGE_HEIGHT = 1200.0

ROOT_FRAME = "frame_ad_root"
COPY_ROW = "auto_row_copy"
HEADLINE = "text_headline"
STAT_GROUP = "group_proof"
STAT_DOT = "ellipse_proof_dot"
STAT_TEXT = "text_proof_stat"
ACCENT_BAR = "rect_accent_bar"
DIVIDER = "line_divider"
HERO_IMAGE = "image_hero"

# Brand colours read off the attached kit (tokens.colors): surface.brand #533AFD,
# surface.accent #EA2261, text.inverse #FFFFFF.
INK = "#0E0B2E"
CARD = "#171043"
CARD_EDGE = "#2E2470"
BRAND = "#533AFD"
BRAND_MID = "#8B5CF6"
ACCENT = "#EA2261"
STAT_INK = "#C7C2F5"


def _transform(x: float, y: float) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "rotation": 0.0,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "flip_x": False,
        "flip_y": False,
    }


def _fixed(value: float) -> dict[str, Any]:
    return {"kind": "fixed", "value": value}


_HUG: dict[str, Any] = {"kind": "hug"}


def _fill_dim(weight: float) -> dict[str, Any]:
    return {"kind": "fill", "value": {"weight": weight}}


def _corner(
    top_left: float, top_right: float, bottom_right: float, bottom_left: float
) -> dict[str, Any]:
    # NOTE the order: the engine's CornerRadii is TL, TR, BR, BL.
    return {
        "top_left": top_left,
        "top_right": top_right,
        "bottom_right": bottom_right,
        "bottom_left": bottom_left,
        "token": None,
    }


def _solid(paint_id: str, hex_value: str) -> dict[str, Any]:
    return {
        "id": paint_id,
        "paint": {"kind": "solid", "color": {"kind": "hex", "value": hex_value}},
    }


def _node(
    node_id: str,
    *,
    name: str,
    kind: dict[str, Any],
    transform: dict[str, Any],
    size: dict[str, Any],
    children: list[str] | None = None,
    fills: list[dict[str, Any]] | None = None,
    strokes: list[dict[str, Any]] | None = None,
    corner: dict[str, Any] | None = None,
    opacity: float = 1.0,
    clip: bool = False,
    layout: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": node_id,
        "name": name,
        "kind": kind,
        "transform": transform,
        "size": size,
        "children": children or [],
        "fills": fills or [],
        "strokes": strokes or [],
        "corner": corner or _corner(0.0, 0.0, 0.0, 0.0),
        "opacity": opacity,
        "clip": clip,
        "layout": layout,
        "computed": None,
        "locked": False,
    }
    node.update(extra)
    return node


def ad_scene(document_id: str, title: str, asset_record: dict[str, Any]) -> dict[str, Any]:
    """The seeded ad: a 1200x1200 dark artboard, copy card over a rounded hero photo.

    Composition (top to bottom): a padded auto-layout copy row carrying the headline and
    a two-child proof-point group, a short gradient accent bar, a hairline divider, and a
    full-width rounded hero image. One node per contract schema, arranged the way an ad
    actually is — the tree has to survive a side-by-side with the standalone editor.

    ``asset_record`` is the workspace's REAL ``design_asset.record_json``, read from the
    DB rather than transcribed here, and it must live in ``scene.assets``: both the
    server renderer and the editor's image cache resolve pixels through
    ``scene.assets[asset_id].media.digest``, so an Image node whose asset is missing from
    the map renders as nothing at all (that is exactly what the first seeded revision did).
    """
    nodes = {
        ROOT_FRAME: _node(
            ROOT_FRAME,
            name="Ad artboard",
            kind={"kind": "frame"},
            transform=_transform(0.0, 0.0),
            size={"width": _fixed(PAGE_WIDTH), "height": _fixed(PAGE_HEIGHT)},
            children=[COPY_ROW, ACCENT_BAR, DIVIDER, HERO_IMAGE],
            fills=[_solid("paint_root_ink", INK)],
            clip=True,
        ),
        COPY_ROW: _node(
            COPY_ROW,
            name="Copy row",
            kind={"kind": "auto_layout", "direction": "row", "wrap": False},
            transform=_transform(72.0, 72.0),
            size={"width": _fixed(1056.0), "height": _HUG},
            children=[HEADLINE, STAT_GROUP],
            fills=[_solid("paint_card", CARD)],
            strokes=[{"id": "stroke_card", "paint": _solid("_", CARD_EDGE)["paint"], "width": 2.0}],
            corner=_corner(32.0, 32.0, 32.0, 96.0),
            layout={
                "gap": 32.0,
                "padding": [40.0, 44.0, 40.0, 44.0],
                "grow": 0.0,
                "align_x": "start",
                "align_y": "center",
            },
        ),
        # The token-bound text: its fill is a brand token, resolved from the attached kit.
        HEADLINE: _node(
            HEADLINE,
            name="Headline",
            kind={
                "kind": "text",
                "content": "Every inbound fax, routed to the right EHR queue.",
                "font_family": "Inter",
                "font_size": 54.0,
                "font_weight": 700,
                "align": "left",
                "line_height": 1.1,
                "letter_spacing": -0.5,
                "wrap": "wrap",
                "direction": "ltr",
                "valign": "center",
            },
            transform=_transform(0.0, 0.0),
            size={"width": _fixed(632.0), "height": _HUG},
            fills=[{"id": "paint_headline", "paint": {"kind": "token", "token": "$text.inverse"}}],
        ),
        STAT_GROUP: _node(
            STAT_GROUP,
            name="Proof point",
            kind={"kind": "group"},
            transform=_transform(0.0, 0.0),
            size={"width": _fill_dim(1.0), "height": _fixed(104.0)},
            children=[STAT_DOT, STAT_TEXT],
        ),
        STAT_DOT: _node(
            STAT_DOT,
            name="Accent dot",
            kind={"kind": "ellipse"},
            transform=_transform(0.0, 40.0),
            size={"width": _fixed(24.0), "height": _fixed(24.0)},
            fills=[_solid("paint_dot", ACCENT)],
        ),
        # The explicitly-styled text: family/size/weight literal, no token anywhere, and a
        # non-unit opacity so the inspector's 0-1 -> percent mapping has real bytes.
        STAT_TEXT: _node(
            STAT_TEXT,
            name="Proof stat",
            kind={
                "kind": "text",
                "content": "3.4x faster triage",
                "font_family": "Inter",
                "font_size": 26.0,
                "font_weight": 600,
                "align": "left",
                "line_height": 1.35,
                "letter_spacing": 0.0,
                "wrap": "wrap",
                "direction": "ltr",
            },
            transform=_transform(44.0, 24.0),
            size={"width": _fixed(256.0), "height": _HUG},
            fills=[_solid("paint_stat", STAT_INK)],
            opacity=0.8,
        ),
        ACCENT_BAR: _node(
            ACCENT_BAR,
            name="Accent bar",
            kind={"kind": "rect"},
            transform=_transform(72.0, 368.0),
            size={"width": _fixed(320.0), "height": _fixed(10.0)},
            fills=[
                {
                    "id": "paint_accent_bar",
                    "paint": {
                        "kind": "linear_gradient",
                        "angle": 90.0,
                        "stops": [
                            {"color": {"kind": "hex", "value": BRAND}, "position": 0.0},
                            {"color": {"kind": "hex", "value": BRAND_MID}, "position": 0.5},
                            {"color": {"kind": "hex", "value": ACCENT}, "position": 1.0},
                        ],
                    },
                }
            ],
            corner=_corner(5.0, 5.0, 5.0, 5.0),
        ),
        DIVIDER: _node(
            DIVIDER,
            name="Divider",
            kind={"kind": "line", "x2": 1056.0, "y2": 0.0},
            transform=_transform(72.0, 412.0),
            size={"width": _fixed(1056.0), "height": _fixed(2.0)},
            strokes=[
                {"id": "stroke_divider", "paint": _solid("_", CARD_EDGE)["paint"], "width": 2.0}
            ],
        ),
        HERO_IMAGE: _node(
            HERO_IMAGE,
            name="Hero image",
            kind={
                "kind": "image",
                "asset_id": ASSET_ID,
                "alt": "Brand gradient backdrop",
            },
            transform=_transform(72.0, 452.0),
            size={"width": _fixed(1056.0), "height": _fixed(676.0)},
            corner=_corner(32.0, 32.0, 32.0, 96.0),
            clip=True,
            source_asset_id=ASSET_ID,
            asset_placement={
                "fit": "cover",
                "focal_point": {"x": 0.5, "y": 0.42},
                "preserve_transparency": False,
                "alt_text": "Brand gradient backdrop",
            },
        ),
    }
    return {
        "schema_version": 1,
        "meta": {
            "id": document_id,
            "title": title,
            "artifact_type": "linkedin_square_ad",
            "medium": "ad",
            "brand_kit": {"id": BRAND_KIT_ID, "version": BRAND_KIT_VERSION},
            "status": {"kind": "draft"},
        },
        "pages": {
            PAGE_ID: {
                "id": PAGE_ID,
                "name": "LinkedIn square",
                "size": {
                    "width": PAGE_WIDTH,
                    "height": PAGE_HEIGHT,
                    "unit": "pt",
                    "preset": "custom",
                    "orientation": "portrait",
                    "source": {"width": PAGE_WIDTH, "height": PAGE_HEIGHT, "unit": "px"},
                    "output": {"raster": {"width_px": 1200, "height_px": 1200}},
                },
                "children": [ROOT_FRAME],
                "bleed": None,
                "safe_area": {"x": 64.0, "y": 64.0, "width": 1072.0, "height": 1072.0},
                "background": [],
            }
        },
        "nodes": nodes,
        "slots": {},
        "assets": {ASSET_ID: asset_record},
        "export_profiles": [
            {
                "name": "linkedin-square",
                "format": "png",
                "pdf_intent": None,
                "raster": {"scale": 1.0, "dpi": None},
                "include_bleed": False,
                "embed_fonts": False,
            }
        ],
    }


# --- the design API seam -----------------------------------------------------


def design_api_url() -> str:
    return os.environ.get("CLUE_DESIGN_API_URL", "http://127.0.0.1:8010").rstrip("/")


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{design_api_url()}{path}",
        data=payload,
        method=method,
        headers={
            "X-Workspace-Id": WORKSPACE_ID,
            **({"content-type": "application/json"} if payload else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:  # surface the engine's diagnostics verbatim
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"{method} {path} failed (HTTP {error.code}):\n{detail}") from error
    except urllib.error.URLError as error:
        raise SystemExit(
            f"{method} {path} could not reach the design API at {design_api_url()} "
            f"({error.reason}). Start it first: "
            "uvicorn lumen_api.main:app --host 127.0.0.1 --port 8010"
        ) from error


def create_scene_document(asset_record: dict[str, Any]) -> dict[str, Any]:
    """POST the scene so the ENGINE validates and normalizes what gets stored."""
    return _request(
        "POST",
        "/documents",
        {
            "document_id": DOCUMENT_ID,
            "title": TITLE,
            "doc_kind": "scene",
            "scene": ad_scene(DOCUMENT_ID, TITLE, asset_record),
        },
    )


def fetch_document(document_id: str) -> dict[str, Any]:
    return _request("GET", f"/documents/{document_id}")


def preflight_preview(scene: dict[str, Any]) -> dict[str, Any]:
    """Structural + brand + layout check of the STORED scene, without persisting it.

    Deliberately NOT ``POST /documents/{id}/preflight``: that route persists its token
    and layout operations, which would resolve the headline's `$text.inverse` fill into
    a literal hex and bump the version — i.e. the verification would destroy the very
    token fixture it was verifying. ``/preflight-preview`` runs the same
    ``core.preflight_scene`` and returns diagnostics, touching nothing.
    """
    return _request("POST", "/preflight-preview", {"scene": scene})


# --- the leg arrangement (direct SQL — no API route mints these) --------------


async def seed_leg(conn: Any) -> None:
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, title)"
            " VALUES (:id, :w, :p, :title) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": THREAD_ID, "w": WORKSPACE_ID, "p": PROJECT_ID, "title": "LinkedIn square ad"},
    )
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by,"
            " parameter_manifest_hash, pin_manifest_hash)"
            " VALUES (:id, :w, :p, 'human', :sha, :sha) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": EXECUTION_ID, "w": WORKSPACE_ID, "p": PROJECT_ID, "sha": _ZERO_SHA},
    )
    await conn.execute(
        text(
            "INSERT INTO design_leg (id, workspace_id, thread_id, parent_execution_id,"
            " state, document_id)"
            " VALUES (:id, :w, :t, :x, 'open_awaiting_user', :d) ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": LEG_ID,
            "w": WORKSPACE_ID,
            "t": THREAD_ID,
            "x": EXECUTION_ID,
            "d": DOCUMENT_ID,
        },
    )


async def teardown(conn: Any) -> None:
    await conn.execute(text("DELETE FROM design_leg WHERE id = :id"), {"id": LEG_ID})
    await conn.execute(
        text("DELETE FROM design_document WHERE id = :d AND workspace_id = :w"),
        {"d": DOCUMENT_ID, "w": WORKSPACE_ID},
    )


async def read_asset_record(conn: Any) -> dict[str, Any]:
    """The REAL AssetRecord for the hero image, straight off the workspace's asset row."""
    row = (
        await conn.execute(
            text(
                "SELECT record_json, digest_value FROM design_asset"
                " WHERE asset_id = :a AND workspace_id = :w"
            ),
            {"a": ASSET_ID, "w": WORKSPACE_ID},
        )
    ).first()
    if row is None:
        raise SystemExit(
            f"asset {ASSET_ID} is not in workspace {WORKSPACE_ID} — the hero image would "
            "have no bytes. Pick another ready raster asset from design_asset and update "
            "ASSET_ID/ASSET_DIGEST."
        )
    if row.digest_value != ASSET_DIGEST:
        raise SystemExit(
            f"asset {ASSET_ID} digest drifted ({row.digest_value} != {ASSET_DIGEST}); "
            "update ASSET_DIGEST so the harvest provenance stays honest"
        )
    record = row.record_json
    return json.loads(record) if isinstance(record, (str, bytes)) else record


async def document_exists(conn: Any) -> bool:
    row = (
        await conn.execute(
            text("SELECT 1 FROM design_document WHERE id = :d AND workspace_id = :w"),
            {"d": DOCUMENT_ID, "w": WORKSPACE_ID},
        )
    ).first()
    return row is not None


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="delete the seeded document + leg first (the scene changed and you want it re-made)",
    )
    args = parser.parse_args()

    url = os.environ.get("CLUE_DATABASE_URL")
    if not url:
        raise SystemExit(
            "CLUE_DATABASE_URL is unset. Pass it inline — never write a repo-root .env:\n"
            "  set -a; source ../istanbul/.env; set +a; "
            ".venv/bin/python scripts/seed_ad_document.py"
        )
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            if args.recreate:
                await teardown(conn)
            already = await document_exists(conn)
            asset_record = await read_asset_record(conn)

        if already:
            print(f"document {DOCUMENT_ID} already exists — leaving it alone (--recreate to redo)")
        else:
            created = create_scene_document(asset_record)
            document = created["document"]
            print(f"created document {document['id']} v{document.get('current_version')}")

        report = preflight_preview(fetch_document(DOCUMENT_ID)["scene"])
        # `diagnostics` is the three-view DTO (audit / current / latest); `audit` is the
        # full run.
        audit = report.get("diagnostics", {}).get("audit", [])
        errors = [d for d in audit if d.get("severity") == "error"]
        warnings = [d for d in audit if d.get("severity") == "warning"]
        print(f"preflight-preview: {len(errors)} error(s), {len(warnings)} warning(s)")
        for diagnostic in errors + warnings:
            print(f"  [{diagnostic['severity']}] {diagnostic['code']}: {diagnostic['message']}")
        if errors:
            raise SystemExit("preflight reported errors — the seeded scene is not valid")

        async with engine.begin() as conn:
            await seed_leg(conn)

        async with engine.connect() as conn:
            document = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, doc_kind, title, status, current_version,"
                            " effective_brand_kit_id, effective_brand_kit_version"
                            " FROM design_document WHERE id = :d AND workspace_id = :w"
                        ),
                        {"d": DOCUMENT_ID, "w": WORKSPACE_ID},
                    )
                )
                .mappings()
                .one()
            )
            leg = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, thread_id, document_id, state"
                            " FROM design_leg WHERE id = :id"
                        ),
                        {"id": LEG_ID},
                    )
                )
                .mappings()
                .one()
            )

        print("document:", dict(document))
        print("leg:     ", dict(leg))
        print(f"workspace:      {WORKSPACE_ID}")
        print(f"artifact route: /projects/{PROJECT_ID}/artifacts/{DOCUMENT_ID}")
        print(f"chats route:    /projects/{PROJECT_ID}/chats/{THREAD_ID}")
        print(
            f"harvest:        curl -s -H 'X-Workspace-Id: {WORKSPACE_ID}' "
            f"{design_api_url()}/documents/{DOCUMENT_ID}"
        )
        print(f"asset bytes:    {design_api_url()}/asset-store/{ASSET_DIGEST}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
