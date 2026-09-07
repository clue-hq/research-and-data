"use client";

import { createContext, useContext } from "react";
import {
  scenePaletteColor,
  type ScenePalette,
} from "@/features/design-editor/adapter/scene-palette";
import type { ThemeColorOption } from "@/features/design-editor/adapter/theme-options";

/**
 * AD4.B step 3: the §1.6 colour machinery for the WHOLE ad inspector panel,
 * moved here out of `image-inspector.tsx` unchanged.
 *
 * It moved for one reason: `ad-dummy-inspectors.tsx` needs it too (its Shape
 * Fill and Stroke Colour rows are the same row), and it cannot import from
 * `image-inspector.tsx` — the import already runs the other way
 * (image-inspector → ad-dummy-inspectors), so the reverse would be a cycle.
 * The same reason `AdLayersBinding` and `AdHydrationBinding` live in the dummy
 * file rather than where they were written; this time the shared thing is a
 * hook, so a third neutral module is the home instead.
 *
 * A PURE MOVE. Every call site keeps its exact behaviour — the provider still
 * wraps the whole panel from `image-inspector.tsx`, so the four dummy schemas
 * inherit the palette through the context with no new props.
 */

/**
 * AD4.0 step 3 (§1.6): the document's brand palette for every ColorControl in
 * the ad inspector panel, carried as data — the seam rule, presentation never
 * fetches.
 *
 * A CONTEXT rather than a prop drilled through each schema, copying the
 * website lane's `ThemeColorsContext` (`web-inspector.tsx`) for the same
 * reason it exists there: the four dummy schemas inherit the feed without the
 * panel threading it. `null` — the chats route before a document loads, a
 * document with no attached kit, a kit fetch that failed — leaves every picker
 * on the dummy's own palette, unchanged.
 */
export const ScenePaletteContext = createContext<ScenePalette | null>(null);

/** The palette itself, for the rows that must RESOLVE a token (§1.6/R3b). */
export function useScenePalette() {
  return useContext(ScenePaletteContext);
}

/**
 * What the pickers are OFFERED, or `undefined` when this document has no brand
 * swatches to offer — which is also the signal that no token write may fire.
 *
 * The two are one question deliberately: with no options, `ColorControl`
 * shows an empty Theme tab, so no pick can name a token this document lacks;
 * the handler is still gated on this value so a stale label can never write
 * `{kind:"token", token:"Primary"}` — a binding nothing can resolve. So callers gate the token handler on this exact value,
 * and `scene-apply.ts` refuses the label a second time at the write.
 */
export function useScenePaletteOptions() {
  const palette = useScenePalette();
  return palette && palette.options.length > 0 ? palette.options : undefined;
}

/**
 * §1.6: ONE colour row — what its swatch is showing, and the two handlers its
 * two halves commit through. Every ad colour control goes through it, so the
 * brand and custom paths cannot drift apart five times over.
 *
 * R3b: `color` RESOLVES that value through the palette, because a token name is
 * not a CSS colour — the chip painted nothing, the Custom tab's picker opened
 * on black, and the picker could not mark the bound swatch as pressed. The
 * name still stands when the palette cannot resolve it (no kit attached, an
 * off-catalog token), which is step 2's truthful display, unchanged.
 */
export function useAdColorRow({
  hydratedValue,
  onHex,
  onToken,
  paletteOptions,
}: {
  hydratedValue: string;
  onHex: (hex: string) => void;
  onToken: (label: string) => void;
  paletteOptions: readonly ThemeColorOption[] | undefined;
}) {
  const palette = useScenePalette();
  // AD4.R: the row shows the DOCUMENT's value — a token name or a colour —
  // which under live hydration is current in the same batch as the write it
  // dispatched (a brand pick surfaces as the token's name, a detaching hex as
  // the hex, a refused write as the unmoved old value). The 'shown' draft this
  // hook carried was the mount-seeded model's patch for exactly that gap.
  const value = hydratedValue;
  return {
    color: scenePaletteColor(palette, value) ?? value,
    onColorChange: onHex,
    // Absent options mean the picker is showing the DUMMY's fixture palette,
    // whose labels name no token this document has — so no token handler is
    // offered at all (under A23 that tab is empty, so there is nothing to pick
    // either), and the Custom tab commits its hex as it always has.
    onTokenChange: paletteOptions && onToken,
    value,
  };
}
