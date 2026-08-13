"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";

/**
 * The composer surface: an auto-growing textarea inside a single rounded,
 * elevated container (not two bordered elements side by side) -- adapted
 * from the AI Elements PromptInput structure (toolbar + state-aware submit
 * button), re-implemented against our own send flow instead of the `ai`
 * SDK it ships with. Enter sends, Shift+Enter inserts a newline.
 */
export default function Composer({
  onSend,
  sending,
  placeholder,
  suggestions,
}: {
  onSend: (text: string) => void;
  sending: boolean;
  placeholder: string;
  suggestions: string[];
}) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  function submit() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    onSend(text);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  // Chips fill the composer rather than sending immediately -- the user
  // still reviews and presses send, which keeps the confirm-before-act
  // model the rest of the product follows.
  function applySuggestion(text: string) {
    setInput(text);
    textareaRef.current?.focus();
  }

  return (
    <div className="ws-composer-row">
      {suggestions.length > 0 && !input && (
        <div className="ws-composer-suggestions">
          {suggestions.map((s) => (
            <button key={s} type="button" className="ws-suggestion-chip" onClick={() => applySuggestion(s)} disabled={sending}>
              {s}
            </button>
          ))}
        </div>
      )}
      <form
        className="ws-composer-surface"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          className="ws-composer-textarea"
          disabled={sending}
        />
        <button type="submit" className="ws-composer-send" disabled={sending || !input.trim()} aria-label="שליחה">
          <Icon name="send" size={16} />
        </button>
      </form>
    </div>
  );
}
