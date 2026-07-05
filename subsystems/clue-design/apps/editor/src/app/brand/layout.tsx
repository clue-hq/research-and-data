import type { Metadata } from "next";
import Link from "next/link";

import "./tokens.css";
import "./brand.css";

export const metadata: Metadata = {
  title: "Brand — Clue",
};

export default function BrandLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="brand-app">
      <header className="brand-topbar">
        <Link href="/brand" className="brand-wordmark">
          Clue<span className="dot">.</span>
        </Link>
        <nav>
          <Link href="/brand">Kits</Link>
          <Link href="/brand/library">Library</Link>
          <Link href="/brand/ingest">Ingest</Link>
        </nav>
        <div>
          <a className="btn btn-ghost btn-sm" href="/">
            Open editor
          </a>
        </div>
      </header>
      <main className="brand-main">{children}</main>
    </div>
  );
}
