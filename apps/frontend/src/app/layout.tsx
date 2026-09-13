import type { Metadata } from "next";
import "@clue/design-system/tokens.css";
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
