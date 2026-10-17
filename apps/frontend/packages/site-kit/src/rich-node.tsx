// Drawing rich text (plan 2, spec §4.4) with React: one element for a stored rich string, the same on
// the server and in the browser that takes a live page over (richHtml is pure), so they never differ.
import { isValidElement, type ReactNode } from "react";
import { hasMarkup, richHtml, type RichOptions } from "./rich";

/** A rich prop as page content. The editor's in-place widget (a ReactNode) passes through; a string
 * with markup becomes an inline span holding its published markup (the grammar is inline only, so the
 * span is valid inside any heading or paragraph); a plain string stays the string. */
export function rich(value: unknown, href: (value: string) => string): ReactNode {
  if (typeof value !== "string") return value as ReactNode;
  if (!hasMarkup(value)) return value;
  return <RichText value={value} href={href} />;
}

/** A stored rich string as an inline span of its published markup; `links={false}` draws its words
 * without links (a button's words: a link inside a button's link is invalid HTML). */
export function RichText({ value, href, links }: { value: string; href: (value: string) => string; links?: boolean }) {
  return <span data-clue-rich="" dangerouslySetInnerHTML={{ __html: richHtml(value, href, { links }) }} />;
}

/** A button's words with any link dropped: a stored rich string drawn by `rich()` is redrawn link-free;
 * anything else (plain words, the editor's in-place field) passes through. */
export function withoutLinks(label: ReactNode): ReactNode {
  if (!isValidElement<{ value: string; href: (value: string) => string }>(label) || label.type !== RichText) return label;
  return <RichText value={label.props.value} href={label.props.href} links={false} />;
}

/** A link that opens in a new tab: its attributes (none when it does not). */
export const newTabAttrs = (newTab: unknown) => (newTab === true ? { target: "_blank", rel: "noopener" } : {});
