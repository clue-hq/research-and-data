import { EDITS_PROP, editsOf, withStyleOverride, type StyleOverride } from "@clue/site-kit/edits";
import type { ElementSelection, ElementSummary, FieldDescription } from "@clue/site-kit/editor-protocol";
import { canonicalJson, componentProps, getAtPath, pageFor, setAtPath, withComponentProps } from "@clue/site-kit/editor-site";
import { richText, styleAt, styleWords } from "@clue/site-kit/rich";
import type { SiteDocument } from "@clue/site-kit/site-document";
import type { LinkChange, LinkRowState } from "@/features/chat-shell/components/site-link-row.logic";
import type { SiteLayerRow } from "./site-layers";

/** What the frame said is selected (Contract 6 `selected`), stamped with its document. The values
 * are never taken from the message: the dock reads them from the app's own copy of the site. */
export interface SiteSelection {
  componentId: string;
  componentType: string;
  documentId: string;
  fields: FieldDescription[];
  target: string;
  /** The selected text element of the section (site element inspector), or null for the section. */
  element: ElementSelection | null;
  /** The section's text elements, for Layers. */
  elements: ElementSummary[];
}

/** Everything the dock draws, as data and callbacks (presentation never reaches the session). */
export interface SiteInspectorBinding {
  disabled: boolean;
  error: string | null;
  fields: readonly FieldDescription[] | null;
  layers: readonly SiteLayerRow[];
  note: string | null;
  onCommit: (name: string, value: unknown) => void;
  onSelectLayer: (row: SiteLayerRow) => void;
  /** Remount identity: a new selection starts with fresh drafts and sections. */
  selectionKey: string;
  title: string;
  values: Record<string, unknown> | null;
  /** The selected text element, as the frame described it (its computed look), or null. */
  element: ElementSelection | null;
  /** That element's manual styling, read from the app's own copy of the site (never the message). */
  elementOverride: StyleOverride | null;
  /** One committed style change: the element's whole new override (one save, one undo step). */
  onStyleCommit: (key: string, override: StyleOverride) => void;
  /** The brand's colours for the colour picker's Theme tab: label = token, value = its CSS colour. */
  palette: readonly { label: string; value: string }[];
  /** The brand's font families with their weights, then the font library's (plan 2). */
  fonts: readonly { family: string; weights: number[] }[];
  /** Plan 2: the highlighted words' own look (their styled span's `_edits` entry), or null. */
  wordsOverride: StyleOverride | null;
  /** One style change on the highlighted words (their span and its look, one save). Returns a note
   * when it cannot be made (the text changed under them), else null. */
  onWordStyleCommit: (apply: (old: StyleOverride) => StyleOverride) => string | null;
  /** Why highlighted words cannot be styled on their own here (the panel then styles the whole
   * text), or null. */
  wordsUnavailable: string | null;
  /** Plan 2: the Link row for the selected text, its site's pages, and one link change (one save);
   * returns a note when the change cannot be made. */
  linkState: LinkRowState;
  pages: readonly { route: string; title: string }[];
  onLinkCommit: (change: LinkChange) => string | null;
}

/** One committed field value → the edited site and the component's whole new props. */
export function commitFieldEdit(
  site: SiteDocument,
  selection: { componentId: string; target: string },
  name: string,
  value: unknown,
): { props: Record<string, unknown>; site: SiteDocument } | null {
  const props = componentProps(site, selection.target, selection.componentId);
  if (!props) return null;
  const edited = withComponentProps(site, selection.target, selection.componentId, setAtPath(props, name, value));
  if (edited === site) return null;
  const nextProps = componentProps(edited, selection.target, selection.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}

/** One committed style → the edited site and the component's whole new props: the element's
 * override replaces its entry in `_edits` (an empty override removes the entry, an empty `_edits`
 * removes the prop). Null when nothing changes or the component is gone. */
export function commitStyleEdit(
  site: SiteDocument,
  selection: { componentId: string; target: string },
  key: string,
  override: StyleOverride,
): { props: Record<string, unknown>; site: SiteDocument } | null {
  const props = componentProps(site, selection.target, selection.componentId);
  if (!props) return null;
  const edits = withStyleOverride(editsOf(props), key, override);
  const next: Record<string, unknown> = { ...props };
  if (Object.keys(edits).length) next[EDITS_PROP] = edits;
  else delete next[EDITS_PROP];
  if (canonicalJson(next) === canonicalJson(props)) return null;
  const edited = withComponentProps(site, selection.target, selection.componentId, next);
  if (edited === site) return null;
  const nextProps = componentProps(edited, selection.target, selection.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}

/** What the panel needs of a selection to act on its highlighted words (plan 2). */
type WordsSelection = { componentId: string; target: string; element: ElementSelection | null };

/** The element's stored rich text: its prop, or (a clone slot never set) its captured words. */
function storedRich(props: Record<string, unknown>, element: ElementSelection): string | null {
  if (!element.rich) return null;
  const stored = getAtPath(props, element.rich.prop);
  return typeof stored === "string" ? stored : (element.rich.fallback ?? null);
}

export const STALE_WORDS = "The text changed. Highlight the words again.";

/** Why words highlighted in this element cannot be styled on their own (ruling R4), or null. */
export function wordsUnavailableReason(selection: { target: string; componentType: string; element: ElementSelection | null } | null): string | null {
  const element = selection?.element;
  if (!selection || !element?.words || element.rich) return null;
  if (selection.target === "shell") return "Words in the header and footer are styled as a whole for now: changes here apply to the whole text.";
  if (selection.componentType === "ClonedSection") {
    return "This text is copied from the seller's page and has no slot, so it is styled as a whole: changes here apply to the whole text.";
  }
  return "This text is styled as a whole: changes here apply to the whole text.";
}

/** One style change on the highlighted words → the edited site and the component's whole new props:
 * the words' styled span in the element's text and its look in `_edits`, together (one save, one
 * undo step). `apply` turns each run's current look into its new one. A refusal when the stored text
 * no longer holds those words; null when nothing changes. */
export function commitWordStyle(
  site: SiteDocument,
  selection: WordsSelection,
  apply: (old: StyleOverride) => StyleOverride,
): { props: Record<string, unknown>; site: SiteDocument } | { refused: string } | null {
  const element = selection.element;
  const words = element?.words;
  const props = componentProps(site, selection.target, selection.componentId);
  if (!element?.rich || !words || !props) return null;
  const html = storedRich(props, element);
  if (html === null || richText(html).slice(words.start, words.end) !== words.text) return { refused: STALE_WORDS };
  const styled = styleWords(html, words.start, words.end, apply, editsOf(props), element.key);
  const next: Record<string, unknown> = setAtPath(props, element.rich.prop, styled.html);
  if (Object.keys(styled.edits).length) next[EDITS_PROP] = styled.edits;
  else delete next[EDITS_PROP];
  const unchanged = styled.html === html && canonicalJson(styled.edits) === canonicalJson(editsOf(props));
  if (unchanged) return null;
  const edited = withComponentProps(site, selection.target, selection.componentId, next);
  const nextProps = componentProps(edited, selection.target, selection.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}

/** The highlighted words' own look: the `_edits` entry of the styled span they all sit in, or null. */
export function wordsOverride(site: SiteDocument | null, selection: WordsSelection | null): StyleOverride | null {
  const element = selection?.element;
  if (!site || !element?.rich || !element.words || !selection) return null;
  const props = componentProps(site, selection.target, selection.componentId);
  const html = props ? storedRich(props, element) : null;
  if (!props || html === null) return null;
  if (richText(html).slice(element.words.start, element.words.end) !== element.words.text) return null;
  const key = styleAt(html, element.words.start, element.words.end);
  return key ? (editsOf(props)[key] ?? null) : null;
}

/** The colour picker's Theme tab: the brand's colours by token, without the technical `palette.*`
 * ramps (founder ruling F3, 2026-08-18, as in the web editor). The validator still accepts them. */
export function sitePalette<B>(
  brand: B,
  choices: (brand: B) => { token: string; value: string }[],
): { label: string; value: string }[] {
  return choices(brand)
    .filter((choice) => !choice.token.toLowerCase().startsWith("palette."))
    .map((choice) => ({ label: choice.token, value: choice.value }));
}

/** The selected element's manual styling in the site as it is now, or null. */
export function elementOverrideOf(
  site: SiteDocument | null,
  selection: { componentId: string; target: string; element: ElementSelection | null } | null,
): StyleOverride | null {
  if (!site || !selection?.element) return null;
  const props = componentProps(site, selection.target, selection.componentId);
  return props ? (editsOf(props)[selection.element.key] ?? null) : null;
}

export function siteInspectorTitle(site: SiteDocument | null, route: string, selectedRow: SiteLayerRow | undefined): string {
  if (selectedRow) return selectedRow.label;
  const title = site ? pageFor(site, route)?.root.props.title : undefined;
  return title && title.trim() ? title : route;
}
