"use client";

import { KeyboardEvent, useEffect, useImperativeHandle, useRef, RefObject } from "react";
import { Icon } from "@/components/Icon";

/**
 * The composer surface: an auto-growing textarea inside a single rounded,
 * elevated container (not two bordered elements side by side) -- adapted
 * from the AI Elements PromptInput structure (toolbar + state-aware submit
 * button), re-implemented against our own send flow instead of the `ai`
 * SDK it ships with. Enter sends, Shift+Enter inserts a newline.
 *
 * The draft lives in the parent rather than here, because the first-run
 * launcher sits outside this component and fills it -- same click-to-fill
 * contract the suggestion chips already used, just from further away.
 */
export interface ComposerHandle {
  focus: () => void;
}

export default function Composer({
  value,
  onValueChange,
  onSend,
  sending,
  placeholder,
  suggestions,
  ref,
}: {
  value: string;
  onValueChange: (v: string) => void;
  onSend: (text: string) => void;
  sending: boolean;
  placeholder: string;
  suggestions: string[];
  ref?: RefObject<ComposerHandle | null>;
}) {
  const input = value;
  const setInput = onValueChange;
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({ focus: () => textareaRef.current?.focus() }), []);

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
          dir="auto"
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
