"use client";

import { AttentionTarget, Highlight, TimelineItem } from "@/lib/workspace";
import { AssistantMessage, ThinkingIndicator, UserMessage } from "./timeline-items/Messages";
import { DataWarningArtifact, DatasetReadyArtifact } from "./timeline-items/DatasetReadyArtifact";
import { ConstraintProposalArtifact } from "./timeline-items/ConstraintProposalArtifact";
import { ConstraintEvent } from "./timeline-items/ConstraintEvent";
import { SolveFailureArtifact, SolveResultArtifact, SolveStartedArtifact } from "./timeline-items/SolveArtifacts";
import { AgentStepsEvent, ManualMoveEvent, ReoptimizationEvent } from "./timeline-items/ActivityEvents";

/**
 * Renders TimelineItem[] to dedicated components -- no arbitrary markup,
 * no generic chat-bubble catch-all. The item's `kind` fully determines
 * what appears; this is the "structured artifacts, not endless chat
 * bubbles" rule made concrete.
 */
export default function Timeline({
  items,
  sending,
  solving,
  deciding,
  onConfirmProposal,
  onRejectProposal,
  onOpenRoster,
  onOpenResults,
  onOpenConstraints,
  onOpenConstraint,
  highlight,
  onHighlight,
  onAttentionTarget,
}: {
  items: TimelineItem[];
  sending: boolean;
  solving: boolean;
  deciding: boolean;
  onConfirmProposal: (id: string) => void;
  onRejectProposal: (id: string) => void;
  onOpenRoster: () => void;
  onOpenResults: () => void;
  onOpenConstraints: () => void;
  onOpenConstraint: (id: string) => void;
  highlight: Highlight;
  onHighlight: (h: Highlight) => void;
  onAttentionTarget: (t: AttentionTarget) => void;
}) {
  // "latest of its kind" drives auto-collapse: only the newest solve
  // result / failure stays expanded, older ones fold into history.
  const lastResultId = [...items].reverse().find((i) => i.kind === "solve_result")?.id ?? null;
  const lastFailureId = [...items].reverse().find((i) => i.kind === "solve_failure" && !i.repeat)?.id ?? null;

  return (
    <>
      {items.map((item) => {
        switch (item.kind) {
          case "user_message":
            return <UserMessage key={item.id} text={item.text} />;
          case "assistant_message":
            return <AssistantMessage key={item.id} text={item.text} />;
          case "dataset_ready":
            return (
              <DatasetReadyArtifact
                key={item.id}
                studentCount={item.studentCount}
                schoolCount={item.schoolCount}
                levelCount={item.levelCount}
                warningCount={item.warningCount}
                levelCounts={item.levelCounts}
                onOpenRoster={onOpenRoster}
              />
            );
          case "data_warning":
            return <DataWarningArtifact key={item.id} problems={item.problems} />;
          case "constraint_proposal":
            return (
              <ConstraintProposalArtifact
                key={item.id}
                proposal={item.proposal}
                status={item.status}
                deciding={deciding}
                onConfirm={() => onConfirmProposal(item.id)}
                onReject={() => onRejectProposal(item.id)}
              />
            );
          case "constraint_event":
            return <ConstraintEvent key={item.id} action={item.action} label={item.label} at={item.at} />;
          case "agent_steps":
            return <AgentStepsEvent key={item.id} tools={item.tools} at={item.at} />;
          case "solve_result":
            return (
              <SolveResultArtifact
                key={item.id}
                metrics={item.metrics}
                latest={item.id === lastResultId}
                highlight={highlight}
                onHighlight={onHighlight}
                onOpenResults={onOpenResults}
                onOpenConstraints={onOpenConstraints}
                onAttentionTarget={onAttentionTarget}
              />
            );
          case "solve_failure":
            return (
              <SolveFailureArtifact
                key={item.id}
                notes={item.notes}
                explanation={item.explanation}
                conflictingIds={item.conflictingIds}
                repeat={item.repeat}
                at={item.at}
                latest={item.id === lastFailureId}
                highlight={highlight}
                onHighlight={onHighlight}
                onOpenConstraints={onOpenConstraints}
                onOpenConstraint={onOpenConstraint}
              />
            );
          case "manual_move":
            return <ManualMoveEvent key={item.id} studentName={item.studentName} from={item.from} to={item.to} at={item.at} />;
          case "reoptimization":
            return <ReoptimizationEvent key={item.id} before={item.before} after={item.after} at={item.at} />;
          default:
            return null;
        }
      })}
      {sending && <ThinkingIndicator />}
      {solving && <SolveStartedArtifact />}
    </>
  );
}
