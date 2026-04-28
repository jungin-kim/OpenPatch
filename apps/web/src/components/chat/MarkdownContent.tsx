import { CodeBlock } from "./CodeBlock";

type Segment =
  | { type: "text"; value: string }
  | { type: "code"; value: string; lang?: string };

interface MarkdownContentProps {
  content: string;
}

function splitMarkdown(content: string): Segment[] {
  const segments: Segment[] = [];
  const fencePattern = /```([A-Za-z0-9_-]+)?[ \t]*\n([\s\S]*?)```/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = fencePattern.exec(content)) !== null) {
    if (match.index > cursor) {
      segments.push({ type: "text", value: content.slice(cursor, match.index) });
    }
    segments.push({
      type: "code",
      lang: match[1],
      value: match[2].replace(/\n$/, ""),
    });
    cursor = match.index + match[0].length;
  }

  if (cursor < content.length) {
    segments.push({ type: "text", value: content.slice(cursor) });
  }

  return segments.length ? segments : [{ type: "text", value: content }];
}

function renderInline(text: string) {
  const parts = text.split(/(`[^`\n]+`)/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code className="inline-code" key={`${part}-${index}`}>
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

function TextBlock({ value }: { value: string }) {
  const paragraphs = value
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  if (!paragraphs.length) {
    return null;
  }

  return (
    <>
      {paragraphs.map((paragraph, index) => (
        <p key={`${paragraph}-${index}`}>
          {paragraph.split(/\n/).map((line, lineIndex) => (
            <span key={`${line}-${lineIndex}`}>
              {lineIndex > 0 ? <br /> : null}
              {renderInline(line)}
            </span>
          ))}
        </p>
      ))}
    </>
  );
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  const segments = splitMarkdown(content);

  return (
    <div className="markdown-body">
      {segments.map((segment, index) =>
        segment.type === "code" ? (
          <CodeBlock
            code={segment.value}
            lang={segment.lang}
            key={`${segment.lang || "code"}-${index}`}
          />
        ) : (
          <TextBlock value={segment.value} key={`text-${index}`} />
        ),
      )}
    </div>
  );
}
