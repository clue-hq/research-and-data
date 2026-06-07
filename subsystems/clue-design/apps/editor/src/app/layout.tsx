import type { Metadata } from "next";
import "./styles.css";

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
