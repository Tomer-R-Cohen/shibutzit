export function UserMessage({ text }: { text: string }) {
  return (
    <div className="ws-bubble user">
      <span className="ws-bubble-text">{text}</span>
    </div>
  );
}

export function AssistantMessage({ text }: { text: string }) {
  return (
    <div className="ws-bubble assistant">
      <span className="ws-bubble-text">{text}</span>
    </div>
  );
}

export function ThinkingIndicator() {
  return (
    <div className="ws-bubble assistant">
      <span className="ws-dots" aria-label="שיבוצית בודקת את הבקשה">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}
