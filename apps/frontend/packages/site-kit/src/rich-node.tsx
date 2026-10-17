// Drawing rich text (plan 2, spec §4.4) with React: one element for a stored rich string, the same on
// the server and in the browser that takes a live page over (richHtml is pure), so they never differ.
import type { ReactNode } from "react";
import { hasMarkup, richHtml } from "./rich";

/** A rich prop as page content. The editor's in-place widget (a ReactNode) passes through; a string
 * with markup becomes an inline span holding its published markup (the grammar is inline only, so the
 * span is valid inside any heading or paragraph); a plain string stays the string. */
export function rich(value: unknown, href: (value: string) => string): ReactNode {
  if (typeof value !== "string") return value as ReactNode;
  if (!hasMarkup(value)) return value;
  return <span data-clue-rich="" dangerouslySetInnerHTML={{ __html: richHtml(value, href) }} />;
}

/** A link that opens in a new tab: its attributes (none when it does not). */
export const newTabAttrs = (newTab: unknown) => (newTab === true ? { target: "_blank", rel: "noopener" } : {});
