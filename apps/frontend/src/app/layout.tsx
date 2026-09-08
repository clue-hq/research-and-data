import type { Metadata } from "next";
import "@clue/design-system/tokens.css";
// D4 (2026-09-09): variables only the pre-D4 design system defined, for the
// features not yet re-synced from the production design. Loaded after
// tokens.css so it can only ADD names, never shadow a production one.
// Deleted by the CSS re-sync job.
import "@clue/design-system/legacy-compat.css";
import "./globals.css";
import { AuthenticationProvider } from "@/auth/provider";

export const metadata: Metadata = {
  title: {
    default: "Clue",
    template: "%s · Clue",
  },
  description: "Clue account intelligence workspace",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const document = (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
  return <AuthenticationProvider>{document}</AuthenticationProvider>;
}
