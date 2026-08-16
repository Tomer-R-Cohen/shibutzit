import { Icon } from "@/components/Icon";

export function AssistantAvatar() {
  return (
    <span className="ws-avatar" aria-hidden>
      <Icon name="sparkle" size={12} />
    </span>
  );
}

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
      <AssistantAvatar />
      <span className="ws-bubble-text">{text}</span>
    </div>
  );
}

export function ThinkingIndicator() {
  return (
    <div className="ws-bubble assistant">
      <AssistantAvatar />
      <span className="ws-dots" aria-label="העוזר מעבד את הבקשה">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}
