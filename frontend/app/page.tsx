"use client";

import { useCallback, useEffect, useState } from "react";
import WorkspaceShell from "@/components/workspace/WorkspaceShell";
import TopBar, { RunState } from "@/components/workspace/TopBar";
import Conversation from "@/components/workspace/Conversation";
import ContextInspector from "@/components/workspace/ContextInspector";
import DatasetOnboarding, { DatasetReadyInfo } from "@/components/workspace/DatasetOnboarding";
import Welcome from "@/components/workspace/Welcome";
import FixturePreview from "@/components/workspace/FixturePreview";
import FirstRunFixturePreview, { FIRST_RUN_FIXTURES } from "@/components/workspace/FirstRunFixturePreview";
import RosterWorkbench from "@/components/workspace/RosterWorkbench";
import ResultsBoard from "@/components/workspace/ResultsBoard";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { getStudents, resetSession } from "@/lib/api";
import type { SuggestedAction } from "@/lib/api";
import { FIXTURES } from "@/lib/fixtures";
import { AttentionTarget, DataProblem, RosterFocus, useWorkspace } from "@/lib/workspace";
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
    historyReady,
    sending,
    solving,
    solverVisualActive,
    setInspector,
    highlight,
    setHighlight,
    workbench,
    setWorkbench,
    refreshConstraintsSummary,
    refreshResultState,
    resultState,
    suggestions,
    decideProposal,
    sendMessage,
    retryMessage,
    retrySolve,
    runSolve,
    appendDatasetReady,
    appendDataWarning,
    appendManualMove,
    appendFinalApproval,
    bumpDataVersion,
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
  const [rosterFocus, setRosterFocus] = useState<RosterFocus | undefined>(undefined);

  const handleReady = useCallback(
    (info: DatasetReadyInfo) => {
      setStudentCount(info.studentCount);
      setDatasetReady(true);
      setPhase("workspace");
      appendDatasetReady(info.studentCount, info.schoolCount, info.levelCount, info.warningCount, info.levelCounts, info.detectedFields, info.missingFields, info.friendshipCount);
      // Default constraints are seeded server-side once a dataset exists, so
      // the summary fetched at mount (before any dataset was loaded) is
      // stale -- refresh it now that there's something to count.
      void refreshConstraintsSummary();
    },
    [appendDatasetReady, refreshConstraintsSummary]
  );

  const handleWarning = useCallback((problems: DataProblem[]) => appendDataWarning(problems), [appendDataWarning]);

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

  function revealInspectorOnSmallScreen() {
    if (window.matchMedia("(max-width: 900px)").matches) setInspectorOpen(true);
  }

  function openConstraints() {
    setInspector({ type: "constraints" });
    revealInspectorOnSmallScreen();
  }

  function openConstraint(id: string) {
    setInspector({ type: "constraint", id });
    revealInspectorOnSmallScreen();
  }

  function openRoster(focus?: RosterFocus) {
    setRosterFocus(focus);
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
      revealInspectorOnSmallScreen();
    } else if (target.kind === "class") {
      setHighlight({ kind: "class", id: target.id });
      openResults();
    } else {
      setInspector({ type: "constraints" });
      revealInspectorOnSmallScreen();
    }
  }

  // The backend owns freshness through input/solve revisions. Timeline
  // events are narrative only and cannot make an old result look current.
  const lastResultIdx = timeline.map((i) => i.kind).lastIndexOf("solve_result");
  const hasResult = lastResultIdx >= 0;
  // `solving` spans the full orchestration, including the assistant's
  // paced post-result commentary. The top bar must describe the actual
  // assignment state: as soon as the structured result lands and the
  // solver visual stops, the assignment is ready even if the assistant is
  // still finishing its explanation below it.
  const runState: RunState = solverVisualActive
    ? "solving"
    : !resultState?.has_result
      ? "none"
      : resultState.is_stale
        ? "stale"
        : resultState.result_mode === "manual"
          ? "adjusted"
          : "fresh";

  const lastFailed = [...timeline].reverse().find((i) => i.kind === "solve_result" || i.kind === "solve_failure")?.kind === "solve_failure";
  const composerPlaceholder = hasResult ? "שאלו אותי על השיבוץ או בקשו שינוי…" : "כתבו לי מה חשוב לכם בשיבוץ…";
  // The pre-result case used to hand back an empty array, so a user who had
  // typed one rule and sent it got a bare input and no idea what else was
  // possible. Every state now offers a next move.
  const fallbackSuggestions: SuggestedAction[] = lastFailed
    ? [
        { label: "כללי החובה המתנגשים", message: "הציגי את כללי החובה שמתנגשים זה בזה." },
        { label: "בדיקת טווח רחב יותר", message: "בדקי מה יקרה אם נרחיב מעט את טווח גודל הכיתה." },
      ]
    : hasResult
      ? [{ label: "בדיקת בקשות החברות", message: "בדקי אילו בקשות חברות קיבלו מענה בשיבוץ." }]
      : timeline.length > 0
        ? [{ label: "הכללים הפעילים", message: "הציגי את הכללים הפעילים ואת ההגדרות שלהם." }]
        : [];
  const composerSuggestions = suggestions.length > 0 ? suggestions : fallbackSuggestions;

  if (fixtureName && FIRST_RUN_FIXTURES.has(fixtureName)) {
    return <FirstRunFixturePreview name={fixtureName} />;
  }

  function openHistory() {
    setInspector({ type: "overview" });
    revealInspectorOnSmallScreen();
  }

  if (fixtureName && FIXTURES[fixtureName]) {
    return <FixturePreview fixture={FIXTURES[fixtureName]} />;
  }

  if (phase === "booting") {
    return (
      <div className="ws-shell">
        <TopBar runState="none" onRunSolve={() => {}} canSolve={false} showRunStatus={false} />
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
        <TopBar runState="none" onRunSolve={() => {}} canSolve={false} showRunStatus={false} />
        <Welcome onPlan={() => setPhase("workspace")} onUpload={() => setPhase("upload")} />
      </div>
    );
  }

  if (phase === "upload") {
    return (
      <div className="ws-shell">
        <TopBar runState="none" onRunSolve={() => {}} canSolve={false} onStartOver={() => setConfirmingReset(true)} showRunStatus={false} />
        <DatasetOnboarding onReady={handleReady} onWarning={handleWarning} onBack={() => setPhase("welcome")} />
      </div>
    );
  }

  return (
    <>
      <WorkspaceShell
        inspectorVisible={datasetReady}
        inspectorOpen={inspectorOpen}
        onCloseInspector={() => setInspectorOpen(false)}
        topBar={
          <TopBar
            runState={runState}
            onRunSolve={() => void runSolve()}
            canSolve={datasetReady && !solving}
            onUploadData={!datasetReady ? () => setPhase("upload") : undefined}
            onStartOver={() => setConfirmingReset(true)}
            inspectorOpen={inspectorOpen}
            onToggleInspector={datasetReady ? () => setInspectorOpen((v) => !v) : undefined}
          />
        }
        conversation={
          <Conversation
            items={timeline}
            sending={sending}
            solving={solving}
            solverVisualActive={solverVisualActive}
            deciding={deciding}
            studentCount={studentCount}
            historyReady={historyReady}
            hasDataset={datasetReady}
            onSend={sendMessage}
            onConfirmProposal={handleConfirmProposal}
            onRejectProposal={handleRejectProposal}
            onOpenRoster={openRoster}
            onOpenResults={openResults}
            onOpenConstraints={openConstraints}
            onOpenConstraint={openConstraint}
            onOpenHistory={openHistory}
            onRetryMessage={retryMessage}
            onRetrySolve={retrySolve}
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
            onOpenResults={openResults}
            highlight={highlight}
            onHighlight={setHighlight}
            sheetOpen={inspectorOpen}
            onCloseSheet={() => setInspectorOpen(false)}
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
      <RosterWorkbench
        open={workbench === "roster"}
        focus={rosterFocus}
        onClose={() => {
          setWorkbench(null);
          setRosterFocus(undefined);
        }}
      />
      <ResultsBoard
        open={workbench === "results"}
        onClose={() => setWorkbench(null)}
        onResultChanged={() => {
          void refreshResultState();
          bumpDataVersion();
        }}
        onAskAI={sending || solving ? undefined : (message) => {
          setWorkbench(null);
          void sendMessage(message);
        }}
        onManualMove={appendManualMove}
        onApproved={appendFinalApproval}
      />
    </>
  );
}
