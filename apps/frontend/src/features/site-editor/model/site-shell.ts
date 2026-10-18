// The site element inspector's Header group (plan 6, rulings R10 and R12): the header stays at the
// top while the page scrolls, and/or sits over the first section. Both are facts on the header's own
// box (`_edits.root`), saved, undone and published like any other change.
import { EDITS_PROP, ROOT_KEY, editsOf, withStyleOverride } from "@clue/site-kit/edits";
import { canonicalJson, componentProps, withComponentProps } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SiteDocument } from "@clue/site-kit/site-document";

export type HeaderPlacement = { sticky: boolean; overlay: boolean };

/** The header's placement, when the header itself is selected (not one of its elements); null otherwise. */
export function headerPlacementState(
  site: SiteDocument | null,
  selection: { target: string; componentId: string; element: unknown } | null,
): HeaderPlacement | null {
  if (!site || !selection || selection.target !== SHELL_TARGET || selection.componentId !== "header" || selection.element) return null;
  const props = componentProps(site, SHELL_TARGET, "header");
  if (!props) return null;
  const root = editsOf(props)[ROOT_KEY];
  return { sticky: root?.sticky === true, overlay: root?.overlay === true };
}

/** Sticky or overlay turned on or off: written to, or removed from, the header's `_edits.root` (an
 * entry left empty goes with it). Null when nothing changes. */
export function commitHeaderPlacement(
  site: SiteDocument,
  which: "sticky" | "overlay",
  on: boolean,
): { props: Record<string, unknown>; site: SiteDocument } | null {
  const props = componentProps(site, SHELL_TARGET, "header");
  if (!props) return null;
  const edits = editsOf(props);
  const updated = withStyleOverride(edits, ROOT_KEY, { ...edits[ROOT_KEY], [which]: on ? true : undefined });
  const next: Record<string, unknown> = { ...props };
  if (Object.keys(updated).length) next[EDITS_PROP] = updated;
  else delete next[EDITS_PROP];
  if (canonicalJson(next) === canonicalJson(props)) return null;
  const edited = withComponentProps(site, SHELL_TARGET, "header", next);
  const nextProps = componentProps(edited, SHELL_TARGET, "header");
  return nextProps ? { props: nextProps, site: edited } : null;
}

/** Founder 2026-10-19: the header and footer are treated like every other part of the page. A whole
 * copied section, the whole header and the whole footer show nothing of their own when selected (only
 * Layers, plus the header's own settings above): every part is edited by clicking it. Our own sections
 * keep their section-level panel. */
export function showsSectionPanel(selection: { target: string; componentType: string } | null): boolean {
  if (!selection) return false;
  return selection.target !== SHELL_TARGET && selection.componentType !== "ClonedSection";
}

type AccountLogoSelection = {
  target: string;
  componentId: string;
  element: { key?: string; imageSource?: { kind: string; slot?: string; uses?: number } | null } | null;
};

const ACCOUNT_LOGO_SLOT = "account_logo";
const ACCOUNT_SHOWN_SLOT = "account_shown";

function isAccountLogo(selection: AccountLogoSelection | null): selection is AccountLogoSelection {
  const source = selection?.element?.imageSource;
  return (
    !!selection &&
    selection.target === SHELL_TARGET &&
    selection.componentId === "header" &&
    source?.kind === "slot" &&
    source.slot === ACCOUNT_LOGO_SLOT
  );
}

/** A header template's account logo is hidden through the template's own `account_shown` slot, so the
 * logo and the thin line before it hide together. Null for any other selection. */
export function accountShownState(
  site: SiteDocument | null,
  selection: AccountLogoSelection | null,
): { hidden: boolean; part: "header" } | null {
  if (!site || !isAccountLogo(selection)) return null;
  const props = componentProps(site, SHELL_TARGET, "header");
  if (!props) return null;
  const slots = (props.slots ?? {}) as Record<string, unknown>;
  return { hidden: slots[ACCOUNT_SHOWN_SLOT] === false, part: "header" };
}

/** Hiding writes `account_shown: false`; showing removes it (the template's fallback shows it). Null
 * when nothing changes or the selection is not the account logo. */
export function commitAccountShown(
  site: SiteDocument,
  selection: AccountLogoSelection,
  hidden: boolean,
): { props: Record<string, unknown>; site: SiteDocument } | null {
  if (!isAccountLogo(selection)) return null;
  const props = componentProps(site, SHELL_TARGET, "header");
  if (!props) return null;
  const slots: Record<string, unknown> = { ...((props.slots ?? {}) as Record<string, unknown>) };
  if (hidden) slots[ACCOUNT_SHOWN_SLOT] = false;
  else delete slots[ACCOUNT_SHOWN_SLOT];
  const next = { ...props, slots };
  if (canonicalJson(next) === canonicalJson(props)) return null;
  const edited = withComponentProps(site, SHELL_TARGET, "header", next);
  const nextProps = componentProps(edited, SHELL_TARGET, "header");
  return nextProps ? { props: nextProps, site: edited } : null;
}
