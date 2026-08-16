"use client";

import { useStickToBottom } from "use-stick-to-bottom";
import { AttentionTarget, Highlight, TimelineItem } from "@/lib/workspace";
import { Icon } from "@/components/Icon";
import Timeline from "./Timeline";
import Composer from "./Composer";
import { AssistantAvatar } from "./timeline-items/Messages";

export default function Conversation({
  items,
  sending,
  solving,
  deciding,
  onSend,
  onConfirmProposal,
  onRejectProposal,
  onOpenRoster,
  onOpenResults,
  onOpenConstraints,
  onOpenConstraint,
  composerPlaceholder,
  composerSuggestions,
  highlight,
  onHighlight,
  onAttentionTarget,
}: {
  items: TimelineItem[];
  sending: boolean;
  solving: boolean;
  deciding: boolean;
  onSend: (text: string) => void;
  onConfirmProposal: (id: string) => void;
  onRejectProposal: (id: string) => void;
  onOpenRoster: () => void;
  onOpenResults: () => void;
  onOpenConstraints: () => void;
  onOpenConstraint: (id: string) => void;
  composerPlaceholder: string;
  composerSuggestions: string[];
  highlight: Highlight;
  onHighlight: (h: Highlight) => void;
  onAttentionTarget: (t: AttentionTarget) => void;
}) {
  const { scrollRef, contentRef, isAtBottom, scrollToBottom } = useStickToBottom({ initial: "instant" });

  return (
    <section className="ws-conversation">
      <div ref={scrollRef} className="ws-timeline-scroll">
        <div ref={contentRef} className="ws-timeline-content">
          {items.length === 0 && !sending && !solving ? (
            <div className="ws-empty">
              <AssistantAvatar />
              <p>למשל: &quot;שרה כהן ומיכל לוי לא יכולות להיות באותה כיתה&quot;</p>
            </div>
          ) : (
            <Timeline
              items={items}
              sending={sending}
              solving={solving}
              deciding={deciding}
              onConfirmProposal={onConfirmProposal}
              onRejectProposal={onRejectProposal}
              onOpenRoster={onOpenRoster}
              onOpenResults={onOpenResults}
              onOpenConstraints={onOpenConstraints}
              onOpenConstraint={onOpenConstraint}
              highlight={highlight}
              onHighlight={onHighlight}
              onAttentionTarget={onAttentionTarget}
            />
          )}
        </div>
      </div>
      {!isAtBottom && (
        <button type="button" className="ws-scroll-bottom" onClick={() => scrollToBottom()} aria-label="גלילה לתחתית השיחה">
          <Icon name="chevron" size={14} />
        </button>
      )}
      <Composer onSend={onSend} sending={sending} placeholder={composerPlaceholder} suggestions={composerSuggestions} />
    </section>
  );
}
