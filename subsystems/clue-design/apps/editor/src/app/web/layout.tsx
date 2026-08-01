import type { Metadata } from "next";

// Same self-contained-section pattern as /brand and /new: reuse the shipped
// token layer + component vocabulary, scoped under `.brand-app`. `./web.css`
// adds only the empty-shell layout. Deliberately imports NO scene/editor code
// (no EditorApp, no CanvasKit) — the web shell stays a clean, light bundle.
import "../brand/tokens.css";
import "../brand/brand.css";
import "./web.css";

export const metadata: Metadata = {
  title: "Website — Clue"
};

export default function WebLayout({ children }: { children: React.ReactNode }) {
  return <div className="brand-app web-app">{children}</div>;
}
