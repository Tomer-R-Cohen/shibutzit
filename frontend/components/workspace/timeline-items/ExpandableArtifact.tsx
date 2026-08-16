"use client";

import { ReactNode, useState } from "react";
import { Icon } from "@/components/Icon";

/**
 * Collapsed/expanded body for large artifact content (e.g. a solve
 * failure's per-rule breakdown) so the timeline doesn't permanently carry
 * huge blocks -- the surrounding artifact chrome (head/actions) stays put,
 * only this region toggles. The grid-rows trick animates to auto height
 * without JS measuring.
 */
export function ExpandableArtifact({
  defaultExpanded = false,
  collapsedLabel,
  expandedLabel,
  children,
}: {
  defaultExpanded?: boolean;
  collapsedLabel: string;
  expandedLabel: string;
  children: ReactNode;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  // When a newer solve arrives, this artifact stops being "latest" and
  // should fold itself away. React's documented adjust-state-during-render
  // pattern (not an effect) so the collapse happens in the same commit.
  const [prevDefault, setPrevDefault] = useState(defaultExpanded);
  if (prevDefault !== defaultExpanded) {
    setPrevDefault(defaultExpanded);
    setExpanded(defaultExpanded);
  }

  return (
    <div className="ws-expandable">
      <div className={`ws-expandable-body${expanded ? " open" : ""}`}>
        <div className="ws-expandable-body-inner">{children}</div>
      </div>
      <button type="button" className="ws-expandable-toggle" onClick={() => setExpanded((e) => !e)} aria-expanded={expanded}>
        <Icon name="chevron" size={12} className={expanded ? "ws-expandable-chevron open" : "ws-expandable-chevron"} />
        {expanded ? expandedLabel : collapsedLabel}
      </button>
    </div>
  );
}
