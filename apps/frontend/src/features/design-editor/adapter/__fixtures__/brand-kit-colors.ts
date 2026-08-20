/**
 * AD4.0 step 3 fixture: the REAL brand-kit colour catalog harvested from the
 * kit the seeded ad document is bound to, exactly as `GET /brand-kits/{id}`
 * serves it under `brand_kit_json.tokens` — NOT hand-written shapes (the
 * AD2.2/W2.2 law: every adapter in AD2/AD3/AD4 is TDD'd against real bytes).
 *
 * Harvest provenance
 * ------------------
 *   brand kit  `brand_kit_ing_813df4f30f2d429a853dbccae2277a5a` ("Stripe")
 *   version    8 (the version the route served at capture — see the caveat)
 *   workspace  `ws_8040294627e146ae93f753ec0d3e1726` ("Insight Health", dev DB)
 *   captured   2026-08-21, design API on :8010
 *   command    curl -s -H 'X-Workspace-Id: ws_8040294627e146ae93f753ec0d3e1726' \
 *                http://127.0.0.1:8010/brand-kits/brand_kit_ing_813df4f30f2d429a853dbccae2277a5a
 *   bound by   `HARVESTED_AD_PAGE.meta.brand_kit` (`{id, version: 6}`)
 *
 * SLICE, not the whole payload: `brand_kit_json.tokens.colors` and
 * `.tokens.aliases`, which are the only two maps `buildTokenColorMap` reads
 * (`engine/scene/tokenColors.ts`). The kit's other token families (typography,
 * spacing, radii, stroke widths, opacity, shadows, effects, assets) and the
 * envelope around them (`brand_kit`, `brand_summary`, `diagnostics`) are
 * elided — every entry below is byte-for-byte as served, including the
 * `role`/`provenance`/`description` fields the colour parser ignores, so the
 * fixture also proves the parser tolerates them.
 *
 * Three facts about these bytes are load-bearing for §1.6:
 *   • 42 colour tokens, of which 22 are `palette.*` ramp steps
 *     (`role: "palette"`) and 20 are semantic roles (surface/text/border/
 *     focus). The name prefix and the server's own `role` agree on every one
 *     of the 42, and the 20 semantic names are EXACTLY the colour buckets the
 *     same response publishes under `brand_summary.tokens`
 *     (`text_tokens` + `surface_tokens` + `border_tokens` + `focus_tokens`) —
 *     the catalog upstream's `ColorSwatchControl` offers from. That agreement
 *     is why `scene-palette.ts` can filter on the name and still land on the
 *     server's own answer without a second parser.
 *   • every `value.default` here is `{kind:"hex"}`. The `oklch` and `alias`
 *     value kinds `tokenColors.ts` also handles are NOT exercised by this kit,
 *     so the tests that cover them derive from these bytes and say so.
 *   • `tokens.aliases` carries one entry — `accent.primary` -> `surface.accent`
 *     ("ingestion alias"). `buildTokenColorMap` folds it into the resolution
 *     map; `brand_summary.tokens` does not publish it, and neither does the
 *     picker (see `buildScenePalette`).
 *
 * CAVEAT recorded at capture: the scene pins `brand_kit.version: 6` while
 * `GET /brand-kits/{id}` serves the LATEST version (8 here) — the route takes
 * no version. The session's font path has always read the kit this way; the
 * palette inherits it. See the fetch site in `use-scene-editing-session.ts`.
 */
import type { BrandKitDetailPayload } from "../../engine/scene/tokenColors";

/**
 * The bytes, UNANNOTATED on purpose: every entry carries the server's
 * `role`/`provenance`/`description`/`modes` fields, which the parser's
 * deliberately-narrow `BrandKitDetailPayload` does not name — annotating the
 * literal would trip TypeScript's excess-property check on a payload we do not
 * own. `adBrandKit()` below is the typed accessor, so the assignability is
 * still checked, just not against a fresh literal.
 */
export const HARVESTED_AD_BRAND_KIT = {
  "tokens": {
    "colors": {
      "focus.ring": {
        "role": "focus",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#8F9AFF"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#6D70FF"
          }
        },
        "provenance": {
          "source": "derived:focus.ring",
          "confidence": 0.6
        },
        "description": null
      },
      "text.brand": {
        "role": "text",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#B5BFFF"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#533AFD"
          }
        },
        "provenance": {
          "source": "derived:text.brand",
          "confidence": 0.6
        },
        "description": null
      },
      "text.muted": {
        "role": "text",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#838592"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#2E2E2E"
          }
        },
        "provenance": {
          "source": "derived:text.muted",
          "confidence": 0.6
        },
        "description": null
      },
      "text.accent": {
        "role": "text",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#FF9DAB"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#4329D5"
          }
        },
        "provenance": {
          "source": "derived:text.accent",
          "confidence": 0.6
        },
        "description": null
      },
      "border.brand": {
        "role": "border",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#6D70FF"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#6D70FF"
          }
        },
        "provenance": {
          "source": "derived:border.brand",
          "confidence": 0.6
        },
        "description": null
      },
      "surface.card": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#16192D"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#F8FAFD"
          }
        },
        "provenance": {
          "source": "website:rendered :: footer",
          "confidence": 0.9
        },
        "description": null
      },
      "surface.page": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#0D0F23"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#F8FAFD"
          }
        },
        "provenance": {
          "source": "website:rendered :: footer",
          "confidence": 0.9
        },
        "description": null
      },
      "text.inverse": {
        "role": "text",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#000000"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#FFFFFF"
          }
        },
        "provenance": {
          "source": "derived:text.inverse",
          "confidence": 0.6
        },
        "description": null
      },
      "text.primary": {
        "role": "text",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#EBEEFC"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#000000"
          }
        },
        "provenance": {
          "source": "website:rendered :: body",
          "confidence": 0.9
        },
        "description": null
      },
      "border.strong": {
        "role": "border",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#585C74"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#898B8D"
          }
        },
        "provenance": {
          "source": "derived:border.strong",
          "confidence": 0.6
        },
        "description": null
      },
      "border.subtle": {
        "role": "border",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#292C42"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#DEDFE2"
          }
        },
        "provenance": {
          "source": "derived:border.subtle",
          "confidence": 0.6
        },
        "description": null
      },
      "surface.brand": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#8F9AFF"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#533AFD"
          }
        },
        "provenance": {
          "source": "website:https://b.stripecdn.com/mkt-ssr-statics/assets/_next/static/css/c56888b4229cd132.css :: .sessions-section__cta-button",
          "confidence": 0.9
        },
        "description": null
      },
      "surface.muted": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#1B1D32"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#E7E9EC"
          }
        },
        "provenance": {
          "source": "derived:surface.muted",
          "confidence": 0.6
        },
        "description": null
      },
      "border.default": {
        "role": "border",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#3D4158"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#C4C6C8"
          }
        },
        "provenance": {
          "source": "derived:border.default",
          "confidence": 0.6
        },
        "description": null
      },
      "surface.accent": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#FF8096"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#EA2261"
          }
        },
        "provenance": {
          "source": "website:css :: --hds-color-accentColorMode-ruby-icon-solid",
          "confidence": 0.9
        },
        "description": null
      },
      "surface.canvas": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#08091C"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#FAFCFF"
          }
        },
        "provenance": {
          "source": "derived:surface.canvas",
          "confidence": 0.6
        },
        "description": null
      },
      "text.secondary": {
        "role": "text",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#B4B6C4"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#161616"
          }
        },
        "provenance": {
          "source": "derived:text.secondary",
          "confidence": 0.6
        },
        "description": null
      },
      "surface.inverse": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#F8FAFD"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#101214"
          }
        },
        "provenance": {
          "source": "derived:surface.inverse",
          "confidence": 0.6
        },
        "description": null
      },
      "surface.elevated": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#1F2237"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#FAFAFA"
          }
        },
        "provenance": {
          "source": "derived:surface.elevated",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.50": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#FAFAFA"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.50)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.50": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#F9FAFF"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.50)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.100": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#F0F0F0"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.100)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.200": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#DEDEDE"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.200)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.300": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#C4C4C4"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.300)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.400": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#A4A4A4"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.400)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.500": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#868686"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.500)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.600": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#6C6C6C"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.600)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.700": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#555555"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.700)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.800": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#424242"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.800)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.900": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#2E2E2E"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.900)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.neutral.950": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#000000"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.neutral.950)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.100": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#ECEFFF"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.100)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.200": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#D5DCFF"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.200)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.300": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#B5BFFF"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.300)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.400": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#8F9AFF"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.400)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.500": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#6D70FF"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.500)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.600": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#533AFD"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.600)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.700": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#4329D5"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.700)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.800": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#3420A9"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.800)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.900": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#23137B"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.900)",
          "confidence": 0.6
        },
        "description": null
      },
      "palette.primary.950": {
        "role": "palette",
        "value": {
          "modes": {},
          "default": {
            "kind": "hex",
            "value": "#130750"
          }
        },
        "provenance": {
          "source": "derived:ramp(palette.primary.950)",
          "confidence": 0.6
        },
        "description": null
      },
      "surface.brand.subtle": {
        "role": "surface",
        "value": {
          "modes": {
            "theme.dark": {
              "kind": "hex",
              "value": "#222546"
            }
          },
          "default": {
            "kind": "hex",
            "value": "#ECEFFF"
          }
        },
        "provenance": {
          "source": "derived:surface.brand.subtle",
          "confidence": 0.6
        },
        "description": null
      }
    },
    "aliases": {
      "accent.primary": {
        "token": "surface.accent",
        "description": "ingestion alias"
      }
    }
  }
};

/**
 * The harvested kit as the parser's input. A LIVE reference into the shared
 * fixture (the `adNode` rule): a test that derives a variant must deep-copy
 * first, or it rewrites the fixture for every later test in every file.
 */
export function adBrandKit(): BrandKitDetailPayload {
  return HARVESTED_AD_BRAND_KIT;
}
