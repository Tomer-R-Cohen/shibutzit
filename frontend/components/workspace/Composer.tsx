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
 * launcher (and the inline follow-up suggestions in the timeline) sit
 * outside this component and fill it -- click-to-fill from further away.
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
  ref,
}: {
  value: string;
  onValueChange: (v: string) => void;
  onSend: (text: string) => void;
  sending: boolean;
  placeholder: string;
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

  return (
    <div className="ws-composer-row">
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
