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
