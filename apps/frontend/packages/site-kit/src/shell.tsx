// The site shell: one campaign header and one footer, stored once per site and rendered around every
// page. "Prepared for <account>" sits beside the seller's logo, not under it. Every value is the
// kit's (theme.ts); the logo heights are site-kit's named fallbacks (the kit records logos, not the
// size a header shows them at).
import type { BrandData } from "./brand";
import { Fragment, type ReactNode } from "react";
import { SHELL_SCOPE, editsCss, editsOf, orderOf, type Edits } from "./edits";
import { newTabAttrs, rich } from "./rich-node";
import { Button } from "./sections";

export type HeaderProps = {
  preparedFor: string;
  accountLogo: string;
  ctaLabel: string;
  ctaHref: string;
  ctaNewTab?: boolean;
  /** A button style of the brand's (brand.md, Buttons); empty is the standard button. */
  ctaLook?: string;
  /** Links to the site's other pages; shown on wider screens beside the button. */
  nav?: { label: string; href: string; newTab?: boolean }[];
  /** Manual styling of the header's elements (edits.ts). */
  _edits?: Edits;
};
export type FooterProps = {
  legal: string;
  privacyHref: string;
  privacyNewTab?: boolean;
  termsHref: string;
  termsNewTab?: boolean;
  _edits?: Edits;
};
export type ShellData = { header: HeaderProps; footer: FooterProps };

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

/** The shell's manual styling, drawn as the first child of its header or footer: they are not page
 * sections, so they scope their own edits (and stay the brand root's direct children). */
function ShellEdits({ brand, scope, props }: { brand: BrandData; scope: string; props: Record<string, unknown> }) {
  const css = editsCss(scope, editsOf(props), brand);
  return css ? <style data-clue-edits="" dangerouslySetInnerHTML={{ __html: css }} /> : null;
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

export function SiteHeader({ brand, header, href }: { brand: BrandData; header: HeaderProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  const order = orderOf(editsOf(header));
  return (
    <header data-clue-section={SHELL_SCOPE.header} data-clue-el="root" className="brand-rule-b bg-surface-page text-on-surface-page">
      <ShellEdits brand={brand} scope={SHELL_SCOPE.header} props={header} />
      <div className="brand-content flex items-center justify-between gap-stack-default px-page-margin py-stack-tight" data-clue-el="root.inner">
        <div className="flex min-w-0 items-center gap-stack-tight" data-clue-el="brand">
          {inOrder(
            [
              // eslint-disable-next-line @next/next/no-img-element
              ["logo", logo ? <img key="logo" src={logo} alt="" className="brand-logo-header w-auto shrink-0" data-clue-el="logo" /> : null],
              ["divider", <span key="divider" aria-hidden className="brand-rule-v shrink-0" data-clue-el="divider" />],
              [
                "accountLogo",
                header.accountLogo ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key="accountLogo" src={header.accountLogo} alt="" className="brand-logo-header w-auto shrink-0" data-clue-el="accountLogo" />
                ) : null,
              ],
              [
                "prepared",
                <span key="prepared" className="min-w-0 truncate font-body text-body text-ink-secondary" data-clue-el="prepared">
                  <span className="hidden sm:inline">Prepared for </span>
                  {/* The account's name is the styleable text: it carries its own colour, so a style set on
                      the line around it would not reach it. */}
                  <span className="text-ink-primary" data-clue-el="preparedFor">{header.preparedFor}</span>
                </span>,
              ],
            ],
            order.brand,
          )}
        </div>
        <div className="flex shrink-0 items-center gap-stack-default" data-clue-el="actions">
          {inOrder(
            [
              [
                "nav",
                header.nav?.length ? (
                  <nav key="nav" className="hidden items-center gap-stack-default md:flex" data-clue-el="nav">
                    {header.nav.map((item, index) => (
                      <a key={item.href + item.label} href={href(item.href)} {...newTabAttrs(item.newTab)} className="brand-navlink" data-clue-el={`nav.${index}`}>
                        {item.label}
                      </a>
                    ))}
                  </nav>
                ) : null,
              ],
              [
                "ctaArea",
                // On phones the hero carries the same action, so the account name gets the room.
                <span key="ctaArea" className="hidden shrink-0 sm:inline-flex" data-clue-el="ctaArea">
                  <Button brand={brand} label={rich(header.ctaLabel, href)} href={href(header.ctaHref)} surface="page" look={header.ctaLook} el="cta" newTab={header.ctaNewTab} />
                </span>,
              ],
            ],
            order.actions,
          )}
        </div>
      </div>
    </header>
  );
}

export function SiteFooter({ brand, footer, href }: { brand: BrandData; footer: FooterProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  const order = orderOf(editsOf(footer));
  return (
    <footer data-clue-section={SHELL_SCOPE.footer} data-clue-el="root" className="brand-rule-t bg-surface-page text-on-surface-page">
      <ShellEdits brand={brand} scope={SHELL_SCOPE.footer} props={footer} />
      <div className="brand-content flex flex-col gap-stack-default px-page-margin py-stack-loose md:flex-row md:items-center md:justify-between" data-clue-el="root.inner">
        {inOrder(
          [
            // eslint-disable-next-line @next/next/no-img-element
            ["logo", logo ? <img key="logo" src={logo} alt="" className="brand-logo-footer w-auto self-start" data-clue-el="logo" /> : null],
            ["legal", <p key="legal" className="font-caption text-caption text-ink-muted" data-clue-el="legal">{footer.legal}</p>],
            [
              "links",
              <div key="links" className="flex gap-stack-default font-caption text-caption" data-clue-el="links">
                {inOrder(
                  [
                    ["privacy", footer.privacyHref ? <a key="privacy" href={href(footer.privacyHref)} {...newTabAttrs(footer.privacyNewTab)} className="brand-link" data-clue-el="privacy">Privacy policy</a> : null],
                    ["terms", footer.termsHref ? <a key="terms" href={href(footer.termsHref)} {...newTabAttrs(footer.termsNewTab)} className="brand-link" data-clue-el="terms">Terms</a> : null],
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
