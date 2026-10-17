// The site shell: one campaign header and one footer, stored once per site and rendered around every
// page. "Prepared for <account>" sits beside the seller's logo, not under it. Every value is the
// kit's (theme.ts); the logo heights are site-kit's named fallbacks (the kit records logos, not the
// size a header shows them at).
import type { BrandData } from "./brand";
import { SHELL_SCOPE, editsCss, editsOf, type Edits } from "./edits";
import { Button } from "./sections";

export type HeaderProps = {
  preparedFor: string;
  accountLogo: string;
  ctaLabel: string;
  ctaHref: string;
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

export function SiteHeader({ brand, header, href }: { brand: BrandData; header: HeaderProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  return (
    <header data-clue-section={SHELL_SCOPE.header} className="brand-rule-b bg-surface-page text-on-surface-page">
      <ShellEdits brand={brand} scope={SHELL_SCOPE.header} props={header} />
      <div className="brand-content flex items-center justify-between gap-stack-default px-page-margin py-stack-tight">
        <div className="flex min-w-0 items-center gap-stack-tight">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {logo ? <img src={logo} alt="" className="brand-logo-header w-auto shrink-0" /> : null}
          <span aria-hidden className="brand-rule-v shrink-0" />
          {header.accountLogo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={header.accountLogo} alt="" className="brand-logo-header w-auto shrink-0" />
          ) : null}
          <span className="min-w-0 truncate font-body text-body text-ink-secondary">
            <span className="hidden sm:inline">Prepared for </span>
            {/* The account's name is the styleable text: it carries its own colour, so a style set on
                the line around it would not reach it. */}
            <span className="text-ink-primary" data-clue-el="preparedFor">{header.preparedFor}</span>
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-stack-default">
          {header.nav?.length ? (
            <nav className="hidden items-center gap-stack-default md:flex">
              {header.nav.map((item, index) => (
                <a key={item.href + item.label} href={href(item.href)} className="brand-navlink" data-clue-el={`nav.${index}`}>
                  {item.label}
                </a>
              ))}
            </nav>
          ) : null}
          {/* On phones the hero carries the same action, so the account name gets the room. */}
          <span className="hidden shrink-0 sm:inline-flex">
            <Button brand={brand} label={header.ctaLabel} href={href(header.ctaHref)} surface="page" look={header.ctaLook} />
          </span>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter({ brand, footer, href }: { brand: BrandData; footer: FooterProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  return (
    <footer data-clue-section={SHELL_SCOPE.footer} className="brand-rule-t bg-surface-page text-on-surface-page">
      <ShellEdits brand={brand} scope={SHELL_SCOPE.footer} props={footer} />
      <div className="brand-content flex flex-col gap-stack-default px-page-margin py-stack-loose md:flex-row md:items-center md:justify-between">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {logo ? <img src={logo} alt="" className="brand-logo-footer w-auto self-start" /> : null}
        <p className="font-caption text-caption text-ink-muted" data-clue-el="legal">{footer.legal}</p>
        <div className="flex gap-stack-default font-caption text-caption">
          {footer.privacyHref ? <a href={href(footer.privacyHref)} className="brand-link" data-clue-el="privacy">Privacy policy</a> : null}
          {footer.termsHref ? <a href={href(footer.termsHref)} className="brand-link" data-clue-el="terms">Terms</a> : null}
        </div>
      </div>
    </footer>
  );
}
