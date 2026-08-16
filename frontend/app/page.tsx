"use client";

import { useCallback, useEffect, useState } from "react";
import WorkspaceShell from "@/components/workspace/WorkspaceShell";
import TopBar from "@/components/workspace/TopBar";
import Conversation from "@/components/workspace/Conversation";
import ContextInspector from "@/components/workspace/ContextInspector";
import DatasetOnboarding, { DatasetReadyInfo } from "@/components/workspace/DatasetOnboarding";
import FixturePreview from "@/components/workspace/FixturePreview";
import RosterWorkbench from "@/components/workspace/RosterWorkbench";
import ResultsBoard from "@/components/workspace/ResultsBoard";
import { FIXTURES } from "@/lib/fixtures";
import { AttentionTarget, useWorkspace } from "@/lib/workspace";

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
  const [studentCount, setStudentCount] = useState<number | null>(null);
  const [deciding, setDeciding] = useState(false);

  const handleReady = useCallback(
    (info: DatasetReadyInfo) => {
      setStudentCount(info.studentCount);
      setDatasetReady(true);
      appendDatasetReady(info.studentCount, info.schoolCount, info.levelCount, info.warningCount, info.levelCounts);
      // Default constraints are seeded server-side once a dataset exists, so
      // the summary fetched at mount (before any dataset was loaded) is
      // stale -- refresh it now that there's something to count.
      void refreshConstraintsSummary();
    },
    [appendDatasetReady, refreshConstraintsSummary]
  );

  const handleWarning = useCallback((problems: string[]) => appendDataWarning(problems), [appendDataWarning]);

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

  const hasResult = timeline.some((item) => item.kind === "solve_result");
  const lastFailed = [...timeline].reverse().find((i) => i.kind === "solve_result" || i.kind === "solve_failure")?.kind === "solve_failure";
  const composerPlaceholder = hasResult ? "שאלו על השיבוץ או בקשו שינוי..." : "הוסיפו כלל או בקשו שינוי...";
  const composerSuggestions = lastFailed
    ? ["הצג את הכללים המתנגשים", "הקל על מכסת גודל הכיתה"]
    : hasResult
      ? ["בדוק בקשות חברות", "שפר איזון לימודי"]
      : [];

  if (fixtureName && FIXTURES[fixtureName]) {
    return <FixturePreview fixture={FIXTURES[fixtureName]} />;
  }

  if (!datasetReady) {
    return (
      <div className="ws-shell">
        <TopBar onRunSolve={() => {}} solving={false} canSolve={false} hasResult={false} />
        <DatasetOnboarding onReady={handleReady} onWarning={handleWarning} />
      </div>
    );
  }

  return (
    <>
      <WorkspaceShell
        topBar={
          <TopBar onRunSolve={runSolve} solving={solving} canSolve={datasetReady && !solving} hasResult={hasResult} />
        }
        conversation={
          <Conversation
            items={timeline}
            sending={sending}
            solving={solving}
            deciding={deciding}
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
          />
        }
      />
      <RosterWorkbench open={workbench === "roster"} onClose={() => setWorkbench(null)} />
      <ResultsBoard open={workbench === "results"} onClose={() => setWorkbench(null)} />
    </>
  );
}
