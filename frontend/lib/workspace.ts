"use client";

// The single place that turns backend API responses into "what artifact
// appears where." Every workspace action (send a message, confirm a
// proposal, run a solve, move a student) goes through here, appending a
// TimelineItem and/or changing InspectorState -- this is what keeps
// app/page.tsx from becoming a pile of booleans (showData/showResults/...).
//
// Timeline persistence: initialized from the backend's real chat history
// (/api/chat/history) on mount, so plain messages and any pending proposal
// survive a refresh. Richer typed events (solve results, manual moves) are
// client-side/ephemeral for this pass -- they narrate the current session,
// not a durable log; only the underlying constraint/assignment state they
// describe is actually persisted (by the backend, as always).

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ApiError,
  ChatMessage,
  GlobalMetrics,
  OptimizeResponse,
  PendingProposal,
  ResultState,
  SuggestedAction,
  confirmChatProposal,
  getChatHistory,
  getConstraints,
  getResultsMetrics,
  getResultState,
  rejectChatProposal,
  runOptimize,
  sendChatMessage,
} from "@/lib/api";

export type WorkspaceWorkbench = "roster" | "results" | null;

export type InspectorState =
  | { type: "overview" }
  | { type: "constraint"; id: string }
  | { type: "constraints" }
  | { type: "student"; id: number }
  | { type: "result"; classId?: number };

export type TimelineItem =
  | { id: string; kind: "user_message"; at: number; text: string }
  | { id: string; kind: "assistant_message"; at: number; text: string }
  | { id: string; kind: "dataset_ready"; at: number; studentCount: number; schoolCount: number; levelCount: number; warningCount: number; levelCounts: Record<string, number> }
  | { id: string; kind: "data_warning"; at: number; problems: string[] }
  | { id: string; kind: "constraint_proposal"; at: number; proposal: PendingProposal; status: "pending" | "confirmed" | "rejected" }
  | { id: string; kind: "constraint_event"; at: number; action: "applied" | "modified" | "removed"; label: string }
  // What the agent looked up before answering. Rendered as the quietest
  // timeline tier -- it's evidence the answer came from the data, not a
  // result in its own right.
  | { id: string; kind: "agent_steps"; at: number; tools: string[] }
  | { id: string; kind: "solve_result"; at: number; metrics: GlobalMetrics }
  | { id: string; kind: "solve_failure"; at: number; notes: string[]; explanation?: string | null; conflictingIds: string[]; repeat: boolean }
  | { id: string; kind: "manual_move"; at: number; studentName: string; from: number; to: number }
  | { id: string; kind: "reoptimization"; at: number; before?: number; after?: number };

export interface ConstraintsSummary {
  total: number;
  active: number;
  hard: number;
  soft: number;
}

/**
 * What the user is currently pointing at, shared across every surface so
 * hovering a class in the result artifact can light up the same class in
 * the inspector (and vice versa). Deliberately ephemeral -- this is a
 * pointing gesture, not a selection: `inspector` is what's *open*,
 * `highlight` is what's merely *under the cursor / referred to*.
 */
export type Highlight =
  | { kind: "class"; id: number }
  | { kind: "constraint"; id: string }
  | { kind: "student"; id: number }
  | null;

/** Where an attention observation points, so clicking one lands somewhere
 *  specific instead of dumping the user in a generic list. */
export type AttentionTarget = { kind: "class"; id: number } | { kind: "constraint"; id: string } | { kind: "constraints" };

export interface AttentionItem {
  text: string;
  target: AttentionTarget;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function useWorkspace() {
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [inspector, setInspector] = useState<InspectorState>({ type: "overview" });
  const [highlight, setHighlight] = useState<Highlight>(null);
  const [workbench, setWorkbench] = useState<WorkspaceWorkbench>(null);
  const [sending, setSending] = useState(false);
  const [solving, setSolving] = useState(false);
  const [constraintsSummary, setConstraintsSummary] = useState<ConstraintsSummary | null>(null);
  const [resultState, setResultState] = useState<ResultState | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestedAction[]>([]);
  // Bumped whenever anything the inspector panels read has changed on the
  // server: a rule confirmed, a checklist column added, the class count
  // set from chat. Panels take it as a `refreshKey` and re-fetch. This is
  // what makes the rules list update live instead of going stale until
  // the user happens to navigate away and back.
  const [dataVersion, setDataVersion] = useState(0);
  const bumpDataVersion = useCallback(() => setDataVersion((v) => v + 1), []);
  const loadedRef = useRef(false);

  const append = useCallback((item: TimelineItem) => {
    setTimeline((prev) => [...prev, item]);
  }, []);

  const refreshConstraintsSummary = useCallback(async () => {
    try {
      const r = await getConstraints();
      const active = r.constraints.filter((c) => c.active);
      setConstraintsSummary({
        total: r.constraints.length,
        active: active.length,
        hard: active.filter((c) => c.hard).length,
        soft: active.filter((c) => !c.hard).length,
      });
    } catch {
      // summary is a convenience for the top bar / overview -- never block on it
    }
  }, []);

  const refreshResultState = useCallback(async () => {
    try {
      setResultState(await getResultState());
    } catch {
      // The top-bar state is helpful but must not block the workspace.
    }
  }, []);

  const loadHistory = useCallback(async () => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    try {
      const r = await getChatHistory();
      const items: TimelineItem[] = r.messages.map((m: ChatMessage) => ({
        id: uid(),
        kind: m.role === "user" ? "user_message" : "assistant_message",
        at: Date.now(),
        text: m.content,
      }));
      if (r.pending_proposal) {
        items.push({ id: uid(), kind: "constraint_proposal", at: Date.now(), proposal: r.pending_proposal, status: "pending" });
      }
      setTimeline(items);
    } catch {
      // fresh session with no history yet -- fine, start empty
    }
    void refreshConstraintsSummary();
    void refreshResultState();
  }, [refreshConstraintsSummary, refreshResultState]);

  useEffect(() => {
    (async () => {
      await loadHistory();
    })();
  }, [loadHistory]);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || sending) return;
      append({ id: uid(), kind: "user_message", at: Date.now(), text: trimmed });
      setSending(true);
      try {
        const res = await sendChatMessage(trimmed);
        // The lookups land before the answer, in the order they happened --
        // the counselor sees the agent check the data, then speak.
        const tools = (res.steps ?? []).filter((s) => s.ok).map((s) => s.tool);
        if (tools.length > 0) {
          append({ id: uid(), kind: "agent_steps", at: Date.now(), tools });
        }
        // A planning tool wrote to the session (checklist column, class
        // count). Nothing else would tell the panels to re-read.
        if (res.state_changed) {
          bumpDataVersion();
          void refreshConstraintsSummary();
        }
        if (res.result_state) setResultState(res.result_state);
        setSuggestions(res.suggestions ?? []);
        if (res.pending_proposal) {
          append({ id: uid(), kind: "constraint_proposal", at: Date.now(), proposal: res.pending_proposal, status: "pending" });
        } else {
          append({ id: uid(), kind: "assistant_message", at: Date.now(), text: res.reply });
        }
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "לא הצלחתי לשלוח את ההודעה");
      } finally {
        setSending(false);
      }
    },
    [append, sending, bumpDataVersion, refreshConstraintsSummary]
  );

  const decideProposal = useCallback(
    async (itemId: string, decision: "confirm" | "reject") => {
      try {
        if (decision === "confirm") {
          const res = await confirmChatProposal();
          const result = res.result as { label_hebrew?: string } | undefined;
          setTimeline((prev) =>
            prev.map((it) => (it.id === itemId && it.kind === "constraint_proposal" ? { ...it, status: "confirmed" } : it))
          );
          append({ id: uid(), kind: "constraint_event", at: Date.now(), action: "applied", label: result?.label_hebrew ?? "הכלל עודכן" });
          bumpDataVersion();
          void refreshConstraintsSummary();
          void refreshResultState();
        } else {
          await rejectChatProposal();
          setTimeline((prev) =>
            prev.map((it) => (it.id === itemId && it.kind === "constraint_proposal" ? { ...it, status: "rejected" } : it))
          );
        }
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "לא הצלחתי לעדכן את ההצעה");
      }
    },
    [append, refreshConstraintsSummary, refreshResultState, bumpDataVersion]
  );

  const runSolve = useCallback(async () => {
    if (solving) return;
    setSolving(true);
    try {
      const res: OptimizeResponse = await runOptimize();
      if (res.result_state) setResultState(res.result_state);
      if (res.is_feasible) {
        const metrics = await getResultsMetrics();
        append({ id: uid(), kind: "solve_result", at: Date.now(), metrics });
        // Commentary follows the artifact, so the numbers land first and
        // the read of them second -- and it's simply absent when no LLM is
        // configured rather than showing a placeholder.
        if (res.result_comment) {
          append({ id: uid(), kind: "assistant_message", at: Date.now(), text: res.result_comment });
        }
      } else {
        const conflictingIds = res.conflicting_constraint_ids ?? [];
        // A repeat failure (same streak) collapses to a compact activity
        // line instead of re-rendering the full artifact -- checked against
        // the previous item at append time, not a separate tracked flag.
        setTimeline((prev) => {
          const last = prev[prev.length - 1];
          const repeat = last?.kind === "solve_failure";
          const next: TimelineItem[] = [
            ...prev,
            {
              id: uid(),
              kind: "solve_failure",
              at: Date.now(),
              notes: res.infeasibility_notes,
              explanation: res.infeasibility_explanation,
              conflictingIds,
              repeat,
            },
          ];
          // A dead end is the one place the product should offer a way
          // out: the backend stages a concrete relaxation, shown as the
          // same confirm/reject card a chat proposal uses.
          if (res.relaxation_proposal) {
            next.push({
              id: uid(),
              kind: "constraint_proposal",
              at: Date.now(),
              proposal: res.relaxation_proposal,
              status: "pending",
            });
          }
          return next;
        });
        void refreshConstraintsSummary();
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "לא הצלחתי ליצור את השיבוץ");
    } finally {
      setSolving(false);
    }
  }, [solving, append, refreshConstraintsSummary]);

  const appendDatasetReady = useCallback(
    (studentCount: number, schoolCount: number, levelCount: number, warningCount: number, levelCounts: Record<string, number>) =>
      append({ id: uid(), kind: "dataset_ready", at: Date.now(), studentCount, schoolCount, levelCount, warningCount, levelCounts }),
    [append]
  );

  const appendDataWarning = useCallback((problems: string[]) => append({ id: uid(), kind: "data_warning", at: Date.now(), problems }), [append]);

  /**
   * A run-parameter change logged as a rule change, which is what it
   * actually is: the class count drives the capacity rule's bounds
   * server-side (sync_class_size_bounds). Filing it as a `constraint_event`
   * gets it both a line in the activity log and -- because that is exactly
   * what the top bar's staleness check looks for -- an honest "the rules
   * moved since this result" state. Editing the class count on the main
   * surface without that would silently invalidate the result on screen.
   */
  const appendRunConfigChange = useCallback(
    (label: string) => append({ id: uid(), kind: "constraint_event", at: Date.now(), action: "modified", label }),
    [append]
  );

  const appendManualMove = useCallback(
    (studentName: string, from: number, to: number) => append({ id: uid(), kind: "manual_move", at: Date.now(), studentName, from, to }),
    [append]
  );

  const appendReoptimization = useCallback(
    (before?: number, after?: number) => append({ id: uid(), kind: "reoptimization", at: Date.now(), before, after }),
    [append]
  );

  return {
    timeline,
    setTimeline,
    inspector,
    setInspector,
    highlight,
    setHighlight,
    workbench,
    setWorkbench,
    sending,
    solving,
    constraintsSummary,
    resultState,
    suggestions,
    refreshConstraintsSummary,
    refreshResultState,
    dataVersion,
    bumpDataVersion,
    sendMessage,
    decideProposal,
    runSolve,
    appendDatasetReady,
    appendDataWarning,
    appendManualMove,
    appendReoptimization,
    appendRunConfigChange,
  };
}

export type Workspace = ReturnType<typeof useWorkspace>;
