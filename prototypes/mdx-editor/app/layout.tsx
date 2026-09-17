import type { Metadata } from "next";
import "@mdxeditor/editor/style.css";
import "@fontsource/dm-mono/300.css";
import "./generated/tokens.css";
import "./globals.css";

export const metadata: Metadata = { title: "Document editor · Clue prototype", description: "Isolated MDXEditor review with Clue design tokens and sample documents." };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
