import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nebula",
  description: "Amazon Nova-powered evidence-backed grant writing workspace",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
