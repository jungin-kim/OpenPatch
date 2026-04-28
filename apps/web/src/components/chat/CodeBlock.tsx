"use client";

import { useState } from "react";

const LANG_LABELS: Record<string, string> = {
  python: "Python",
  py: "Python",
  javascript: "JavaScript",
  js: "JavaScript",
  typescript: "TypeScript",
  ts: "TypeScript",
  jsx: "JSX",
  tsx: "TSX",
  bash: "Bash",
  sh: "Shell",
  zsh: "Zsh",
  fish: "Fish",
  powershell: "PowerShell",
  ps1: "PowerShell",
  json: "JSON",
  yaml: "YAML",
  yml: "YAML",
  toml: "TOML",
  ini: "INI",
  cfg: "Config",
  env: "Env",
  diff: "Diff",
  patch: "Patch",
  sql: "SQL",
  html: "HTML",
  css: "CSS",
  scss: "SCSS",
  xml: "XML",
  rust: "Rust",
  rs: "Rust",
  go: "Go",
  java: "Java",
  ruby: "Ruby",
  rb: "Ruby",
  php: "PHP",
  c: "C",
  cpp: "C++",
  cs: "C#",
  swift: "Swift",
  kotlin: "Kotlin",
  kt: "Kotlin",
  scala: "Scala",
  elixir: "Elixir",
  ex: "Elixir",
  exs: "Elixir",
  elm: "Elm",
  haskell: "Haskell",
  hs: "Haskell",
  lua: "Lua",
  r: "R",
  matlab: "MATLAB",
  makefile: "Makefile",
  dockerfile: "Dockerfile",
  proto: "Protobuf",
  terraform: "Terraform",
  tf: "Terraform",
  hcl: "HCL",
  markdown: "Markdown",
  md: "Markdown",
  plaintext: "Text",
  text: "Text",
  txt: "Text",
  output: "Output",
  console: "Console",
  terminal: "Terminal",
  log: "Log",
};

interface CodeBlockProps {
  code: string;
  lang?: string;
}

export function CodeBlock({ code, lang }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const langKey = lang?.toLowerCase().trim() ?? "";
  const label = LANG_LABELS[langKey] ?? (lang ? lang : "Code");

  function handleCopy() {
    navigator.clipboard
      .writeText(code)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        // Clipboard API unavailable (e.g. non-secure context)
      });
  }

  return (
    <div className="chat-code-block">
      <div className="chat-code-header">
        <span className="chat-code-lang">{label}</span>
        <button
          className={`chat-code-copy${copied ? " chat-code-copy-success" : ""}`}
          type="button"
          onClick={handleCopy}
          aria-label={copied ? "Copied!" : "Copy code"}
        >
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>
      <pre className="chat-code-pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}
