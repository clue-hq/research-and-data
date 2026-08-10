import type { Metadata } from "next";
import "@clue/design-system/tokens.css";
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
