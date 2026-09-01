"use client";

import { AttentionTarget, Highlight, RosterFocus, TimelineItem } from "@/lib/workspace";
import { AssistantMessage, ThinkingIndicator, UserMessage } from "./timeline-items/Messages";
import { DataWarningArtifact, DatasetReadyArtifact } from "./timeline-items/DatasetReadyArtifact";
import { ConstraintProposalArtifact } from "./timeline-items/ConstraintProposalArtifact";
import { ConstraintEvent } from "./timeline-items/ConstraintEvent";
import { SolveFailureArtifact, SolveResultArtifact, SolveStartedArtifact } from "./timeline-items/SolveArtifacts";
import { AgentStepsEvent, ChatErrorArtifact, FinalApprovalEvent, ManualMoveEvent, ReoptimizationEvent, SolveComparisonArtifact, SolveErrorArtifact, VersionRestoreEvent } from "./timeline-items/ActivityEvents";

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
  onOpenHistory,
  onRetryMessage,
  onRetrySolve,
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
  onOpenRoster: (focus?: RosterFocus) => void;
  onOpenResults: () => void;
  onOpenConstraints: () => void;
  onOpenConstraint: (id: string) => void;
  onOpenHistory: () => void;
  onRetryMessage: (errorId: string, text: string) => void;
  onRetrySolve: (errorId: string) => void;
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
            return <AssistantMessage key={item.id} text={item.text} streaming={item.streaming} />;
          case "dataset_ready":
            return (
              <DatasetReadyArtifact
                key={item.id}
                studentCount={item.studentCount}
                schoolCount={item.schoolCount}
                levelCount={item.levelCount}
                warningCount={item.warningCount}
                levelCounts={item.levelCounts}
                detectedFields={item.detectedFields}
                missingFields={item.missingFields}
                friendshipCount={item.friendshipCount}
                onOpenRoster={onOpenRoster}
              />
            );
          case "data_warning":
            return <DataWarningArtifact key={item.id} problems={item.problems} onOpenRoster={onOpenRoster} />;
          case "constraint_proposal":
            return (
              <ConstraintProposalArtifact
                key={item.id}
                proposal={item.proposal}
                status={item.status}
                error={item.error}
                deciding={deciding}
                onConfirm={() => onConfirmProposal(item.id)}
                onReject={() => onRejectProposal(item.id)}
              />
            );
          case "constraint_event":
            return <ConstraintEvent key={item.id} action={item.action} label={item.label} at={item.at} />;
          case "agent_steps":
            return <AgentStepsEvent key={item.id} tools={item.tools} at={item.at} onOpenResults={onOpenResults} />;
          case "solve_result":
            return (
              <SolveResultArtifact
                key={item.id}
                metrics={item.metrics}
                version={item.version}
                latest={item.id === lastResultId}
                highlight={highlight}
                onHighlight={onHighlight}
                onOpenResults={onOpenResults}
                onOpenConstraints={onOpenConstraints}
                onAttentionTarget={onAttentionTarget}
              />
            );
          case "solve_comparison":
            return <SolveComparisonArtifact key={item.id} {...item} onOpenResults={onOpenResults} onOpenHistory={onOpenHistory} />;
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
          case "version_restore":
            return <VersionRestoreEvent key={item.id} version={item.version} reason={item.reason} at={item.at} />;
          case "reoptimization":
            return <ReoptimizationEvent key={item.id} before={item.before} after={item.after} at={item.at} />;
          case "final_approval":
            return <FinalApprovalEvent key={item.id} exported={item.exported} at={item.at} />;
          case "chat_error":
            return (
              <ChatErrorArtifact
                key={item.id}
                message={item.message}
                retryable={item.retryable}
                onRetry={() => onRetryMessage(item.id, item.retryText)}
                onReview={onOpenHistory}
              />
            );
          case "solve_error":
            return (
              <SolveErrorArtifact
                key={item.id}
                message={item.message}
                retryable={item.retryable}
                completedVersions={item.completedVersions}
                onRetry={() => onRetrySolve(item.id)}
                onReview={onOpenResults}
              />
            );
          default:
            return null;
        }
      })}
      {sending && !items.some((item) => item.kind === "assistant_message" && item.streaming) && <ThinkingIndicator />}
      {solving && <SolveStartedArtifact />}
    </>
  );
}
