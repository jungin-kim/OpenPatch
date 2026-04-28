import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "./CodeBlock";

interface MarkdownContentProps {
  content: string;
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="markdown-body">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Block code: has a language-xxx className on the code element
        // Inline code: no className
        code({ className, children }) {
          const langMatch = /language-(\w+)/.exec(className ?? "");
          const code = String(children).replace(/\n$/, "");

          if (langMatch ?? className) {
            // Fenced code block
            return <CodeBlock code={code} lang={langMatch?.[1]} />;
          }

          // Inline code
          return <code className="inline-code">{children}</code>;
        },

        // Strip the outer <pre> wrapper — CodeBlock renders its own
        pre({ children }) {
          return <>{children}</>;
        },
      }}
    >
      {content}
    </ReactMarkdown>
    </div>
  );
}
