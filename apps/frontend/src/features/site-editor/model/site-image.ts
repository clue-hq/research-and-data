// The site element inspector's image panel (plan 5), as pure decisions over the app's own copy of the
// site: the image's alt text, read from and written to where it lives (ruling R2), and the prop path
// Replace writes the new file to (ruling R1). The session writes each change as one save.
import { AltTextSchema, cloneImageAt, type BrandData } from "@clue/site-kit";
import type { ElementSelection } from "@clue/site-kit/editor-protocol";
import { canonicalJson, componentProps, getAtPath, setAtPath, withComponentProps } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";

export const ALT_REFUSED = "Alt text is plain text of at most 300 characters, with no line breaks.";

type ImageSelection = {
  componentId: string;
  target: string;
  element: Pick<ElementSelection, "key" | "altSource" | "imageSource" | "image"> | null;
};

/** A copied image's captured alt text (what the seller's page says), or "" when unknown. */
function capturedAlt(props: Record<string, unknown>, key: string, brand: Pick<BrandData, "clones"> | null): string {
  const clone = brand?.clones[String(props.fragmentId ?? "")];
  return clone ? (cloneImageAt(clone, key)?.alt ?? "") : "";
}

/** The image's alt text as stored: its prop, a copied section's `alts` entry, or (no entry) the copied
 * image's own. Null when the marketer cannot change it (the agent's, a video's, an icon's). */
export function imageAltOf(site: SiteDocument | null, selection: ImageSelection | null, brand: Pick<BrandData, "clones"> | null): string | null {
  const source = selection?.element?.altSource;
  const props = site && selection && source ? componentProps(site, selection.target, selection.componentId) : null;
  if (!source || source.kind === "fixed" || !props) return null;
  if (source.kind === "prop") {
    const stored = getAtPath(props, source.prop);
    return typeof stored === "string" ? stored : "";
  }
  const alts = (props.alts as Record<string, string> | undefined) ?? {};
  return alts[source.key] ?? capturedAlt(props, source.key, brand);
}

/** One alt text typed in the panel → the edited site and the section's whole new props. Trimmed; an
 * empty text removes the prop; a copied image's text equal to its captured alt drops its `alts` entry
 * (an empty `alts` goes too). Refused when it is not plain text of at most 300 characters; null when
 * nothing changes or the marketer cannot change it. */
export function commitImageAlt(
  site: SiteDocument,
  selection: ImageSelection,
  text: string,
  brand: Pick<BrandData, "clones"> | null,
): { props: Record<string, unknown>; site: SiteDocument } | { refused: string } | null {
  const source = selection.element?.altSource;
  const props = componentProps(site, selection.target, selection.componentId);
  if (!source || source.kind === "fixed" || !props) return null;
  const alt = text.trim();
  if (!AltTextSchema.safeParse(alt).success) return { refused: ALT_REFUSED };
  let next: Record<string, unknown>;
  if (source.kind === "prop") {
    next = alt ? setAtPath(props, source.prop, alt) : { ...props };
    if (!alt) delete next[source.prop];
  } else {
    const others = Object.fromEntries(Object.entries((props.alts as Record<string, string> | undefined) ?? {}).filter(([key]) => key !== source.key));
    const alts = alt === capturedAlt(props, source.key, brand) ? others : { ...others, [source.key]: alt };
    next = { ...props, alts };
    if (!Object.keys(alts).length) delete next.alts;
  }
  if (canonicalJson(next) === canonicalJson(props)) return null;
  const edited = withComponentProps(site, selection.target, selection.componentId, next);
  const nextProps = componentProps(edited, selection.target, selection.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}

/** The prop path Replace writes the new file to (the dock's image field), and how many images on the
 * section it draws; null when the marketer cannot replace this image. */
export function imageReplaceTarget(selection: ImageSelection | null): { prop: string; uses: number } | null {
  const source = selection?.element?.imageSource;
  if (!source || source.kind === "fixed") return null;
  return source.kind === "prop" ? { prop: source.prop, uses: source.uses } : { prop: `slots.${source.slot}`, uses: source.uses };
}
