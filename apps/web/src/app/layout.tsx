import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RepoOperator",
  description: "Hosted UI shell for RepoOperator.",
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
