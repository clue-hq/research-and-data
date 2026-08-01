import type { Metadata } from "next";

// Follow the /brand section pattern: a self-contained section that reuses the
// shipped Cursor-skin token layer + component vocabulary (chips, cards, ink
// pills). Scoped under `.brand-app`, so `.btn`/form styles resolve and the
// tokens are in scope; `./new.css` adds only the gate-specific layout.
import "../brand/tokens.css";
import "../brand/brand.css";
import "./new.css";

export const metadata: Metadata = {
  title: "New — Clue"
};

export default function NewLayout({ children }: { children: React.ReactNode }) {
  return <div className="brand-app new-app">{children}</div>;
}
