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
