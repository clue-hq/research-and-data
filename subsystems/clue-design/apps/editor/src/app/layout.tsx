import type { Metadata } from "next";
// Order matters: Tailwind theme/utilities → token layer (defines the vars) →
// shell styles (consume them). See tailwind.css for the no-preflight rationale.
import "./tailwind.css";
import "./tokens.css";
import "./styles.css";
// Live-design-streaming S2 chrome — a dedicated sheet so the parked shell CSS
// (styles.css) stays untouched. Consumes existing tokens only.
import "./agentStreaming.css";

export const metadata: Metadata = {
  title: "ABM Design Editor",
  description: "React-Konva editor adapter for the ABM Design Engine"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
