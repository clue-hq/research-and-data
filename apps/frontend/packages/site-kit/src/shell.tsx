// The site shell: one campaign header and one footer, stored once per site and rendered around
// every page. "Prepared for <account>" sits beside the seller's logo, not under it.
import type { BrandData } from "./brand";

export type HeaderProps = {
  preparedFor: string;
  accountLogo: string;
  ctaLabel: string;
  ctaHref: string;
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

export function SiteHeader({ brand, header, href }: { brand: BrandData; header: HeaderProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  return (
    <header className="border-b border-line-subtle bg-surface-page text-on-surface-page">
      <div className="mx-auto flex max-w-[75rem] items-center justify-between gap-4 px-6 py-3 md:px-10">
        <div className="flex min-w-0 items-center gap-3 md:gap-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {logo ? <img src={logo} alt="" className="h-6 w-auto shrink-0 md:h-7" /> : null}
          <span aria-hidden className="h-6 w-px shrink-0 bg-line-default" />
          {header.accountLogo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={header.accountLogo} alt="" className="h-6 w-auto shrink-0" />
          ) : null}
          <span className="min-w-0 truncate font-body text-body text-ink-secondary">
            <span className="hidden sm:inline">Prepared for </span>
            <span className="font-semibold text-ink-primary">{header.preparedFor}</span>
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-6">
          {header.nav?.length ? (
            <nav className="hidden items-center gap-5 md:flex">
              {header.nav.map((item) => (
                <a key={item.href + item.label} href={href(item.href)} className="font-body text-body text-ink-primary hover:underline">
                  {item.label}
                </a>
              ))}
            </nav>
          ) : null}
          {/* On phones the hero carries the same action, so the account name gets the room. */}
          <a href={href(header.ctaHref)} className="brand-btn hidden shrink-0 sm:inline-flex">
            {header.ctaLabel}
          </a>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter({ brand, footer, href }: { brand: BrandData; footer: FooterProps; href: (v: string) => string }) {
  const logo = sellerLogo(brand);
  return (
    <footer className="border-t border-line-subtle bg-surface-page text-on-surface-page">
      <div className="mx-auto flex max-w-[75rem] flex-col gap-4 px-6 py-8 md:flex-row md:items-center md:justify-between md:px-10">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {logo ? <img src={logo} alt="" className="h-5 w-auto self-start opacity-80" /> : null}
        <p className="font-caption text-caption text-ink-muted">{footer.legal}</p>
        <div className="flex gap-6 font-caption text-caption text-ink-muted">
          {footer.privacyHref ? <a href={href(footer.privacyHref)} className="hover:underline">Privacy policy</a> : null}
          {footer.termsHref ? <a href={href(footer.termsHref)} className="hover:underline">Terms</a> : null}
        </div>
      </div>
    </footer>
  );
}
