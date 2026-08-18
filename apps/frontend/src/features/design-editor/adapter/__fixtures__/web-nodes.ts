/**
 * W2.2 fixtures: REAL WebNode JSON snapshots harvested from a seeded web
 * document, exactly as `GET /documents/{id}` serves them under the `scene`
 * key — NOT hand-written shapes. Harvest provenance: document
 * `doc_31126145a0aa4753920629ae323a301b` (workspace "Insight Health" dev DB),
 * version 2, captured 2026-08-18 via the design API. One node per inspector
 * schema: text (headline/sub), button (cta), image (fimg), icon (ficon),
 * container (fgrid + the page root), section (hero/features), embed (fembed).
 */
import type { WebNode } from "../../engine/webDocuments";

export const HARVESTED_PAGE: { page_root: string; nodes: Record<string, WebNode> } =
{
  "page_root": "root",
  "nodes": {
    "cta": {
      "id": "cta",
      "href": "#",
      "kind": "button",
      "name": "CTA",
      "label": "Book a demo",
      "classes": "rounded-full bg-white text-slate-900 px-6 py-3 font-semibold",
      "new_tab": false,
      "variant": "primary"
    },
    "sub": {
      "id": "sub",
      "kind": "text",
      "name": "Subheadline",
      "classes": "text-lg text-slate-300 text-center max-w-xl",
      "content": {
        "blocks": [
          {
            "type": "paragraph",
            "children": [
              {
                "text": "AI fax, referral, and document-processing agents that route inbound work into the right EHR queue.",
                "type": "text"
              }
            ]
          }
        ],
        "schema_version": 1
      },
      "variant": "body"
    },
    "fimg": {
      "id": "fimg",
      "alt": "Product logo",
      "href": "https://example.com",
      "kind": "image",
      "name": "Feature image",
      "classes": "object-cover",
      "new_tab": true,
      "asset_id": "asset_fixture_logo"
    },
    "hero": {
      "id": "hero",
      "tag": "section",
      "kind": "section",
      "name": "Hero",
      "classes": "flex flex-col items-center gap-6 py-24 px-8 bg-slate-900",
      "children": [
        "headline",
        "sub",
        "cta"
      ]
    },
    "root": {
      "id": "root",
      "kind": "container",
      "classes": "",
      "new_tab": false,
      "children": [
        "hero",
        "features"
      ]
    },
    "fgrid": {
      "id": "fgrid",
      "kind": "container",
      "name": "Feature grid",
      "classes": "grid grid-cols-3 gap-6 px-4 py-2 bg-card text-dark",
      "new_tab": false,
      "children": [
        "fimg",
        "ficon",
        "fembed"
      ]
    },
    "ficon": {
      "id": "ficon",
      "icon": "star",
      "kind": "icon",
      "name": "Feature icon",
      "classes": "px-2 py-2 text-primary"
    },
    "fembed": {
      "id": "fembed",
      "url": "https://example.com/widget",
      "html": "",
      "kind": "embed",
      "name": "Feature embed",
      "classes": "",
      "provider": "custom"
    },
    "features": {
      "id": "features",
      "tag": "section",
      "kind": "section",
      "name": "Features",
      "classes": "flex flex-col gap-8 py-16 px-8 bg-light",
      "children": [
        "fgrid"
      ]
    },
    "headline": {
      "id": "headline",
      "kind": "text",
      "name": "Headline",
      "classes": "text-5xl font-bold text-white text-center",
      "content": {
        "blocks": [
          {
            "type": "paragraph",
            "children": [
              {
                "text": "Insight Health",
                "type": "text"
              }
            ]
          }
        ],
        "schema_version": 1
      },
      "variant": "body"
    }
  }
} as never;

/**
 * W4.5 fixture: the page ROOT — the canvas schema's node — harvested from the
 * same document at **version 47**, captured 2026-08-18 via the design API
 * (`GET /documents/{id}` → `scene.pages[0]`, never hand-written).
 *
 * Why its own snapshot: the roots above carry `classes: ""`, so neither can
 * show a background token reaching canvas state. This one does — one
 * `set_node_classes` op (46 → 47) put the document's real `surface-canvas`
 * theme token on the root, exactly the class the Background popover writes.
 *
 * The kind is the load-bearing byte: `lumen-web` builds every page root as a
 * Container (`crates/lumen-web/src/doc.rs::WebDoc::new`), and the canvas
 * schema is chosen by node ID (`inspectorSelectionFor`), not by kind — so
 * row 1's background write rides row 19's container kind rather than needing a
 * kind of its own.
 */
export const HARVESTED_PAGE_ROOT_V47: { page_root: string; nodes: Record<string, WebNode> } =
{
  "page_root": "root",
  "nodes": {
    "root": {
      "id": "root",
      "kind": "container",
      "classes": "bg-surface-canvas",
      "new_tab": false,
      "children": [
        "hero",
        "features"
      ]
    }
  }
} as never;

/**
 * W4.9 fixture: the feature-grid **container as the visibility eye left it** —
 * harvested from the same document (`doc_31126145a0aa4753920629ae323a301b`) at
 * **version 52**, `GET /documents/{id}` → `scene.pages[0]`, never hand-written.
 *
 * Provenance is the point: version 52 was produced by clicking the inspector
 * header's eye on the live editor (51 → 52), so these are the exact bytes row
 * 40's write puts on disk — `grid` gone, `hidden` appended, every other token
 * in place. It is the one fixture that proves the eye and W4.4's Flex/Grid/Hide
 * segmented share a facet rather than agreeing by coincidence: hydrating it
 * yields `visible: false` AND `layoutMode: "Hide"` from the same parse.
 */
export const HARVESTED_HIDDEN_CONTAINER_V52: { page_root: string; nodes: Record<string, WebNode> } =
{
  "page_root": "root",
  "nodes": {
    "fgrid": {
      "id": "fgrid",
      "kind": "container",
      "name": "Feature grid",
      "classes": "grid-cols-3 gap-6 px-4 bg-card text-dark py-8 hidden",
      "new_tab": false,
      "children": [
        "fimg",
        "ficon",
        "fembed"
      ]
    }
  }
} as never;

/**
 * W4.6 fixture: the feature **icon** carrying ONE padding axis — harvested
 * from the same document (`doc_31126145a0aa4753920629ae323a301b`) at **version
 * 56**, `GET /documents/{id}` → `scene.pages[0]`, never hand-written.
 *
 * Why this snapshot exists: every earlier harvest catches `ficon` with BOTH
 * axes present ("px-2 py-2 text-primary"), which cannot exercise R3's truthful
 * zero — the rule that an absent axis is real zero padding, not the dummy's
 * fixture default. One `set_node_classes` op (55 → 56) dropped `py-2`, so these
 * are real bytes for the state the icon's two-box Layout control must state
 * honestly: X = 2, Y = 0.
 *
 * The `text-primary` token is deliberately left in place: per ruling 18b the
 * trimmed icon schema shows NO color control, so this class is the authored
 * page's own styling that every icon write must leave untouched.
 */
export const HARVESTED_ICON_V56: { page_root: string; nodes: Record<string, WebNode> } =
{
  "page_root": "root",
  "nodes": {
    "ficon": {
      "id": "ficon",
      "icon": "star",
      "kind": "icon",
      "name": "Feature icon",
      "classes": "px-2 text-primary"
    }
  }
} as never;

/**
 * W4.4 fixtures: a SECOND wire-true harvest of the same document
 * (`doc_31126145a0aa4753920629ae323a301b`, workspace "Insight Health" dev DB)
 * at **version 33**, captured 2026-08-18 via the design API — again as
 * `GET /documents/{id}` serves it under `scene`, never hand-written.
 *
 * Why a second snapshot rather than a re-harvest of the one above: the v2
 * snapshot is the frozen baseline the W3.2 text-schema tests assert against
 * (browser verification since then has legitimately changed `sub`'s classes),
 * so it stays put. This one exists for two reasons:
 *   • the hero **section** now carries BOTH section props — `tag` *and*
 *     `anchor_id` ("hero-anchor", written by one `set_node_props` call that
 *     took the document 32 → 33) — which is what the contract §4
 *     props-preservation regression test needs real bytes for;
 *   • the container (`fgrid`) and section (`hero`/`features`) nodes carry the
 *     display/direction/gap/padding/color utilities rows 19/20/22 map.
 */
export const HARVESTED_PAGE_V33: { page_root: string; nodes: Record<string, WebNode> } =
{
  "page_root": "root",
  "nodes": {
    "cta": {
      "id": "cta",
      "href": "#",
      "kind": "button",
      "name": "CTA",
      "label": "Book a demo",
      "classes": "rounded-full bg-white text-slate-900 px-6 py-3 font-semibold",
      "new_tab": false,
      "variant": "primary"
    },
    "sub": {
      "id": "sub",
      "kind": "text",
      "name": "Subheadline",
      "classes": "text-center max-w-xl text-xl font-normal text-accent",
      "content": {
        "blocks": [
          {
            "type": "paragraph",
            "children": [
              {
                "text": "AI fax, referral, and document-processing agents that route inbound work into the right EHR queue.",
                "type": "text"
              }
            ]
          }
        ],
        "schema_version": 1
      },
      "variant": "body"
    },
    "fimg": {
      "id": "fimg",
      "alt": "Product logo",
      "href": "https://example.com",
      "kind": "image",
      "name": "Feature image",
      "classes": "object-cover",
      "new_tab": true,
      "asset_id": "asset_fixture_logo"
    },
    "hero": {
      "id": "hero",
      "tag": "section",
      "kind": "section",
      "name": "Hero",
      "classes": "flex flex-col items-center gap-6 py-24 px-8 bg-slate-900",
      "children": [
        "headline",
        "sub",
        "cta"
      ],
      "anchor_id": "hero-anchor"
    },
    "root": {
      "id": "root",
      "kind": "container",
      "classes": "",
      "new_tab": false,
      "children": [
        "hero",
        "features"
      ]
    },
    "fgrid": {
      "id": "fgrid",
      "kind": "container",
      "name": "Feature grid",
      "classes": "grid grid-cols-3 gap-6 px-4 py-2 bg-card text-dark",
      "new_tab": false,
      "children": [
        "fimg",
        "ficon",
        "fembed"
      ]
    },
    "ficon": {
      "id": "ficon",
      "icon": "star",
      "kind": "icon",
      "name": "Feature icon",
      "classes": "px-2 py-2 text-primary"
    },
    "fembed": {
      "id": "fembed",
      "url": "https://example.com/widget",
      "html": "",
      "kind": "embed",
      "name": "Feature embed",
      "classes": "",
      "provider": "custom"
    },
    "features": {
      "id": "features",
      "tag": "section",
      "kind": "section",
      "name": "Features",
      "classes": "flex flex-col gap-8 py-16 px-8 bg-light",
      "children": [
        "fgrid"
      ]
    },
    "headline": {
      "id": "headline",
      "kind": "text",
      "name": "Headline",
      "classes": "text-5xl text-center font-bold text-light",
      "content": {
        "blocks": [
          {
            "type": "paragraph",
            "children": [
              {
                "text": "Insight Health",
                "type": "text"
              }
            ]
          }
        ],
        "schema_version": 1
      },
      "variant": "body"
    }
  }
} as never;
/**
 * W4.2 (lane B) fixtures: a second REAL harvest, seeded for the image/button
 * radius work — document `doc_298a0c3a512640fbb6823b68b8016733` version 1,
 * page `home`, captured 2026-08-18 via the design API and copied byte-faithful
 * from `.superpowers/sdd/2026-08-18-w4-lane-b-brief/harvested-nodes.json`.
 * The three images cover the radius cases the first harvest lacks:
 * `img_plain` an arbitrary pixel radius (`rounded-[8px]`), `img_linked` a
 * named all-corners radius plus one corner override (`rounded-lg
 * rounded-tl-[4px]`) and the linked/new-tab pair, `img_bare` the bare
 * `rounded` default (which the engine parses as null, §1 row 14).
 */
export const HARVESTED_IMAGE_PAGE: {
  page_root: string;
  nodes: Record<string, WebNode>;
} = {
  "page_root": "root",
  "nodes": {
    "cta": {
      "id": "cta",
      "href": "https://example.com/offer",
      "kind": "button",
      "name": "CTA",
      "label": "See the offer",
      "classes": "bg-accent text-dark px-4 py-2 rounded-md",
      "new_tab": false,
      "variant": "secondary"
    },
    "hero": {
      "id": "hero",
      "tag": "section",
      "kind": "section",
      "name": "Hero",
      "classes": "flex flex-col gap-6 px-8 py-12 bg-light",
      "children": [
        "img_linked",
        "img_plain",
        "img_bare",
        "cta"
      ],
      "anchor_id": "laneb-hero"
    },
    "root": {
      "id": "root",
      "kind": "container",
      "classes": "",
      "new_tab": false,
      "children": [
        "hero"
      ]
    },
    "img_bare": {
      "id": "img_bare",
      "alt": "Bare rounded",
      "kind": "image",
      "name": "Bare rounded",
      "classes": "rounded w-80",
      "new_tab": false,
      "asset_id": "asset_c42b6ba24117"
    },
    "img_plain": {
      "id": "img_plain",
      "alt": "Teal banner plain",
      "kind": "image",
      "name": "Plain banner",
      "classes": "object-contain rounded-[8px] w-80",
      "new_tab": false,
      "asset_id": "asset_c42b6ba24117"
    },
    "img_linked": {
      "id": "img_linked",
      "alt": "Teal banner",
      "href": "https://example.com/teal",
      "kind": "image",
      "name": "Linked banner",
      "classes": "object-cover rounded-lg rounded-tl-[4px] w-80",
      "new_tab": true,
      "asset_id": "asset_c42b6ba24117"
    }
  }
} as never;

/**
 * Documented classes-variants for the radius cases the harvest does not carry:
 * the SAME harvested node (`img_plain`), only its `classes` string altered —
 * no hand-invented node shape. Keyed by the case each one proves.
 */
export const IMAGE_RADIUS_CLASS_VARIANTS = {
  /** No radius utility at all → the designed empty, not "0". */
  none: "object-contain w-80",
  /** A variant-prefixed token is opaque to the facets (engine header). */
  variantOnly: "hover:rounded-xl w-80",
  /** An arbitrary value that is not the `[<digits>px]` shape displays
   * verbatim. */
  arbitraryNonPixel: "rounded-[50%] w-80",
  /** A named scale value displays verbatim. */
  named: "rounded-full w-80"
} as const;
