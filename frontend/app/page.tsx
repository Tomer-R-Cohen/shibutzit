"use client";

import { useCallback, useEffect, useState } from "react";
import WorkspaceShell from "@/components/workspace/WorkspaceShell";
import TopBar, { RunState } from "@/components/workspace/TopBar";
import Conversation from "@/components/workspace/Conversation";
import ContextInspector from "@/components/workspace/ContextInspector";
import DatasetOnboarding, { DatasetReadyInfo } from "@/components/workspace/DatasetOnboarding";
import Welcome from "@/components/workspace/Welcome";
import FixturePreview from "@/components/workspace/FixturePreview";
import RosterWorkbench from "@/components/workspace/RosterWorkbench";
import ResultsBoard from "@/components/workspace/ResultsBoard";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { getStudents, resetSession } from "@/lib/api";
import { FIXTURES } from "@/lib/fixtures";
import { AttentionTarget, useWorkspace } from "@/lib/workspace";
import { probeDataReady } from "@/lib/bootstrap";
import { resetFlags } from "@/lib/steps";

// The whole app is one workspace: TopBar for orientation, a dominant
// conversation/timeline on the right (RTL inline-start), and a contextual
// inspector on the left that shows whatever is currently relevant -- see
// generic-strolling-oasis.md for the full rationale. Before a dataset is
// ready there is nothing to converse about yet, so the shell shows the
// onboarding dropzone in place of the two-pane workspace.
export default function Home() {
  // Dev-only escape hatch: ?fixture=<name> renders a hand-written, fully
  // local state instead of talking to the real backend -- the only way to
  // screenshot-verify LLM-gated states (constraint proposals) without an
  // API key. Read from the URL client-side only, so production builds
  // never branch on it during SSR.
  const [fixtureName, setFixtureName] = useState<string | null>(null);
  useEffect(() => {
    (() => {
      if (process.env.NODE_ENV === "production") return;
      const f = new URLSearchParams(window.location.search).get("fixture");
      if (f) setFixtureName(f);
    })();
  }, []);

  const workspace = useWorkspace();
  const {
    timeline,
    sending,
    solving,
    setInspector,
    highlight,
    setHighlight,
    workbench,
    setWorkbench,
    refreshConstraintsSummary,
    decideProposal,
    sendMessage,
    runSolve,
    appendDatasetReady,
    appendDataWarning,
  } = workspace;
  const [datasetReady, setDatasetReady] = useState(false);
  // welcome -> (plan | upload) -> workspace. The app used to auto-load the
  // bundled sample on mount, which meant it opened onto someone else's data
  // and there was no moment at which the counselor decided anything. A
  // session that already has data skips straight to the workspace.
  const [phase, setPhase] = useState<"booting" | "welcome" | "upload" | "workspace">("booting");
  const [studentCount, setStudentCount] = useState<number | null>(null);
  const [deciding, setDeciding] = useState(false);
  // Only consulted below the 900px breakpoint, where the inspector stops
  // being a second column and becomes a dismissible sheet.
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);

  const handleReady = useCallback(
    (info: DatasetReadyInfo) => {
      setStudentCount(info.studentCount);
      setDatasetReady(true);
      setPhase("workspace");
      appendDatasetReady(info.studentCount, info.schoolCount, info.levelCount, info.warningCount, info.levelCounts);
      // Default constraints are seeded server-side once a dataset exists, so
      // the summary fetched at mount (before any dataset was loaded) is
      // stale -- refresh it now that there's something to count.
      void refreshConstraintsSummary();
    },
    [appendDatasetReady, refreshConstraintsSummary]
  );

  const handleWarning = useCallback((problems: string[]) => appendDataWarning(problems), [appendDataWarning]);

  useEffect(() => {
    (async () => {
      const ready = await probeDataReady();
      if (!ready) {
        setPhase("welcome");
        return;
      }
      // Returning to a session that already has a roster: rebuild the
      // student count without re-announcing the dataset in the timeline,
      // which the chat history already carries.
      try {
        const st = await getStudents();
        setStudentCount(st.rows.length);
        setDatasetReady(true);
      } catch {
        /* fall through to the workspace anyway; panels handle their own errors */
      }
      setPhase("workspace");
    })();
  }, []);

  // A full reload rather than resetting React state piece by piece: a new
  // session id means every panel's cached fetch is stale, and there are
  // enough of them now that missing one would leave the old roster's
  // numbers on screen under a fresh session.
  async function handleStartOver() {
    try {
      await resetSession();
    } catch {
      /* a new local id is enough; the backend creates the session lazily */
    }
    resetFlags();
    window.location.reload();
  }

  async function handleConfirmProposal(id: string) {
    setDeciding(true);
    try {
      await decideProposal(id, "confirm");
    } finally {
      setDeciding(false);
    }
  }

  async function handleRejectProposal(id: string) {
    setDeciding(true);
    try {
      await decideProposal(id, "reject");
    } finally {
      setDeciding(false);
    }
  }

  function openConstraints() {
    setInspector({ type: "constraints" });
  }

  function openConstraint(id: string) {
    setInspector({ type: "constraint", id });
  }

  function openRoster() {
    setWorkbench("roster");
  }

  function openResults() {
    setWorkbench("results");
  }

  // An attention observation points at a real entity -- open it, and leave
  // the highlight set so the artifact it came from shows what was picked.
  function handleAttentionTarget(target: AttentionTarget) {
    if (target.kind === "constraint") {
      setInspector({ type: "constraint", id: target.id });
      setHighlight({ kind: "constraint", id: target.id });
    } else if (target.kind === "class") {
      setHighlight({ kind: "class", id: target.id });
      openResults();
    } else {
      setInspector({ type: "constraints" });
    }
  }

  // Run state, derived rather than tracked: a rule that landed *after* the
  // most recent solve means the assignment on screen no longer reflects the
  // rules the user can see in the inspector. That gap was previously silent
  // -- the top bar said "שיבוץ עדכני" no matter how much had changed since.
  const lastResultIdx = timeline.map((i) => i.kind).lastIndexOf("solve_result");
  const hasResult = lastResultIdx >= 0;
  const rulesChangedSinceResult =
    hasResult && timeline.slice(lastResultIdx + 1).some((i) => i.kind === "constraint_event");
  const runState: RunState = solving ? "solving" : !hasResult ? "none" : rulesChangedSinceResult ? "stale" : "fresh";

  const lastFailed = [...timeline].reverse().find((i) => i.kind === "solve_result" || i.kind === "solve_failure")?.kind === "solve_failure";
  const composerPlaceholder = hasResult ? "שאלו על השיבוץ או בקשו שינוי..." : "הוסיפו כלל או בקשו שינוי...";
  // The pre-result case used to hand back an empty array, so a user who had
  // typed one rule and sent it got a bare input and no idea what else was
  // possible. Every state now offers a next move.
  const composerSuggestions = lastFailed
    ? ["הצג את הכללים המתנגשים", "הקל על מכסת גודל הכיתה"]
    : hasResult
      ? ["בדוק בקשות חברות", "שפר איזון לימודי"]
      : timeline.length > 0
        ? ["לאזן את רמות הלימוד בין הכיתות", "הצג את הכללים הפעילים"]
        : [];

  if (fixtureName && FIXTURES[fixtureName]) {
    return <FixturePreview fixture={FIXTURES[fixtureName]} />;
  }

  if (phase === "booting") {
    return (
      <div className="ws-shell">
        <TopBar runState="none" onRunSolve={() => {}} canSolve={false} />
        <div className="ws-onboarding">
          <div className="ws-onboarding-box">
            <span className="ws-spinner" aria-hidden />
            <p style={{ margin: 0 }}>רגע…</p>
          </div>
        </div>
      </div>
    );
  }

  if (phase === "welcome") {
    return (
      <div className="ws-shell">
        <TopBar runState="none" onRunSolve={() => {}} canSolve={false} />
        <Welcome onPlan={() => setPhase("workspace")} onUpload={() => setPhase("upload")} />
      </div>
    );
  }

  if (phase === "upload") {
    return (
      <div className="ws-shell">
        <TopBar runState="none" onRunSolve={() => {}} canSolve={false} onStartOver={() => setConfirmingReset(true)} />
        <DatasetOnboarding onReady={handleReady} onWarning={handleWarning} onBack={() => setPhase("welcome")} />
      </div>
    );
  }

  return (
    <>
      <WorkspaceShell
        inspectorOpen={inspectorOpen}
        onCloseInspector={() => setInspectorOpen(false)}
        topBar={
          <TopBar
            runState={runState}
            onRunSolve={runSolve}
            canSolve={datasetReady && !solving}
            onUploadData={!datasetReady ? () => setPhase("upload") : undefined}
            onStartOver={() => setConfirmingReset(true)}
            inspectorOpen={inspectorOpen}
            onToggleInspector={() => setInspectorOpen((v) => !v)}
          />
        }
        conversation={
          <Conversation
            items={timeline}
            sending={sending}
            solving={solving}
            deciding={deciding}
            studentCount={studentCount}
            hasDataset={datasetReady}
            onSend={sendMessage}
            onConfirmProposal={handleConfirmProposal}
            onRejectProposal={handleRejectProposal}
            onOpenRoster={openRoster}
            onOpenResults={openResults}
            onOpenConstraints={openConstraints}
            onOpenConstraint={openConstraint}
            composerPlaceholder={composerPlaceholder}
            composerSuggestions={composerSuggestions}
            highlight={highlight}
            onHighlight={setHighlight}
            onAttentionTarget={handleAttentionTarget}
          />
        }
        inspector={
          <ContextInspector
            workspace={workspace}
            studentCount={studentCount}
            onOpenRoster={openRoster}
            highlight={highlight}
            onHighlight={setHighlight}
            sheetOpen={inspectorOpen}
          />
        }
      />
      <ConfirmDialog
        open={confirmingReset}
        onOpenChange={setConfirmingReset}
        title="להתחיל מחדש?"
        body="הכללים, השיחה, רשימת העמודות והקובץ שנטען יימחקו, ותחזרו למסך הפתיחה. אין דרך לשחזר."
        confirmLabel="כן, להתחיל מחדש"
        danger
        onConfirm={() => void handleStartOver()}
      />
      <RosterWorkbench open={workbench === "roster"} onClose={() => setWorkbench(null)} />
      <ResultsBoard open={workbench === "results"} onClose={() => setWorkbench(null)} />
    </>
  );
}
