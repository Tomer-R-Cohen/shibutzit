"use client";

import { useCallback, useState } from "react";
import WorkspaceShell from "./WorkspaceShell";
import TopBar from "./TopBar";
import Conversation from "./Conversation";
import ContextInspector, { ContextInspectorWorkspace } from "./ContextInspector";
import { Fixture } from "@/lib/fixtures";
import { Highlight, InspectorState, TimelineItem } from "@/lib/workspace";
import ResultsBoard from "./ResultsBoard";
import RosterWorkbench from "./RosterWorkbench";

// Dev-only, offline rendering of a hand-written Fixture -- no network calls
// (including ConstraintBrowser/ConstraintInspector; the rest of the loop, notably
// constraint_proposal confirm/reject, is fully local so LLM-gated states are
// screenshot-verifiable without an API key). See lib/fixtures.ts.
export default function FixturePreview({ fixture }: { fixture: Fixture }) {
  const hasDataset = fixture.studentCount != null;
  const [timeline, setTimeline] = useState<TimelineItem[]>(fixture.timeline);
  const [inspector, setInspector] = useState<InspectorState>(fixture.inspectorPreview?.initial ?? { type: "overview" });
  const [highlight, setHighlight] = useState<Highlight>(null);
  const [deciding, setDeciding] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(fixture.inspectorPreview?.open ?? false);

  function showInspector(state: InspectorState) {
    setInspector(state);
    if (window.matchMedia("(max-width: 900px)").matches) setInspectorOpen(true);
  }

  const decideProposal = useCallback((itemId: string, decision: "confirm" | "reject") => {
    setDeciding(true);
    setTimeout(() => {
      setTimeline((prev) => {
        const next = prev.map((it) =>
          it.id === itemId && it.kind === "constraint_proposal" ? { ...it, status: decision === "confirm" ? ("confirmed" as const) : ("rejected" as const) } : it
        );
        if (decision === "confirm") {
          const item = prev.find((it) => it.id === itemId);
          if (item && item.kind === "constraint_proposal") {
            next.push({
              id: `fx-event-${itemId}`,
              kind: "constraint_event",
              at: Date.now(),
              action: item.proposal.kind === "propose" ? "applied" : item.proposal.kind === "modify" ? "modified" : "removed",
              label: item.proposal.constraint?.label_hebrew ?? item.proposal.summary_hebrew,
            });
          }
        }
        return next;
      });
      setDeciding(false);
    }, 250);
  }, []);

  const inspectorWorkspace: ContextInspectorWorkspace = {
    inspector,
    setInspector,
    constraintsSummary: fixture.constraintsSummary,
    refreshConstraintsSummary: async () => {},
    refreshResultState: async () => {},
    appendRunConfigChange: () => {},
    appendVersionRestore: () => {},
    dataVersion: 0,
    bumpDataVersion: () => {},
  };

  return (
    <>
    <WorkspaceShell
      inspectorVisible={hasDataset}
      inspectorOpen={inspectorOpen}
      onCloseInspector={() => setInspectorOpen(false)}
      topBar={
        <TopBar
          onRunSolve={() => {}}
          canSolve={hasDataset}
          runState={timeline.some((item) => item.kind === "solve_result") ? "fresh" : "none"}
          onUploadData={!hasDataset ? () => {} : undefined}
          inspectorOpen={inspectorOpen}
          onToggleInspector={hasDataset ? () => setInspectorOpen((open) => !open) : undefined}
          onStartOver={() => {}}
        />
      }
      conversation={
        <Conversation
          items={timeline}
          sending={false}
          solving={false}
          solverVisualActive={false}
          deciding={deciding}
          studentCount={fixture.studentCount}
          onSend={() => {}}
          onConfirmProposal={(id) => decideProposal(id, "confirm")}
          onRejectProposal={(id) => decideProposal(id, "reject")}
          onOpenRoster={() => {}}
          onOpenResults={() => {}}
          onOpenConstraints={() => showInspector({ type: "constraints" })}
          onOpenConstraint={(id) => showInspector({ type: "constraint", id })}
          onOpenHistory={() => showInspector({ type: "overview" })}
          onRetryMessage={() => {}}
          onRetrySolve={() => {}}
          composerPlaceholder="הוסיפו כלל או בקשו שינוי..."
          composerSuggestions={[
            { label: "בדוק בקשות חברות", message: "בדוק את המענה לבקשות החברות בשיבוץ." },
            { label: "שיפור האיזון הלימודי", message: "בדקי איך אפשר לשפר את האיזון הלימודי." },
          ]}
          highlight={highlight}
          onHighlight={setHighlight}
          onAttentionTarget={(t) => {
            if (t.kind === "constraint") showInspector({ type: "constraint", id: t.id });
            else if (t.kind === "constraints") showInspector({ type: "constraints" });
            else setHighlight({ kind: "class", id: t.id });
          }}
        />
      }
      inspector={
        <ContextInspector
          workspace={inspectorWorkspace}
          studentCount={fixture.studentCount}
          onOpenResults={() => {}}
          highlight={highlight}
          onHighlight={setHighlight}
          sheetOpen={inspectorOpen}
          onCloseSheet={() => setInspectorOpen(false)}
          overviewPreview={fixture.overviewPreview}
          constraintPreview={fixture.inspectorPreview?.constraints}
        />
      }
    />
    {fixture.classReview && (
      <ResultsBoard
        open
        onClose={() => {}}
        onAskAI={() => {}}
        fixtureData={fixture.classReview}
      />
    )}
    {(fixture.rosterReview || fixture.rosterError || fixture.rosterSaveError) && (
      <RosterWorkbench open onClose={() => {}} fixtureData={fixture.rosterReview} fixtureError={fixture.rosterError} fixtureSaveError={fixture.rosterSaveError} />
    )}
    </>
  );
}
