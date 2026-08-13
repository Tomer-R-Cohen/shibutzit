"use client";

import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import { ConstraintsSummary } from "@/lib/workspace";

/**
 * Brand + at-a-glance counts + the one primary action. Deliberately thin --
 * this is orientation, not a dashboard; everything else lives in the
 * conversation or the inspector. Once a result exists, the primary action
 * shrinks to a secondary "run again" next to a plain confirmation that the
 * workspace has a real result -- the interface should say so, not just sit
 * there with the same "run" button as before anything happened.
 */
export default function TopBar({
  studentCount,
  constraintsSummary,
  onRunSolve,
  solving,
  canSolve,
  hasResult,
}: {
  studentCount: number | null;
  constraintsSummary: ConstraintsSummary | null;
  onRunSolve: () => void;
  solving: boolean;
  canSolve: boolean;
  hasResult: boolean;
}) {
  return (
    <header className="ws-topbar">
      <div className="cw-brand">
        <div className="cw-brand-mark">ז</div>
        <div className="cw-brand-title">שיבוצית</div>
      </div>
      <div className="ws-topbar-counts">
        {studentCount != null && <span className="cw-num">{studentCount} תלמידות</span>}
        {constraintsSummary && (
          <span className="cw-num">
            {constraintsSummary.active} כללים · {constraintsSummary.hard} קשיחים
          </span>
        )}
      </div>
      <div className="ws-topbar-spacer" />
      {hasResult && !solving ? (
        <div className="ws-topbar-result">
          <span className="ws-topbar-result-ok">
            <Icon name="check" size={13} />
            שיבוץ עדכני
          </span>
          <Button variant="secondary" size="sm" disabled={!canSolve} onClick={onRunSolve}>
            הרצה מחדש
          </Button>
        </div>
      ) : (
        <Button disabled={!canSolve || solving} onClick={onRunSolve}>
          {solving ? "מריץ שיבוץ…" : "הרצת שיבוץ"}
        </Button>
      )}
    </header>
  );
}
