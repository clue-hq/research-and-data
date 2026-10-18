// The site's header and footer (plan 6): the fallback templates, used when a kit has no header or
// footer template of its own, and every word in them is the marketer's. They are sections: the page
// draws them first and last inside their section scope (config.tsx), so their `_edits` are scoped by
// that box, not here. Every value is the kit's (theme.ts); the logo heights are site-kit's named
// fallbacks (the kit records logos, not the size a header shows them at).
import type { BrandData } from "./brand";
import { Fragment, type ReactNode } from "react";
import { editsOf, orderOf, type Edits } from "./edits";
import { newTabAttrs, rich } from "./rich-node";
import { Button } from "./sections";
import { menuSource, type MenuItem } from "./site-menu";

export type HeaderProps = {
  /** The line addressing the account (rich text without links): the agent writes it, never fixed words. */
  accountLine: string;
  accountLogo: string;
  ctaLabel: string;
  ctaHref: string;
  ctaNewTab?: boolean;
  /** A button style of the brand's (brand.md, Buttons); empty is the standard button. */
  ctaLook?: string;
  /** The seller's logo, replaced from the library; empty is the kit's. */
  logo?: string;
  /** Plan 5: the logos' alt texts (empty: decorative). */
  logoAlt?: string;
  accountLogoAlt?: string;
  /** Plan 6: the menu's labels by page and links after the pages (site-menu.ts). */
  menuLabels?: Record<string, string>;
  menuExtra?: { label: string; href: string; newTab?: boolean }[];
  /** Manual styling of the header's elements (edits.ts). */
  _edits?: Edits;
};
export type FooterProps = {
  legal: string;
  logo?: string;
  logoAlt?: string;
  /** The links' words; empty is "Privacy policy" / "Terms". */
  privacyLabel?: string;
  privacyHref: string;
  privacyNewTab?: boolean;
  termsLabel?: string;
  termsHref: string;
  termsNewTab?: boolean;
  _edits?: Edits;
};

type Logos = Record<string, { variants: { name: string; asset_id: string }[] }>;

export function sellerLogo(brand: BrandData, variant: "primary" | "reversed" = "primary"): string | null {
  const logos = (brand.kit as { assets?: { logos?: Logos } }).assets?.logos ?? {};
  const primary = logos.primary?.variants ?? [];
  const pick =
    (variant === "reversed" && primary.find((v) => v.name === "reversed")) ||
    primary.find((v) => v.name !== "reversed") ||
    logos.mark?.variants?.[0];
  return pick ? brand.assets[pick.asset_id]?.file ?? null : null;
}

/** Every file of the kit's logos, all variants (mark, primary, reversed…). kit.Image shows these whole. */
export function logoFiles(brand: BrandData): Set<string> {
  const logos = (brand.kit as { assets?: { logos?: Logos } }).assets?.logos ?? {};
  const files = new Set<string>();
  for (const logo of Object.values(logos)) {
    for (const variant of logo?.variants ?? []) {
      const file = brand.assets[variant.asset_id]?.file;
      if (file) files.add(file);
    }
  }
  return files;
}

/** A group's parts in the group's `order` (plan 4): the parts it names go into the places those parts
 * hold, in its order; a key no part has is ignored, and parts it does not name keep their places. */
function inOrder(parts: [key: string, node: ReactNode][], order: readonly string[] | undefined): ReactNode[] {
  const drawn = parts.filter(([, node]) => node !== null && node !== undefined && node !== false);
  if (!order?.length) return drawn.map(([key, node]) => <Fragment key={key}>{node}</Fragment>);
  const listed = drawn.filter(([key]) => order.includes(key)).sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));
  let next = 0;
  return drawn
    .map((part) => (order.includes(part[0]) ? listed[next++] : part))
    .map(([key, node]) => <Fragment key={key}>{node}</Fragment>);
}

export function SiteHeader({
  brand,
  header,
  href,
  menu = [],
}: {
  brand: BrandData;
  header: HeaderProps;
  href: (v: string) => string;
  /** The site's pages and extra links (site-menu.ts), hrefs already under the base path. */
  menu?: MenuItem[];
}) {
  const logo = header.logo || sellerLogo(brand);
  const order = orderOf(editsOf(header));
  return (
    <header data-clue-el="root" className="brand-rule-b bg-surface-page text-on-surface-page">
      <div className="brand-content flex items-center justify-between gap-stack-default px-page-margin py-stack-tight" data-clue-el="root.inner">
        {/* The two groups, in their order too (plan 4 review I2). */}
        {inOrder(
          [
            [
              "brand",
              <div key="brand" className="flex min-w-0 items-center gap-stack-tight" data-clue-el="brand">
                {inOrder(
                  [
                    // eslint-disable-next-line @next/next/no-img-element
                    ["logo", logo ? <img key="logo" src={logo} alt={header.logoAlt ?? ""} className="brand-logo-header w-auto shrink-0" data-clue-el="logo" /> : null],
                    ["divider", <span key="divider" aria-hidden className="brand-rule-v shrink-0" data-clue-el="divider" />],
                    [
                      "accountLogo",
                      header.accountLogo ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img key="accountLogo" src={header.accountLogo} alt={header.accountLogoAlt ?? ""} className="brand-logo-header w-auto shrink-0" data-clue-el="accountLogo" />
                      ) : null,
                    ],
                    [
                      "accountLine",
                      <span key="accountLine" className="min-w-0 truncate font-body text-body text-ink-primary" data-clue-el="accountLine">
                        {rich(header.accountLine, href)}
                      </span>,
                    ],
                  ],
                  order.brand,
                )}
              </div>,
            ],
            [
              "actions",
              <div key="actions" className="flex shrink-0 items-center gap-stack-default" data-clue-el="actions">
                {inOrder(
                  [
                    [
                      "menu",
                      // Plan 6 (ruling R8): the site's pages, then the agent's extra links; shown on wider
                      // screens beside the button (ruling R9).
                      menu.length ? (
                        <nav key="menu" className="hidden items-center gap-stack-default md:flex" data-clue-el="menu">
                          {inOrder(
                            menu.map((item) => [
                              item.key,
                              <a key={item.key} href={item.href} {...newTabAttrs(item.newTab)} className="brand-navlink" data-clue-el={item.key} data-clue-menu-label="" data-clue-menu-source={menuSource(item)}>
                                {item.label}
                              </a>,
                            ]),
                            order.menu,
                          )}
                        </nav>
                      ) : null,
                    ],
                    [
                      "ctaArea",
                      // On phones the hero carries the same action, so the account line gets the room.
                      <span key="ctaArea" className="hidden shrink-0 sm:inline-flex" data-clue-el="ctaArea">
                        <Button brand={brand} label={rich(header.ctaLabel, href)} href={href(header.ctaHref)} surface="page" look={header.ctaLook} el="cta" newTab={header.ctaNewTab} />
                      </span>,
                    ],
                  ],
                  order.actions,
                )}
              </div>,
            ],
          ],
          order["root.inner"],
        )}
      </div>
    </header>
  );
}

export function SiteFooter({ brand, footer, href }: { brand: BrandData; footer: FooterProps; href: (v: string) => string }) {
  const logo = footer.logo || sellerLogo(brand);
  const order = orderOf(editsOf(footer));
  return (
    <footer data-clue-el="root" className="brand-rule-t bg-surface-page text-on-surface-page">
      <div className="brand-content flex flex-col gap-stack-default px-page-margin py-stack-loose md:flex-row md:items-center md:justify-between" data-clue-el="root.inner">
        {inOrder(
          [
            // eslint-disable-next-line @next/next/no-img-element
            ["logo", logo ? <img key="logo" src={logo} alt={footer.logoAlt ?? ""} className="brand-logo-footer w-auto self-start" data-clue-el="logo" /> : null],
            ["legal", <p key="legal" className="font-caption text-caption text-ink-muted" data-clue-el="legal">{rich(footer.legal, href)}</p>],
            [
              "links",
              <div key="links" className="flex gap-stack-default font-caption text-caption" data-clue-el="links">
                {inOrder(
                  [
                    ["privacy", footer.privacyHref ? <a key="privacy" href={href(footer.privacyHref)} {...newTabAttrs(footer.privacyNewTab)} className="brand-link" data-clue-el="privacy">{rich(footer.privacyLabel || "Privacy policy", href)}</a> : null],
                    ["terms", footer.termsHref ? <a key="terms" href={href(footer.termsHref)} {...newTabAttrs(footer.termsNewTab)} className="brand-link" data-clue-el="terms">{rich(footer.termsLabel || "Terms", href)}</a> : null],
                  ],
                  order.links,
                )}
              </div>,
            ],
          ],
          order["root.inner"],
        )}
      </div>
    </footer>
  );
}
