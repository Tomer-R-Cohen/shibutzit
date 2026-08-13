"use client";

import { useEffect, useState } from "react";
import { ConstraintsSummary } from "@/lib/workspace";
import { RunConfig, getRunConfig } from "@/lib/api";
import { Icon } from "@/components/Icon";

/**
 * The default inspector pane: what's true right now. Sections are separated
 * by whitespace + a hairline divider rather than a bordered card each --
 * the panel's own background already distinguishes it from the canvas, so
 * a box around every row would be a border doing no work.
 */
export default function OverviewInspector({
  studentCount,
  constraintsSummary,
  onOpenConstraints,
  onOpenRoster,
}: {
  studentCount: number | null;
  constraintsSummary: ConstraintsSummary | null;
  onOpenConstraints: () => void;
  onOpenRoster?: () => void;
}) {
  const [runConfig, setRunConfig] = useState<RunConfig | null>(null);

  useEffect(() => {
    getRunConfig()
      .then(setRunConfig)
      .catch(() => {});
  }, []);

  return (
    <>
      <div className="ws-insp-section">
        <div className="ws-insp-title">מצב נוכחי</div>
      </div>

      <div className="ws-insp-section">
        {onOpenRoster ? (
          <button className="ws-insp-row" onClick={onOpenRoster}>
            <span>נתונים</span>
            <span className="ws-insp-row-meta">{studentCount != null ? `${studentCount} תלמידות` : "טרם נטען"}</span>
            <Icon name="chevron" size={13} className="ws-chev" style={{ transform: "rotate(-90deg)" }} />
          </button>
        ) : (
          <div className="ws-insp-row" style={{ cursor: "default" }}>
            <span>נתונים</span>
            <span className="ws-insp-row-meta">{studentCount != null ? `${studentCount} תלמידות` : "טרם נטען"}</span>
          </div>
        )}
      </div>

      <div className="ws-insp-section">
        <button className="ws-insp-row" onClick={onOpenConstraints}>
          <span>כללים</span>
          <span className="ws-insp-row-meta">
            {constraintsSummary ? `${constraintsSummary.active} פעילים · ${constraintsSummary.hard} קשיחים` : "…"}
          </span>
          <Icon name="chevron" size={13} className="ws-chev" style={{ transform: "rotate(-90deg)" }} />
        </button>
      </div>

      <div className="ws-insp-section">
        <div className="ws-insp-row" style={{ cursor: "default" }}>
          <span>שיבוץ</span>
          <span className="ws-insp-row-meta">{runConfig ? `${runConfig.num_classes} כיתות` : "…"}</span>
        </div>
      </div>
    </>
  );
}
