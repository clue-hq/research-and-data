import {
  buildTokenColorMap,
  resolveTokenColor,
  type BrandKitDetailPayload,
  type TokenColorMap,
} from "../engine/scene/tokenColors";
import type { ThemeColorOption } from "./theme-options";

/**
 * AD4.0 step 3: §1.6's colour policy for the SCENE (ad) lane — the brand
 * vocabulary every ad colour control offers, and what one swatch value means
 * as a colour.
 *
 * §1.6, in full: "Brand-kit colors are offered **first** in the picker;
 * **custom hex is allowed**, accompanied by the small 'this leaves your brand
 * palette' note (§6 mockup-gated wording/design). A raw color on a token-bound
 * element detaches its brand binding — that is the accepted, *informed*
 * trade." Gate G-B is OPEN, so the note is not rendered anywhere; this comment
 * and `scene-apply.ts`'s `solidHexPaint` are the only places it is mentioned.
 *
 * THE ROUTE, recorded here because the plan's own reference (`brandHub`) does
 * not exist: `GET /brand-kits/{id}/versions/{version}` →
 * `brand_kit_json.tokens.colors`, fetched through
 * `documentStore.fetchBrandKitDetail` and parsed by the engine's
 * `tokenColors.ts::buildTokenColorMap`. There is exactly ONE parser for that
 * payload and this module does not write a second — it decides only which of
 * the parsed tokens the picker OFFERS, and in what order.
 *
 * ── WHICH TOKENS ARE OFFERED (the decision, and its evidence) ─────────────
 * The seeded kit defines 42 colour tokens: 20 SEMANTIC roles (`surface.*`,
 * `text.*`, `border.*`, `focus.*`) and 22 `palette.*` RAMP steps. The picker
 * offers the 20 and hides the ramps. Three independent authorities agree:
 *
 *   • the SERVER's own catalog. The very same response carries
 *     `brand_summary.tokens` — a `BrandTokenCatalog` whose colour buckets
 *     (`text_tokens` + `surface_tokens` + `border_tokens` + `focus_tokens`)
 *     are EXACTLY those 20 names, ramps excluded. That catalog is what
 *     upstream's own picker offers from
 *     (`ColorSwatchControl.tsx:129-210` → `BrandTokenCatalog`), so this is the
 *     product's established answer to "which colour tokens are offerable",
 *     not a local invention. We do not READ it, because
 *     `fetchBrandKitDetail` returns `brand_kit_json` alone and that extracted
 *     engine module is a verbatim upstream port we may not edit — but the
 *     kit's own `role` field agrees with the name prefix on all 42 entries, so
 *     filtering on `palette.` lands on the identical set.
 *   • the WEBSITE lane's founder ruling F3 (2026-08-18): "technical palette-*
 *     ramps are hidden from the picker" (`theme-options.ts:44`). Same product
 *     decision, same control, different naming convention (`palette-` there,
 *     `palette.` here).
 *   • the CONTROL. `ColorControl`'s Theme tab is a flat, ungrouped list with
 *     no scroll affordance of its own; 42 swatches — 22 of them ramp steps
 *     that duplicate the semantic values (`palette.primary.600` IS
 *     `surface.brand`, #533AFD) — is not a palette a marketer can read.
 *
 * §1.6 itself says only "brand-kit colors are offered first", with no slot
 * semantics, so the *narrow* reading (every colour token, ramps included) is
 * not foreclosed by the contract. It is foreclosed by the three authorities
 * above, and this is recorded as a decision rather than a discovery.
 *
 * OFFERING and RESOLVING are deliberately different sets. A ramp or an alias
 * is hidden from the picker but still resolves through `colors`, so a document
 * an agent bound to `palette.primary.600` (or to the kit's legacy
 * `accent.primary` alias) still shows its real colour and can still seed a
 * gradient. The web lane conflated the two and recorded the consequence as a
 * known gap (`theme-options.ts:56-60`); with resolution split out, the ad lane
 * does not have it.
 *
 * ORDER: the kit's own token order, exactly as `buildThemeColorOptions` keeps
 * the server's. §1.6's "offered first" is about brand-vs-custom, and the
 * control already answers it structurally — the Theme tab is the DEFAULT tab
 * and holds only brand swatches, while custom hex lives behind the second tab.
 * Re-sorting inside the list would be UI policy with no design authority (the
 * control renders no group headings to sort into).
 */

/** One brand swatch the picker offers. `ColorControl` takes `ThemeColorOption`
 * (`{label, value}`); the extra `token` is what the write path needs, carried
 * explicitly so the label→token map is true BY CONSTRUCTION rather than by the
 * convention that they happen to coincide (they do today — a test pins it). */
export interface ScenePaletteOption extends ThemeColorOption {
  /** The brand-kit token this row writes, without the author-facing `$`. */
  token: string;
}

export interface ScenePalette {
  /** EVERY colour token the kit defines, ramps and aliases included — the
   * resolution map (`buildTokenColorMap`), never the offer list. */
  colors: TokenColorMap;
  /** §1.6: the brand swatches the picker offers, in the kit's own order. */
  options: readonly ScenePaletteOption[];
}

/** Ruling F3's ad-side spelling: the kit's technical ramp namespace. */
const RAMP_PREFIX = "palette.";

/**
 * One brand-kit detail payload → the ad lane's colour vocabulary, or `null`
 * when the kit defines no colours at all (no kit attached, a fetch that
 * failed, a kit with an empty catalog). `null` is the honest "this lane has no
 * brand vocabulary": the picker then shows an empty Theme tab
 * (`resolveInspectorThemeColors`; no fixture palette exists), and every token
 * WRITE refuses, because a label validated against nothing is not a token.
 */
export function buildScenePalette(
  kit: BrandKitDetailPayload | null | undefined,
): ScenePalette | null {
  const colors = buildTokenColorMap(kit);
  if (Object.keys(colors).length === 0) {
    return null;
  }
  const options: ScenePaletteOption[] = [];
  // Iterated over the KIT's catalog rather than the resolved map, so the order
  // is the kit's and the aliases folded into `colors` are not offered.
  for (const name of Object.keys(kit?.tokens?.colors ?? {})) {
    if (name.startsWith(RAMP_PREFIX)) continue;
    const value = colors[name];
    // A token the parser could not resolve (a broken alias chain) has no
    // colour to paint, and an unpaintable swatch is worse than no swatch —
    // `buildThemeColorOptions`'s own rule, kept here.
    if (!value) continue;
    options.push({ label: name, token: name, value });
  }
  return { colors, options };
}

/**
 * R3b: one swatch value → the colour the DOCUMENT actually has, or `null`.
 *
 * Only a brand TOKEN resolves. A hex, the `none` sentinel and anything else
 * name no token and yield nothing — callers decide what to do with that, which
 * is what keeps this function from ever fabricating a colour.
 *
 * `$`-TOLERANT, because both spellings are real: the kit's keys are bare
 * (`text.inverse`) while a stored paint may carry the author-facing sugar (the
 * seeded ad's headline is filled with `$text.inverse`). `resolveTokenColor` is
 * the engine's own strip-and-look-up and is not re-implemented here.
 */
export function scenePaletteColor(
  palette: ScenePalette | null | undefined,
  value: string,
): string | null {
  if (!palette || value === "") {
    return null;
  }
  return resolveTokenColor(palette.colors, value);
}

/**
 * R3: the token an `onTokenChange` LABEL names, or `null`.
 *
 * `ColorControl` reports the label of the row that was clicked, so the only
 * labels this can legitimately see are ones `options` supplied. Validating
 * against that list is therefore not defensive noise — it is what stops the
 * picker from writing phantom tokens: a label that is not in the kit's list
 * (`{kind:"token", token:"Primary"}`, say) is a binding no kit can resolve. Same
 * hazard the web lane's chip comment names ("never a fixture-palette popover
 * that would write phantom tokens"), refused here at the write gate instead.
 */
export function scenePaletteToken(
  palette: ScenePalette | null | undefined,
  label: string,
): string | null {
  if (!palette) {
    return null;
  }
  return palette.options.find((option) => option.label === label)?.token ?? null;
}

/**
 * R3b: one swatch value as a value a HEX-shaped consumer can use — a hex
 * verbatim, a brand token resolved through the palette, and `null` for
 * anything else (the `none` state, an unknown token, an absent kit).
 *
 * The two callers are the ones where a hex is STRUCTURALLY required and the
 * displayed value may be a token name: `scene-hydrate.ts`'s
 * `backgroundFillCommits` (which re-seeds a gradient's stops from the swatch)
 * and the same file's outgoing-stop read. `null` there means REFUSE the mode
 * switch — the null contract, not a substituted colour.
 *
 * ONE rule, applied to the value and then to the token's colour: whatever the
 * controls can already hold survives VERBATIM, casing included (it is the
 * string the panel is showing, and re-casing it would churn a value nobody
 * changed), and only a form they cannot hold is rewritten.
 */
export function paletteHex(
  palette: ScenePalette | null | undefined,
  value: string,
): string | null {
  const direct = usableHex(value);
  if (direct !== null) {
    return direct;
  }
  const resolved = scenePaletteColor(palette, value);
  return resolved === null ? null : usableHex(resolved);
}

/** A colour string the inspector's controls can hold: a six-digit hex exactly
 * as written, an eight-digit one truncated (a kit's oklch token with alpha < 1
 * resolves to one), and `null` for everything else. */
function usableHex(value: string): string | null {
  const normalized = normalizeHex(value);
  if (normalized === null) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.toLowerCase() === normalized ? trimmed : normalized;
}

/**
 * §1.6's custom-hex half: the ported hex normalization
 * (`ColorSwatchControl.tsx:256-261` `normalizeHexInput`) — lowercase,
 * `#rrggbb` accepted, `#rrggbbaa` truncated to six digits. ONE deliberate
 * divergence: upstream falls back to a silent `#000000` for anything else; we
 * return `null`, because a silent black is exactly the kind of guess the null
 * contract forbids.
 *
 * It lives HERE, beside the brand half of §1.6, because step 3 gave it a
 * second caller: `scene-hydrate.ts` needs the same "is this a usable colour?"
 * question that `scene-apply.ts` has always asked, and scene-apply already
 * imports scene-hydrate — importing it back would close a cycle. One §1.6
 * module both can read is the way out; the function itself is unchanged.
 */
export function normalizeHex(raw: string): string | null {
  const trimmed = raw.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(trimmed)) {
    return trimmed.toLowerCase();
  }
  if (/^#[0-9a-fA-F]{8}$/.test(trimmed)) {
    return trimmed.slice(0, 7).toLowerCase();
  }
  return null;
}
