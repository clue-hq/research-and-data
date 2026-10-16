// The site shell: one campaign header and one footer, stored once per site and rendered around every
// page. "Prepared for <account>" sits beside the seller's logo, not under it. Every value is the
// kit's (theme.ts); the logo heights are site-kit's named fallbacks (the kit records logos, not the
// size a header shows them at).
import type { BrandData } from "./brand";
import { Button } from "./sections";

export type HeaderProps = {
  preparedFor: string;
  accountLogo: string;
  ctaLabel: string;
  ctaHref: string;
  /** A button style of the brand's (brand.md, Buttons); empty is the standard button. */
  ctaLook?: string;
  /** Links to the site's other pages; shown on wider screens beside the button. */
  nav?: { label: string; href: string }[];
};
export type FooterProps = { legal: string; privacyHref: string; termsHref: string };
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

export function SiteHeader({ brand, header, href }: { brand: BrandData; header: HeaderProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  return (
    <header className="brand-rule-b bg-surface-page text-on-surface-page">
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
            <span className="text-ink-primary">{header.preparedFor}</span>
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-stack-default">
          {header.nav?.length ? (
            <nav className="hidden items-center gap-stack-default md:flex">
              {header.nav.map((item) => (
                <a key={item.href + item.label} href={href(item.href)} className="brand-navlink">
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
    <footer className="brand-rule-t bg-surface-page text-on-surface-page">
      <div className="brand-content flex flex-col gap-stack-default px-page-margin py-stack-loose md:flex-row md:items-center md:justify-between">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {logo ? <img src={logo} alt="" className="brand-logo-footer w-auto self-start" /> : null}
        <p className="font-caption text-caption text-ink-muted">{footer.legal}</p>
        <div className="flex gap-stack-default font-caption text-caption">
          {footer.privacyHref ? <a href={href(footer.privacyHref)} className="brand-link">Privacy policy</a> : null}
          {footer.termsHref ? <a href={href(footer.termsHref)} className="brand-link">Terms</a> : null}
        </div>
      </div>
    </footer>
  );
}
