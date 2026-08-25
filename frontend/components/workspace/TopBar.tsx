"use client";

import clsx from "clsx";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";

/**
 * Three zones: identity, run state, the one primary action.
 *
 * The middle zone exists because a conversational solver has a failure mode
 * no button can fix -- you confirm two more rules, scroll up, and the result
 * artifact sitting above you is now describing an assignment that no longer
 * reflects those rules. Nothing on screen used to say so. `runState` is
 * derived from the timeline (a rule landing after the last solve makes the
 * result stale), and the primary action re-labels itself to match, so "the
 * numbers are out of date" and "here is how to fix that" are the same
 * sentence.
 *
 * The state is spelled out in words, never carried by the dot's colour
 * alone.
 */
export type RunState = "none" | "solving" | "fresh" | "stale";

const RUN_STATE_TEXT: Record<RunState, string> = {
  none: "טרם הופק שיבוץ",
  solving: "מפיק שיבוץ…",
  fresh: "השיבוץ מעודכן",
  stale: "הכללים השתנו מאז ההרצה",
};

const RUN_ACTION_TEXT: Record<RunState, string> = {
  none: "הרצת שיבוץ",
  solving: "מריץ…",
  fresh: "הרצה מחדש",
  stale: "הרצה מחדש",
};

export default function TopBar({
  runState,
  onRunSolve,
  canSolve,
  inspectorOpen,
  onToggleInspector,
  onUploadData,
  onStartOver,
}: {
  runState: RunState;
  onRunSolve: () => void;
  canSolve: boolean;
  inspectorOpen?: boolean;
  onToggleInspector?: () => void;
  /** Present only while planning: there is no roster yet. */
  onUploadData?: () => void;
  /** Discard this session and go back to the first screen. */
  onStartOver?: () => void;
}) {
  const solving = runState === "solving";

  return (
    <header className="ws-topbar">
      <div className="ws-brand">
        <div className="ws-brand-mark" aria-hidden>
          ז
        </div>
        <div className="ws-brand-title">שיבוצית</div>
      </div>

      <span
        className={clsx("ws-runstate", runState === "fresh" && "fresh", runState === "stale" && "stale", solving && "busy")}
        aria-live="polite"
      >
        <span className="dot" aria-hidden />
        {onUploadData ? "תכנון - טרם נטען קובץ" : RUN_STATE_TEXT[runState]}
      </span>

      <div className="ws-topbar-spacer" />

      <div className="ws-topbar-actions">
        {/* The welcome screen was previously unreachable once a session
            had data: the app probes for a roster on load and goes
            straight to the workspace. This is the way back. */}
        {onStartOver && (
          <button type="button" className="ws-startover" onClick={onStartOver}>
            התחלה חדשה
          </button>
        )}
        {onToggleInspector && (
          <button
            type="button"
            className="ws-insp-toggle"
            onClick={onToggleInspector}
            aria-expanded={!!inspectorOpen}
            aria-controls="ws-inspector"
          >
            <Icon name="list" size={14} />
            מצב נוכחי
          </button>
        )}
        {/* Planning mode has no roster, so "run" is meaningless and loading
            the file is the real next step. */}
        {onUploadData ? (
          <Button onClick={onUploadData}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <Icon name="upload" size={14} />
              טעינת קובץ
            </span>
          </Button>
        ) : (
        <>
        {/* Once a result exists the run button stops being the loudest thing
            on screen -- unless the rules moved under it, in which case it
            goes back to primary because re-running is now the point. */}
        <Button
          variant={runState === "fresh" ? "secondary" : "primary"}
          disabled={!canSolve || solving}
          onClick={onRunSolve}
        >
          {RUN_ACTION_TEXT[runState]}
        </Button>
        </>
        )}
      </div>
    </header>
  );
}
