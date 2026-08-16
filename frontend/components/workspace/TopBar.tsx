"use client";

import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";

/**
 * Brand + the one primary action. Deliberately thin -- this is
 * orientation, not a dashboard; student/rule counts already live one
 * click away in the inspector's overview pane, so they don't need a
 * second, permanent home up here too. Once a result exists, the primary
 * action shrinks to a secondary "run again" next to a plain confirmation
 * that the workspace has a real result -- the interface should say so,
 * not just sit there with the same "run" button as before anything
 * happened.
 */
export default function TopBar({
  onRunSolve,
  solving,
  canSolve,
  hasResult,
}: {
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
