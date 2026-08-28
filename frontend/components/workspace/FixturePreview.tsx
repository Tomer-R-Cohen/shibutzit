"use client";

import { useCallback, useState } from "react";
import WorkspaceShell from "./WorkspaceShell";
import TopBar from "./TopBar";
import Conversation from "./Conversation";
import ContextInspector, { ContextInspectorWorkspace } from "./ContextInspector";
import { Fixture } from "@/lib/fixtures";
import { Highlight, InspectorState, TimelineItem } from "@/lib/workspace";

// Dev-only, offline rendering of a hand-written Fixture -- no network calls
// (aside from ConstraintBrowser/ConstraintInspector, which still talk to a
// real backend if one happens to be running; the rest of the loop, notably
// constraint_proposal confirm/reject, is fully local so LLM-gated states are
// screenshot-verifiable without an API key). See lib/fixtures.ts.
export default function FixturePreview({ fixture }: { fixture: Fixture }) {
  const [timeline, setTimeline] = useState<TimelineItem[]>(fixture.timeline);
  const [inspector, setInspector] = useState<InspectorState>({ type: "overview" });
  const [highlight, setHighlight] = useState<Highlight>(null);
  const [deciding, setDeciding] = useState(false);

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
    dataVersion: 0,
    bumpDataVersion: () => {},
  };

  return (
    <WorkspaceShell
      topBar={
        <TopBar
          onRunSolve={() => {}}
          canSolve={fixture.studentCount != null}
          runState={timeline.some((item) => item.kind === "solve_result") ? "fresh" : "none"}
        />
      }
      conversation={
        <Conversation
          items={timeline}
          sending={false}
          solving={false}
          deciding={deciding}
          studentCount={fixture.studentCount}
          onSend={() => {}}
          onConfirmProposal={(id) => decideProposal(id, "confirm")}
          onRejectProposal={(id) => decideProposal(id, "reject")}
          onOpenRoster={() => {}}
          onOpenResults={() => {}}
          onOpenConstraints={() => setInspector({ type: "constraints" })}
          onOpenConstraint={(id) => setInspector({ type: "constraint", id })}
          composerPlaceholder="הוסיפו כלל או בקשו שינוי..."
          composerSuggestions={[
            { label: "בדוק בקשות חברות", message: "בדוק את המענה לבקשות החברות בשיבוץ." },
            { label: "שיפור האיזון הלימודי", message: "בדקי איך אפשר לשפר את האיזון הלימודי." },
          ]}
          highlight={highlight}
          onHighlight={setHighlight}
          onAttentionTarget={(t) => {
            if (t.kind === "constraint") setInspector({ type: "constraint", id: t.id });
            else if (t.kind === "constraints") setInspector({ type: "constraints" });
            else setHighlight({ kind: "class", id: t.id });
          }}
        />
      }
      inspector={
        <ContextInspector
          workspace={inspectorWorkspace}
          studentCount={fixture.studentCount}
          highlight={highlight}
          onHighlight={setHighlight}
        />
      }
    />
  );
}
