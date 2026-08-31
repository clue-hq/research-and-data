/**
 * AD2.2 fixtures: a REAL scene-document snapshot harvested from the seeded ad,
 * exactly as `GET /documents/{id}` serves it under the `scene` key — NOT
 * hand-written shapes (the W2.2 law the website lane set: every adapter in
 * AD2/AD3/AD4 is TDD'd against these bytes).
 *
 * Harvest provenance
 * ------------------
 *   document   `doc_ad22linkedinsquare00000000001` ("Insight Health — LinkedIn square ad")
 *   workspace  `ws_8040294627e146ae93f753ec0d3e1726` ("Insight Health", dev DB)
 *   version    0 (birth — the document has had no edits)
 *   captured   2026-08-20, design API on :8010
 *   command    curl -s -H 'X-Workspace-Id: ws_8040294627e146ae93f753ec0d3e1726' \
 *                http://127.0.0.1:8010/documents/doc_ad22linkedinsquare00000000001
 *   seeded by  `scripts/seed_ad_document.py` (idempotent; `--recreate` re-mints it)
 *
 * One node per contract schema, arranged as an actual 1200x1200 LinkedIn square
 * ad rather than a test grid — a padded auto-layout copy row (headline + a
 * two-child proof-point group) over a gradient accent bar, a hairline rule, and
 * a rounded hero image with real bytes behind it:
 *
 *   frame       `frame_ad_root`      clipped, solid #0E0B2E, 1200x1200
 *   auto_layout `auto_row_copy`      row, gap 32, padding [40,44,40,44]
 *   text        `text_headline`      brand TOKEN fill (`$text.inverse`), width fixed / height hug
 *   group       `group_proof`        two children, width FILL(1) / height fixed
 *   ellipse     `ellipse_proof_dot`  solid accent
 *   text        `text_proof_stat`    explicit Inter/26/600, opacity 0.8
 *   rect        `rect_accent_bar`    3-stop linear gradient, angle 90
 *   line        `line_divider`       the §5 unrepresented kind
 *   image       `image_hero`         asset_placement.fit "cover", asymmetric corner radii
 *
 * Three things about these bytes are load-bearing and easy to mistake for typos:
 *   • `computed` is `null` on EVERY node. That is the honest at-rest state — the
 *     engine solves layout in the renderer/preflight and never persists geometry
 *     back onto the stored scene (verified: no stored scene document in the dev DB
 *     carries a `computed` block). Position hydration therefore reads `transform`,
 *     not a stored computed box.
 *   • the serialized `corner` key ORDER is TL, TR, BL, BR while the contract type's
 *     field order is TL, TR, BR, BL. `auto_row_copy` / `image_hero` carry
 *     `bottom_left: 96` and `bottom_right: 32`, so a BR/BL swap fails loudly.
 *   • the page is `preset: "custom"` at 1200x1200pt. The engine's own
 *     `PagePreset::LinkedinAd` is the 1200x627 banner, so `custom` is the truthful
 *     value; the inspector's preset select matches on SIZE (contract §1.1's
 *     corrected LinkedIn square), which is the exact-match case this fixture serves.
 */
import type { Node, NodeId, Scene } from "../../engine/scene/contracts";

export const HARVESTED_AD_PAGE: Scene = {
  "meta": {
    "id": "doc_ad22linkedinsquare00000000001",
    "title": "Insight Health — LinkedIn square ad",
    "medium": "ad",
    "status": {
      "kind": "draft"
    },
    "brand_kit": {
      "id": "brand_kit_ing_813df4f30f2d429a853dbccae2277a5a",
      "version": 6
    },
    "artifact_type": "linkedin_square_ad"
  },
  "nodes": {
    "image_hero": {
      "id": "image_hero",
      "clip": true,
      "kind": {
        "alt": "Brand gradient backdrop",
        "kind": "image",
        "asset_id": "asset_ing_2b0928ca4f3a3c70"
      },
      "name": "Hero image",
      "size": {
        "width": {
          "kind": "fixed",
          "value": 1056.0
        },
        "height": {
          "kind": "fixed",
          "value": 676.0
        }
      },
      "fills": [],
      "corner": {
        "top_left": 32.0,
        "top_right": 32.0,
        "bottom_left": 96.0,
        "bottom_right": 32.0
      },
      "layout": null,
      "locked": false,
      "opacity": 1.0,
      "strokes": [],
      "children": [],
      "computed": null,
      "transform": {
        "x": 72.0,
        "y": 452.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      },
      "asset_placement": {
        "fit": "cover",
        "alt_text": "Brand gradient backdrop",
        "focal_point": {
          "x": 0.5,
          "y": 0.42
        },
        "preserve_transparency": false
      },
      "source_asset_id": "asset_ing_2b0928ca4f3a3c70"
    },
    "group_proof": {
      "id": "group_proof",
      "clip": false,
      "kind": {
        "kind": "group"
      },
      "name": "Proof point",
      "size": {
        "width": {
          "kind": "fill",
          "value": {
            "weight": 1.0
          }
        },
        "height": {
          "kind": "fixed",
          "value": 104.0
        }
      },
      "fills": [],
      "corner": {
        "top_left": 0.0,
        "top_right": 0.0,
        "bottom_left": 0.0,
        "bottom_right": 0.0
      },
      "layout": null,
      "locked": false,
      "opacity": 1.0,
      "strokes": [],
      "children": [
        "ellipse_proof_dot",
        "text_proof_stat"
      ],
      "computed": null,
      "transform": {
        "x": 0.0,
        "y": 0.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      }
    },
    "line_divider": {
      "id": "line_divider",
      "clip": false,
      "kind": {
        "x2": 1056.0,
        "y2": 0.0,
        "kind": "line"
      },
      "name": "Divider",
      "size": {
        "width": {
          "kind": "fixed",
          "value": 1056.0
        },
        "height": {
          "kind": "fixed",
          "value": 2.0
        }
      },
      "fills": [],
      "corner": {
        "top_left": 0.0,
        "top_right": 0.0,
        "bottom_left": 0.0,
        "bottom_right": 0.0
      },
      "layout": null,
      "locked": false,
      "opacity": 1.0,
      "strokes": [
        {
          "id": "stroke_divider",
          "paint": {
            "kind": "solid",
            "color": {
              "kind": "hex",
              "value": "#2E2470"
            }
          },
          "width": 2.0
        }
      ],
      "children": [],
      "computed": null,
      "transform": {
        "x": 72.0,
        "y": 412.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      }
    },
    "auto_row_copy": {
      "id": "auto_row_copy",
      "clip": false,
      "kind": {
        "kind": "auto_layout",
        "wrap": false,
        "direction": "row"
      },
      "name": "Copy row",
      "size": {
        "width": {
          "kind": "fixed",
          "value": 1056.0
        },
        "height": {
          "kind": "hug"
        }
      },
      "fills": [
        {
          "id": "paint_card",
          "paint": {
            "kind": "solid",
            "color": {
              "kind": "hex",
              "value": "#171043"
            }
          }
        }
      ],
      "corner": {
        "top_left": 32.0,
        "top_right": 32.0,
        "bottom_left": 96.0,
        "bottom_right": 32.0
      },
      "layout": {
        "gap": 32.0,
        "grow": 0.0,
        "align_x": "start",
        "align_y": "center",
        "padding": [
          40.0,
          44.0,
          40.0,
          44.0
        ]
      },
      "locked": false,
      "opacity": 1.0,
      "strokes": [
        {
          "id": "stroke_card",
          "paint": {
            "kind": "solid",
            "color": {
              "kind": "hex",
              "value": "#2E2470"
            }
          },
          "width": 2.0
        }
      ],
      "children": [
        "text_headline",
        "group_proof"
      ],
      "computed": null,
      "transform": {
        "x": 72.0,
        "y": 72.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      }
    },
    "frame_ad_root": {
      "id": "frame_ad_root",
      "clip": true,
      "kind": {
        "kind": "frame"
      },
      "name": "Ad artboard",
      "size": {
        "width": {
          "kind": "fixed",
          "value": 1200.0
        },
        "height": {
          "kind": "fixed",
          "value": 1200.0
        }
      },
      "fills": [
        {
          "id": "paint_root_ink",
          "paint": {
            "kind": "solid",
            "color": {
              "kind": "hex",
              "value": "#0E0B2E"
            }
          }
        }
      ],
      "corner": {
        "top_left": 0.0,
        "top_right": 0.0,
        "bottom_left": 0.0,
        "bottom_right": 0.0
      },
      "layout": null,
      "locked": false,
      "opacity": 1.0,
      "strokes": [],
      "children": [
        "auto_row_copy",
        "rect_accent_bar",
        "line_divider",
        "image_hero"
      ],
      "computed": null,
      "transform": {
        "x": 0.0,
        "y": 0.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      }
    },
    "text_headline": {
      "id": "text_headline",
      "clip": false,
      "kind": {
        "kind": "text",
        "wrap": "wrap",
        "align": "left",
        "valign": "center",
        "content": "Every inbound fax, routed to the right EHR queue.",
        "direction": "ltr",
        "font_size": 54.0,
        "font_family": "Inter",
        "font_weight": 700,
        "line_height": 1.1,
        "letter_spacing": -0.5
      },
      "name": "Headline",
      "size": {
        "width": {
          "kind": "fixed",
          "value": 632.0
        },
        "height": {
          "kind": "hug"
        }
      },
      "fills": [
        {
          "id": "paint_headline",
          "paint": {
            "kind": "token",
            "token": "$text.inverse"
          }
        }
      ],
      "corner": {
        "top_left": 0.0,
        "top_right": 0.0,
        "bottom_left": 0.0,
        "bottom_right": 0.0
      },
      "layout": null,
      "locked": false,
      "opacity": 1.0,
      "strokes": [],
      "children": [],
      "computed": null,
      "transform": {
        "x": 0.0,
        "y": 0.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      }
    },
    "rect_accent_bar": {
      "id": "rect_accent_bar",
      "clip": false,
      "kind": {
        "kind": "rect"
      },
      "name": "Accent bar",
      "size": {
        "width": {
          "kind": "fixed",
          "value": 320.0
        },
        "height": {
          "kind": "fixed",
          "value": 10.0
        }
      },
      "fills": [
        {
          "id": "paint_accent_bar",
          "paint": {
            "kind": "linear_gradient",
            "angle": 90.0,
            "stops": [
              {
                "color": {
                  "kind": "hex",
                  "value": "#533AFD"
                },
                "position": 0.0
              },
              {
                "color": {
                  "kind": "hex",
                  "value": "#8B5CF6"
                },
                "position": 0.5
              },
              {
                "color": {
                  "kind": "hex",
                  "value": "#EA2261"
                },
                "position": 1.0
              }
            ]
          }
        }
      ],
      "corner": {
        "top_left": 5.0,
        "top_right": 5.0,
        "bottom_left": 5.0,
        "bottom_right": 5.0
      },
      "layout": null,
      "locked": false,
      "opacity": 1.0,
      "strokes": [],
      "children": [],
      "computed": null,
      "transform": {
        "x": 72.0,
        "y": 368.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      }
    },
    "text_proof_stat": {
      "id": "text_proof_stat",
      "clip": false,
      "kind": {
        "kind": "text",
        "wrap": "wrap",
        "align": "left",
        "content": "3.4x faster triage",
        "direction": "ltr",
        "font_size": 26.0,
        "font_family": "Inter",
        "font_weight": 600,
        "line_height": 1.35,
        "letter_spacing": 0.0
      },
      "name": "Proof stat",
      "size": {
        "width": {
          "kind": "fixed",
          "value": 256.0
        },
        "height": {
          "kind": "hug"
        }
      },
      "fills": [
        {
          "id": "paint_stat",
          "paint": {
            "kind": "solid",
            "color": {
              "kind": "hex",
              "value": "#C7C2F5"
            }
          }
        }
      ],
      "corner": {
        "top_left": 0.0,
        "top_right": 0.0,
        "bottom_left": 0.0,
        "bottom_right": 0.0
      },
      "layout": null,
      "locked": false,
      "opacity": 0.8,
      "strokes": [],
      "children": [],
      "computed": null,
      "transform": {
        "x": 44.0,
        "y": 24.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      }
    },
    "ellipse_proof_dot": {
      "id": "ellipse_proof_dot",
      "clip": false,
      "kind": {
        "kind": "ellipse"
      },
      "name": "Accent dot",
      "size": {
        "width": {
          "kind": "fixed",
          "value": 24.0
        },
        "height": {
          "kind": "fixed",
          "value": 24.0
        }
      },
      "fills": [
        {
          "id": "paint_dot",
          "paint": {
            "kind": "solid",
            "color": {
              "kind": "hex",
              "value": "#EA2261"
            }
          }
        }
      ],
      "corner": {
        "top_left": 0.0,
        "top_right": 0.0,
        "bottom_left": 0.0,
        "bottom_right": 0.0
      },
      "layout": null,
      "locked": false,
      "opacity": 1.0,
      "strokes": [],
      "children": [],
      "computed": null,
      "transform": {
        "x": 0.0,
        "y": 40.0,
        "flip_x": false,
        "flip_y": false,
        "skew_x": 0.0,
        "skew_y": 0.0,
        "rotation": 0.0
      }
    }
  },
  "pages": {
    "page_linkedin_square": {
      "id": "page_linkedin_square",
      "name": "LinkedIn square",
      "size": {
        "unit": "pt",
        "width": 1200.0,
        "height": 1200.0,
        "output": {
          "raster": {
            "width_px": 1200,
            "height_px": 1200
          }
        },
        "preset": "custom",
        "source": {
          "unit": "px",
          "width": 1200.0,
          "height": 1200.0
        },
        "orientation": "portrait"
      },
      "bleed": null,
      "children": [
        "frame_ad_root"
      ],
      "safe_area": {
        "x": 64.0,
        "y": 64.0,
        "width": 1072.0,
        "height": 1072.0
      },
      "background": []
    }
  },
  "slots": {},
  "assets": {
    "asset_ing_2b0928ca4f3a3c70": {
      "id": "asset_ing_2b0928ca4f3a3c70",
      "font": null,
      "kind": "raster_image",
      "logo": null,
      "tags": [
        "brand-ingestion",
        "image"
      ],
      "label": "payment-bento-background.jpg",
      "media": {
        "digest": {
          "value": "2b0928ca4f3a3c70c5c2fed22996f0428da219c953a14e71567b73c1d8af937a",
          "algorithm": "sha256"
        },
        "filename": "payment-bento-background.jpg",
        "location": {
          "url": null,
          "provider": "clue-storage",
          "opaque_ref": "ws_8040294627e146ae93f753ec0d3e1726/design/2b0928ca4f3a3c70c5c2fed22996f0428da219c953a14e71567b73c1d8af937a"
        },
        "mime_type": "image/jpeg",
        "thumbnail": {
          "location": {
            "url": null,
            "provider": "clue-storage",
            "opaque_ref": "ws_8040294627e146ae93f753ec0d3e1726/design/5d799142fbc142b8f6164dc07d986a4db2690e4b7739a4f01037d9a59621f869"
          },
          "mime_type": "image/png",
          "pixel_width": 256,
          "pixel_height": 212
        },
        "byte_length": 23935
      },
      "raster": {
        "dpi_x": null,
        "dpi_y": null,
        "has_alpha": false,
        "pixel_width": 860,
        "aspect_ratio": 1.2078651685393258,
        "pixel_height": 712,
        "color_profile": null
      },
      "source": {
        "url": "https://images.stripeassets.com/fzn2n1nzq965/vYmk6v8n7oDAwbDpwhjV6/846f9b3e214549b8f14e2b8c8cfe9343/payment-bento-background.jpg?w=860&q=80",
        "kind": "website",
        "captured_at": "2026-08-20T00:57:57.366048+00:00"
      },
      "status": "ready",
      "vector": null,
      "license": null,
      "provenance": {
        "notes": [],
        "confidence": 0.7,
        "created_at": "2026-08-20T00:57:57.366048+00:00",
        "created_by": "lumen_ingestion",
        "source_label": "website"
      }
    }
  },
  "schema_version": 1,
  "export_profiles": [
    {
      "name": "linkedin-square",
      "format": "png",
      "raster": {
        "dpi": null,
        "scale": 1.0
      },
      "pdf_intent": null,
      "embed_fonts": false,
      "include_bleed": false
    }
  ]
};

/** The harvested page id — the scene has exactly one page. */
export const AD_PAGE_ID = "page_linkedin_square";

/** The seeded document's id, for tests that assert against the real document. */
export const AD_DOCUMENT_ID = "doc_ad22linkedinsquare00000000001";

/**
 * Fixture node by id — throws rather than returning `undefined`, so a renamed or
 * dropped node fails the test that needed it instead of silently hydrating
 * nothing (mirrors the `node(id)` helper the web adapter tests use).
 */
export function adNode(id: NodeId): Node {
  const found = HARVESTED_AD_PAGE.nodes[id];
  if (!found) {
    throw new Error(`fixture node ${id} missing from HARVESTED_AD_PAGE`);
  }
  return found;
}

/** Every inventory kind, reachable by name. Each is `adNode` — same throw. */
export const adFrame = (): Node => adNode("frame_ad_root");
export const adAutoLayout = (): Node => adNode("auto_row_copy");
/** The token-bound text (fill is `$text.inverse`, not a literal). */
export const adTokenText = (): Node => adNode("text_headline");
/** The explicitly-styled text (Inter/26/600) — also the opacity-0.8 node. */
export const adPlainText = (): Node => adNode("text_proof_stat");
export const adGroup = (): Node => adNode("group_proof");
export const adEllipse = (): Node => adNode("ellipse_proof_dot");
export const adRect = (): Node => adNode("rect_accent_bar");
/** The §5 unrepresented kind — selection must resolve to an ancestor, not a schema. */
export const adLine = (): Node => adNode("line_divider");
export const adImage = (): Node => adNode("image_hero");
