import type {
  RichTextCommand,
  RichTextFormatValue,
  RichTextSelectionState,
  WebNodeRect,
} from "../engine/webBridge";
import type { WebTheme } from "../engine/webDocuments";
import { richTextHrefError } from "../engine/webRichText";

/**
 * W4.8a: the pure decisions behind the ported rich-text toolbar
 * (`web-rich-text-toolbar.tsx`) — the render gate, the class-facet read, the
 * theme-token list, the fixed-position math, and the validated link submit.
 *
 * Logic-preserving extraction from the source component
 * (`subsystems/clue-design/apps/editor/src/components/web/WebRichTextToolbar.tsx`
 * :48-69, :141-160, :183-230, :308-321): the source keeps these inline because
 * its suite renders React. This repo has no React renderer — the runner is
 * `tsx --test` (node:test) — so the decisions live here, where they are
 * testable, and the component holds only the DOM/event work that has to touch
 * a real tree. Nothing else changed: same constants, same branch order, same
 * outputs.
 */

/** Source `EDGE_GAP` — minimum gap to any viewport edge. */
export const EDGE_GAP = 12;
/** Source `RANGE_GAP` — gap between the selected range and the toolbar. */
export const RANGE_GAP = 10;

export interface ToolbarPosition {
  left: number;
  top: number;
  placement: "above" | "below";
}

/** The iframe's bounding box in parent-viewport coordinates. */
export interface ToolbarFrameRect {
  top: number;
  left: number;
  right: number;
  bottom: number;
}

export interface ToolbarSize {
  width: number;
  height: number;
}

/**
 * Source `:189-192` — the toolbar shows for a structured (body/small)
 * selection, for any live range carrying text, or for a caret parked inside an
 * existing link (so that link stays editable/removable without reselecting).
 */
export function richTextToolbarValidContext(
  selection: RichTextSelectionState,
): boolean {
  return (
    selection.structured ||
    (!selection.collapsed && selection.selectedText.length > 0) ||
    (selection.collapsed && selection.link.state === "on")
  );
}

/**
 * Source `:51-69` — read one class facet (`text-` / `bg-`) off the selection's
 * common/mixed class sets: exactly one common token and nothing mixed reads as
 * `on`; more than one common token, or any mixed token, reads as `mixed`;
 * otherwise `off`.
 */
export function classFacetValue(
  state: RichTextSelectionState,
  prefix: "text-" | "bg-",
  tokenNames: string[],
): { value: string | null; state: RichTextFormatValue } {
  const matchingCommon = tokenNames.filter((token) =>
    state.commonClasses.includes(`${prefix}${token}`),
  );
  const hasMixed = tokenNames.some((token) =>
    state.mixedClasses.includes(`${prefix}${token}`),
  );
  if (matchingCommon.length === 1 && !hasMixed) {
    return { value: matchingCommon[0], state: "on" };
  }
  if (matchingCommon.length > 1 || hasMixed) {
    return { value: matchingCommon[0] ?? null, state: "mixed" };
  }
  return { value: null, state: "off" };
}

/**
 * Source `:183-186` — the ColorPanels' token list, name-sorted.
 *
 * One addition, founder ruling F3 (2026-08-18): the technical `palette-*` ramp
 * tokens are hidden, exactly as the W4.0 inspector mapper
 * (`adapter/theme-options.ts::buildThemeColorOptions`) hides them. F3 says
 * every color-consuming surface inherits it, and two color surfaces over the
 * same theme must not disagree about which tokens are offered.
 *
 * Display only — see {@link toolbarKnownTokenNames} for why the command's
 * token list is a different, unfiltered one.
 */
export function toolbarThemeTokens(
  theme: WebTheme | null | undefined,
): [string, string][] {
  return Object.entries(theme?.tokens ?? {})
    .filter(([name]) => !name.toLowerCase().startsWith("palette-"))
    .sort(([left], [right]) => left.localeCompare(right));
}

/**
 * Every token name the theme defines, ramps INCLUDED — the `knownTokens` a
 * `set_class_facet` command carries.
 *
 * This deliberately does NOT inherit F3's filter, because `knownTokens` is not
 * a display list: the runtime uses it both as the allowlist for the token
 * being applied and as the set of `${prefix}${token}` classes to STRIP from
 * the run first (`iframe/webRichTextRuntime.ts:1131-1147`). Hiding the ramps
 * here would leave an agent-authored `text-palette-primary-500` in place
 * beside the newly applied `text-accent` — two conflicting color classes on
 * one text run, resolved by whatever the stylesheet order happens to be. F3
 * governs what the user is OFFERED, not what a write is allowed to clean up.
 */
export function toolbarKnownTokenNames(
  theme: WebTheme | null | undefined,
): string[] {
  return Object.keys(theme?.tokens ?? {}).sort((left, right) =>
    left.localeCompare(right),
  );
}

/**
 * Source `:194-230` — the fixed-position math, with the DOM reads (the iframe
 * rect, the toolbar rect, `window.inner*`) lifted into parameters.
 *
 * Returns `null` when the range has scrolled out of the frame — the source's
 * "hidden until positioned" state, which keeps the toolbar from floating over
 * content it no longer points at.
 */
export function computeToolbarPosition({
  frame,
  range,
  toolbar,
  viewport,
}: {
  frame: ToolbarFrameRect;
  range: WebNodeRect;
  toolbar: ToolbarSize;
  viewport: ToolbarSize;
}): ToolbarPosition | null {
  const rangeTop = frame.top + range.top;
  const rangeBottom = frame.top + range.bottom;
  const rangeCenter = frame.left + range.left + range.width / 2;
  if (
    rangeBottom < frame.top ||
    rangeTop > frame.bottom ||
    rangeCenter < frame.left ||
    rangeCenter > frame.right
  ) {
    return null;
  }
  const left = Math.min(
    viewport.width - toolbar.width - EDGE_GAP,
    Math.max(EDGE_GAP, rangeCenter - toolbar.width / 2),
  );
  const above = rangeTop - toolbar.height - RANGE_GAP;
  const placement = above >= EDGE_GAP ? "above" : "below";
  const top =
    placement === "above"
      ? above
      : Math.min(
          viewport.height - toolbar.height - EDGE_GAP,
          rangeBottom + RANGE_GAP,
        );
  return { left, top: Math.max(EDGE_GAP, top), placement };
}

export type RichTextLinkSubmission =
  | { ok: false; error: string }
  | { ok: true; command: RichTextCommand };

/**
 * Source `:308-321` — the parent-side half of the two-layer href grammar: an
 * href that fails `richTextHrefError` never becomes a command (the inline
 * error is shown instead); a valid one becomes exactly one trimmed `set_link`.
 * The runtime re-validates with the same grammar before touching the document,
 * and the server's `set_rich_text` validation is canonical — this layer exists
 * so the user is told *why*, not so the check can be skipped downstream.
 */
export function richTextLinkSubmission(
  href: string,
  newTab: boolean,
): RichTextLinkSubmission {
  const error = richTextHrefError(href);
  if (error) return { ok: false, error };
  return { ok: true, command: { type: "set_link", href: href.trim(), newTab } };
}
