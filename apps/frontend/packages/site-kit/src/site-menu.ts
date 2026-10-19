// Plan 6 (ruling R8): the header's menu lists the site's own pages, filled when the page is drawn, so
// a page added later joins the menu without anyone rewriting the header. Each item is keyed by its page
// (`menu._home` for "/", `menu.<name>` otherwise; page names never start with "_"), so a label, a style
// or an order set on one item keeps pointing at that page when pages are added or removed. Links the
// agent keeps after the pages (`menuExtra`, the seller's own on a one-to-few site) are `menu._<n>`.

export type MenuPage = { route: string; key: string; label: string };
export type MenuItem = {
  key: string;
  label: string;
  href: string;
  newTab?: boolean;
  source: { kind: "page"; route: string } | { kind: "extra"; index: number };
};
export type MenuProps = {
  menuLabels?: Record<string, string>;
  menuExtra?: { label: string; href: string; newTab?: boolean }[];
};

/** What a drawn item is, on its element (data-clue-menu-source): its page or its extra link. */
export const menuSource = (item: MenuItem): string =>
  item.source.kind === "page" ? `page:${item.source.route}` : `extra:${item.source.index}`;

/** A page's item key: `menu._home` for "/", `menu.<name>` for "/<name>". */
export const menuKey = (route: string): string => (route === "/" ? "menu._home" : `menu.${route.slice(1)}`);

/** The page's name in `menuLabels`: `_home` or the page's name. */
const labelKey = (route: string): string => menuKey(route).slice("menu.".length);

/** "Overview" for "/", else the page name with dashes as spaces and a capital first letter. */
function defaultLabel(route: string): string {
  if (route === "/") return "Overview";
  const words = route.slice(1).replace(/-/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The site's pages for its menu: "/" first, then the others alphabetically; none for a one-page site. */
export function siteMenuPages(pages: Record<string, unknown>): MenuPage[] {
  const routes = Object.keys(pages);
  if (routes.length < 2) return [];
  const ordered = [...(routes.includes("/") ? ["/"] : []), ...routes.filter((route) => route !== "/").sort()];
  return ordered.map((route) => ({ route, key: menuKey(route), label: defaultLabel(route) }));
}

/** The items a header draws: the pages (renamed by `menuLabels`), then `menuExtra`. Hrefs are as
 * written; the caller resolves them under the site's base path. */
export function menuItems(pages: readonly MenuPage[], props: MenuProps): MenuItem[] {
  const labels = props.menuLabels ?? {};
  return [
    ...pages.map((page) => ({
      key: page.key,
      label: labels[labelKey(page.route)] || page.label,
      href: page.route,
      source: { kind: "page" as const, route: page.route },
    })),
    ...(props.menuExtra ?? []).map((extra, index) => ({
      key: `menu._${index}`,
      label: extra.label,
      href: extra.href,
      ...(extra.newTab ? { newTab: true } : {}),
      source: { kind: "extra" as const, index },
    })),
  ];
}
