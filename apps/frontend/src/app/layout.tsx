import type { Metadata } from "next";
import "@clue/design-system/tokens.css";
// D4 (2026-09-09): variables only the pre-D4 design system defined, for the
// features not yet re-synced from the production design. Loaded after
// tokens.css so it can only ADD names, never shadow a production one.
// Deleted by the CSS re-sync job.
import "@clue/design-system/legacy-compat.css";
import "./globals.css";
import { AuthenticationProvider } from "@/auth/provider";
import { localWorkspaceInstance } from "@/auth/local-workspace";
import { LocalWorkspaceProvider } from "@/features/session/components/local-workspace-provider";

export function generateMetadata(): Metadata {
  const instance = localWorkspaceInstance();
  return {
    title: instance
      ? { default: `${instance.name} · Local ${instance.port}`, template: `${instance.name} · %s · ${instance.port}` }
      : { default: "Clue", template: "%s · Clue" },
    description: "Clue account intelligence workspace",
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const instance = localWorkspaceInstance();
  const document = (
    <html lang="en" className="h-full antialiased">
      {/* The workspace switcher lives in the protected layout, which is where the
          session's memberships are read; an unauthenticated page has none. */}
      <body className="min-h-full">{children}</body>
    </html>
  );
  return (
    <AuthenticationProvider>
      <LocalWorkspaceProvider value={instance ? { name: instance.name, port: instance.port } : null}>
        {document}
      </LocalWorkspaceProvider>
    </AuthenticationProvider>
  );
}
