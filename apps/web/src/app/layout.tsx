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
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
try {
  var saved = localStorage.getItem("repooperator-theme");
  var theme = saved === "dark" || saved === "light"
    ? saved
    : (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
} catch (_) {}
`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
