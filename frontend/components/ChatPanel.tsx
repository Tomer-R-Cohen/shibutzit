"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import {
  ApiError,
  ChatMessage,
  PendingProposal,
  confirmChatProposal,
  getChatHistory,
  rejectChatProposal,
  sendChatMessage,
} from "@/lib/api";

function AssistantAvatar() {
  return (
    <span className="chat-avatar" aria-hidden>
      <Icon name="sparkle" size={12} />
    </span>
  );
}

/**
 * Conversational constraint agent. Every proposal the model makes is shown
 * here for explicit confirmation before it touches the constraint list --
 * this component never applies anything itself, only /api/chat/confirm
 * does. `onConstraintsChanged` lets the host refresh ConstraintList after
 * a confirm.
 *
 * Deliberately shows a "thinking" state while waiting on a reply and gives
 * the assistant a consistent visual presence (an avatar) -- the point is
 * for this to read as an active expert working, not a form that submits
 * into a void.
 */
export default function ChatPanel({ onConstraintsChanged }: { onConstraintsChanged?: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<PendingProposal | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getChatHistory()
      .then((r) => {
        setMessages(r.messages);
        setPending(r.pending_proposal);
      })
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, pending, sending]);

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setSending(true);
    try {
      const res = await sendChatMessage(text);
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
      setPending(res.pending_proposal);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "שגיאה בשליחת ההודעה");
      setMessages((prev) => prev.slice(0, -1));
      setInput(text);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  async function handleConfirm() {
    setDeciding(true);
    try {
      await confirmChatProposal();
      setPending(null);
      setMessages((prev) => [...prev, { role: "assistant", content: "בוצע — הכלל נוסף לרשימה." }]);
      onConstraintsChanged?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "שגיאה באישור ההצעה");
    } finally {
      setDeciding(false);
    }
  }

  async function handleReject() {
    setDeciding(true);
    try {
      await rejectChatProposal();
      setPending(null);
      setMessages((prev) => [...prev, { role: "assistant", content: "בסדר, ההצעה בוטלה." }]);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "שגיאה בדחיית ההצעה");
    } finally {
      setDeciding(false);
    }
  }

  return (
    <section className="cfg-card chat-card">
      <div className="cfg-card-head">
        <span className="t">שיחה עם העוזר</span>
        <span className="d">תארו כלל בעברית חופשית — כל הצעה מוצגת לאישור לפני שהיא נכנסת לתוקף</span>
      </div>

      <div ref={scrollRef} className="chat-scroll">
        {!loaded ? null : messages.length === 0 && !pending && !sending ? (
          <div className="chat-empty">
            <AssistantAvatar />
            <p>למשל: &quot;שרה כהן ומיכל לוי לא יכולות להיות באותה כיתה&quot;</p>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`chat-bubble ${m.role}`}>
              {m.role === "assistant" && <AssistantAvatar />}
              <span className="chat-bubble-text">{m.content}</span>
            </div>
          ))
        )}

        {sending && (
          <div className="chat-bubble assistant chat-thinking" aria-live="polite">
            <AssistantAvatar />
            <span className="chat-dots" aria-label="העוזר מעבד את הבקשה">
              <span />
              <span />
              <span />
            </span>
          </div>
        )}

        {pending && (
          <div className="chat-proposal">
            <div className="chat-proposal-head">
              <Icon name="sparkle" size={13} />
              <span>הצעה</span>
            </div>
            <div className="chat-proposal-text">{pending.summary_hebrew}</div>
            <div className="chat-proposal-actions">
              <Button size="sm" variant="secondary" onClick={handleReject} disabled={deciding}>
                דחייה
              </Button>
              <Button size="sm" onClick={handleConfirm} disabled={deciding}>
                {deciding ? "מבצע…" : "אישור"}
              </Button>
            </div>
          </div>
        )}
      </div>

      <form onSubmit={handleSend} className="chat-input-row">
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="כתבו כלל או שאלה…"
          className="chat-input"
          disabled={sending}
        />
        <button type="submit" className="chat-send" disabled={sending || !input.trim()} aria-label="שליחה">
          <Icon name="send" size={16} />
        </button>
      </form>
    </section>
  );
}
