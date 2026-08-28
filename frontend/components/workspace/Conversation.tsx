"use client";

import { useRef, useState } from "react";
import { useStickToBottom } from "use-stick-to-bottom";
import { AttentionTarget, Highlight, TimelineItem } from "@/lib/workspace";
import { Icon } from "@/components/Icon";
import Timeline from "./Timeline";
import Composer, { ComposerHandle } from "./Composer";
import Launcher from "./Launcher";
import type { SuggestedAction } from "@/lib/api";

export default function Conversation({
  items,
  sending,
  solving,
  deciding,
  studentCount,
  hasDataset = true,
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
  studentCount: number | null;
  hasDataset?: boolean;
  onSend: (text: string) => void;
  onConfirmProposal: (id: string) => void;
  onRejectProposal: (id: string) => void;
  onOpenRoster: () => void;
  onOpenResults: () => void;
  onOpenConstraints: () => void;
  onOpenConstraint: (id: string) => void;
  composerPlaceholder: string;
  composerSuggestions: SuggestedAction[];
  highlight: Highlight;
  onHighlight: (h: Highlight) => void;
  onAttentionTarget: (t: AttentionTarget) => void;
}) {
  const { scrollRef, contentRef, isAtBottom, scrollToBottom } = useStickToBottom({ initial: "instant" });
  // The draft lives here so the launcher (above the fold) and the composer
  // (pinned below it) are writing into the same field.
  const [draft, setDraft] = useState("");
  const composerRef = useRef<ComposerHandle>(null);

  function pick(text: string) {
    setDraft(text);
    composerRef.current?.focus();
  }

  return (
    <section className="ws-conversation">
      <div ref={scrollRef} className="ws-timeline-scroll">
        <div ref={contentRef} className="ws-timeline-content">
          {items.length === 0 && !sending && !solving ? (
            <Launcher studentCount={studentCount} hasDataset={hasDataset} onPick={pick} />
          ) : (
            <>
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
              {/* follow-up openings, right where the conversation left off --
                  same click-to-fill row style as the first-run launcher, so
                  continuing feels like the same gesture as starting. Hidden
                  while a reply is in flight so it doesn't compete with the
                  "thinking" state. */}
              {!sending && !solving && composerSuggestions.length > 0 && (
                <div className="ws-inline-suggestions">
                  <div className="ws-launcher-label">אפשר להמשיך עם</div>
                  <div className="ws-launcher-list">
                    {composerSuggestions.map((s) => (
                      <button key={s.message} type="button" className="ws-launcher-row" onClick={() => pick(s.message)}>
                        <span className="ico" aria-hidden>
                          <Icon name="sparkle" size={15} />
                        </span>
                        <span className="txt">{s.label}</span>
                        <Icon name="chevron" size={14} className="ws-chev" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      {!isAtBottom && (
        <button type="button" className="ws-scroll-bottom" onClick={() => scrollToBottom()} aria-label="גלילה לתחתית השיחה">
          <Icon name="chevron" size={14} />
        </button>
      )}
      <Composer
        ref={composerRef}
        value={draft}
        onValueChange={setDraft}
        onSend={onSend}
        sending={sending}
        placeholder={composerPlaceholder}
      />
    </section>
  );
}
