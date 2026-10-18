// Plan 6 (rulings R2, R3): the header and footer are drawn as the page's first and last sections, by
// every renderer alike (the editor's Puck data, the static render, a live page on both sides), so they
// get the same section machinery as the page's own sections. The editor's combined page is split back
// into the shell and the page when it saves.
import { ShellEntrySchema, type ShellEntry, type SiteDocument, type SitePage, type SiteShell } from "./site-document";

/** A header or footer entry: a section `{type, props}` whose id is its place. */
export function isShellEntry(value: unknown): value is ShellEntry {
  return ShellEntrySchema.safeParse(value).success;
}

const placed = (shell: SiteShell | null | undefined): shell is SiteShell =>
  !!shell &&
  isShellEntry(shell.header) &&
  isShellEntry(shell.footer) &&
  shell.header.props.id === "header" &&
  shell.footer.props.id === "footer";

/** The page with the header first and the footer last. The same page object when there is no shell or
 * it is not two well-formed entries (an old-shape shell draws nothing: ruling R1). */
export function pageWithShell(page: SitePage, shell: SiteShell | null | undefined): SitePage {
  if (!placed(shell)) return page;
  return { ...page, content: [shell.header, ...page.content, shell.footer] as SitePage["content"] };
}

/** The site after the editor reported its combined page for `route`: an item with id `header` at the
 * start and one with id `footer` at the end go to `site.shell`; everything else is the page. */
export function withEditedShellPage(site: SiteDocument, route: string, edited: SitePage): SiteDocument {
  let content = edited.content;
  const header = content[0]?.props.id === "header" ? content[0] : null;
  if (header) content = content.slice(1);
  const footer = content.at(-1)?.props.id === "footer" ? content.at(-1)! : null;
  if (footer) content = content.slice(0, -1);
  const shell =
    site.shell && header && footer ? { ...site.shell, header: header as ShellEntry, footer: footer as ShellEntry } : site.shell;
  return { ...site, shell, pages: { ...site.pages, [route]: { ...edited, content } } };
}
