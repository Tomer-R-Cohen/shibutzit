import { MessageMarkdown } from "./MessageMarkdown";

export function UserMessage({ text }: { text: string }) {
  return (
    <article className="ws-bubble user" aria-label="הודעה שלך">
      <span className="ws-bubble-text">{text}</span>
    </article>
  );
}

export function AssistantMessage({ text, streaming = false }: { text: string; streaming?: boolean }) {
  return (
    <article className="ws-bubble assistant" aria-label="תשובת עוזרת השיבוץ" aria-live={streaming ? "off" : undefined}>
      <div className="ws-bubble-text">
        <MessageMarkdown text={text} />
        {streaming && <span className="ws-stream-cursor" aria-hidden />}
      </div>
    </article>
  );
}

export function ThinkingIndicator() {
  return (
    <div className="ws-bubble assistant" role="status" aria-live="polite">
      <span className="ws-dots" aria-label="עוזרת השיבוץ בודקת את הבקשה">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}
