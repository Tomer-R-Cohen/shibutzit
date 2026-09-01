import type { ReactNode } from "react";

function inlineMarkdown(text: string): ReactNode[] {
  const tokens = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g);
  return tokens.map((token, index) => {
    if (token.startsWith("**") && token.endsWith("**") && token.length > 4) {
      return <strong key={index}>{token.slice(2, -2)}</strong>;
    }
    if (token.startsWith("`") && token.endsWith("`") && token.length > 2) {
      return <code key={index}>{token.slice(1, -1)}</code>;
    }
    return token;
  });
}

function paragraph(lines: string[], key: number) {
  return (
    <p key={key}>
      {lines.map((line, index) => (
        <span key={index}>
          {index > 0 && <br />}
          {inlineMarkdown(line)}
        </span>
      ))}
    </p>
  );
}

/**
 * Deliberately small, safe Markdown subset for model responses.
 *
 * React escapes every text token; raw HTML, images, links, and arbitrary
 * attributes are never interpreted. This covers the response forms the
 * product asks the model to use: paragraphs, headings, ordered/unordered
 * lists, bold emphasis, and inline code.
 */
export function MessageMarkdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const heading = line.match(/^\s*(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const content = inlineMarkdown(heading[2]);
      blocks.push(
        level === 1 ? <h2 key={index}>{content}</h2> : level === 2 ? <h3 key={index}>{content}</h3> : <h4 key={index}>{content}</h4>,
      );
      index += 1;
      continue;
    }

    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    if (unordered) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*[-*]\s+(.+)$/);
        if (!item) break;
        items.push(<li key={index}>{inlineMarkdown(item[1])}</li>);
        index += 1;
      }
      blocks.push(<ul key={`ul-${index}`}>{items}</ul>);
      continue;
    }

    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*\d+[.)]\s+(.+)$/);
        if (!item) break;
        items.push(<li key={index}>{inlineMarkdown(item[1])}</li>);
        index += 1;
      }
      blocks.push(<ol key={`ol-${index}`}>{items}</ol>);
      continue;
    }

    const paragraphLines = [line];
    const paragraphKey = index;
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^\s*(?:#{1,3}\s+|[-*]\s+|\d+[.)]\s+)/.test(lines[index])
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    blocks.push(paragraph(paragraphLines, paragraphKey));
  }

  return <div className="ws-message-markdown">{blocks}</div>;
}
