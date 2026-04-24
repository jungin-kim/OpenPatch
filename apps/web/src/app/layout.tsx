import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpenPatch",
  description: "Hosted UI shell for OpenPatch.",
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
