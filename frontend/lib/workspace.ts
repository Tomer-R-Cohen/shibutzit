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
  getResultsStudents,
  getResultState,
  getVersions,
  rejectChatProposal,
  runOptimize,
  streamChatMessage,
  streamAfterSolver,
} from "@/lib/api";

export type WorkspaceWorkbench = "roster" | "results" | null;

export type RosterCorrectionField = "current_school" | "academic_level";
export interface RosterFocus {
  studentIds: number[];
  fields: RosterCorrectionField[];
}
export interface DataProblem {
  message: string;
  studentIds?: number[];
  field?: RosterCorrectionField;
}

export type InspectorState =
  | { type: "overview" }
  | { type: "constraint"; id: string }
  | { type: "constraints" }
  | { type: "student"; id: number }
  | { type: "result"; classId?: number };

export type TimelineItem =
  | { id: string; kind: "user_message"; at: number; text: string }
  | { id: string; kind: "assistant_message"; at: number; text: string; streaming?: boolean }
  | { id: string; kind: "dataset_ready"; at: number; studentCount: number; schoolCount: number; levelCount: number; warningCount: number; levelCounts: Record<string, number>; detectedFields: string[]; missingFields: string[]; friendshipCount: number }
  | { id: string; kind: "data_warning"; at: number; problems: DataProblem[] }
  | { id: string; kind: "constraint_proposal"; at: number; proposal: PendingProposal; status: "pending" | "confirmed" | "rejected"; error?: string }
  | { id: string; kind: "constraint_event"; at: number; action: "applied" | "modified" | "removed"; label: string }
  // What the agent looked up before answering. Rendered as the quietest
  // timeline tier -- it's evidence the answer came from the data, not a
  // result in its own right.
  | { id: string; kind: "agent_steps"; at: number; tools: string[] }
  | { id: string; kind: "solve_result"; at: number; metrics: GlobalMetrics; version?: number }
  | { id: string; kind: "solve_comparison"; at: number; fromVersion: number; toVersion: number; before: GlobalMetrics; after: GlobalMetrics; movedStudents: number }
  | { id: string; kind: "solve_failure"; at: number; notes: string[]; explanation?: string | null; conflictingIds: string[]; repeat: boolean }
  | { id: string; kind: "manual_move"; at: number; studentName: string; from: number; to: number }
  | { id: string; kind: "version_restore"; at: number; version: number; reason: string }
  | { id: string; kind: "reoptimization"; at: number; before?: number; after?: number }
  | { id: string; kind: "final_approval"; at: number; exported: boolean }
  | { id: string; kind: "solve_error"; at: number; message: string; retryable: boolean; completedVersions: number }
  | { id: string; kind: "chat_error"; at: number; message: string; retryText: string; retryable: boolean };

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

const SAFE_RETRY_TOOL_PREFIXES = ["get_", "analyze_", "query_", "compare_", "explain_", "simulate_", "inspect_"];
function toolIsSafeToRetry(name: string): boolean {
  return SAFE_RETRY_TOOL_PREFIXES.some((prefix) => name.startsWith(prefix));
}

export function useWorkspace() {
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [historyReady, setHistoryReady] = useState(false);
  const [inspector, setInspector] = useState<InspectorState>({ type: "overview" });
  const [highlight, setHighlight] = useState<Highlight>(null);
  const [workbench, setWorkbench] = useState<WorkspaceWorkbench>(null);
  const [sending, setSending] = useState(false);
  const [solving, setSolving] = useState(false);
  // `solving` guards the full orchestration request. This narrower state
  // controls only the visual solver artifact, which must disappear as soon
  // as the first real result/failure is rendered (before AI narration).
  const [solverVisualActive, setSolverVisualActive] = useState(false);
  const [constraintsSummary, setConstraintsSummary] = useState<ConstraintsSummary | null>(null);
  const [resultState, setResultState] = useState<ResultState | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestedAction[]>([]);
  const [solverRunRequested, setSolverRunRequested] = useState(0);
  // Bumped whenever anything the inspector panels read has changed on the
  // server: a rule confirmed, a checklist column added, the class count
  // set from chat. Panels take it as a `refreshKey` and re-fetch. This is
  // what makes the rules list update live instead of going stale until
  // the user happens to navigate away and back.
  const [dataVersion, setDataVersion] = useState(0);
  const bumpDataVersion = useCallback(() => setDataVersion((v) => v + 1), []);
  const loadedRef = useRef(false);
  const lastRunRef = useRef<{ metrics: GlobalMetrics; assignments: Record<number, number>; version: number } | null>(null);

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
    } finally {
      setHistoryReady(true);
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
    async (text: string, options?: { appendUser?: boolean }) => {
      const trimmed = text.trim();
      if (!trimmed || sending) return;
      if (options?.appendUser !== false) append({ id: uid(), kind: "user_message", at: Date.now(), text: trimmed });
      setSending(true);
      const streamingId = uid();
      let hasStreamingMessage = false;
      const streamedTools = new Set<string>();
      try {
        const res = await streamChatMessage(trimmed, {
          onDelta: (delta) => {
            if (!hasStreamingMessage) {
              hasStreamingMessage = true;
              append({ id: streamingId, kind: "assistant_message", at: Date.now(), text: delta, streaming: true });
            } else {
              setTimeline((prev) =>
                prev.map((item) =>
                  item.id === streamingId && item.kind === "assistant_message" ? { ...item, text: item.text + delta } : item
                )
              );
            }
          },
          onTool: (step) => {
            if (!step.ok) return;
            streamedTools.add(step.tool);
            append({ id: uid(), kind: "agent_steps", at: Date.now(), tools: [step.tool] });
          },
        });
        // The lookups land before the answer, in the order they happened --
        // the counselor sees the agent check the data, then speak.
        const tools = (res.steps ?? []).filter((s) => s.ok && !streamedTools.has(s.tool)).map((s) => s.tool);
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
        if (res.solver_run_requested) setSolverRunRequested(Math.max(1, Math.min(3, res.solver_run_count ?? 1)));
        setSuggestions(res.suggestions ?? []);
        if (res.pending_proposal) {
          if (hasStreamingMessage) setTimeline((prev) => prev.filter((item) => item.id !== streamingId));
          append({ id: uid(), kind: "constraint_proposal", at: Date.now(), proposal: res.pending_proposal, status: "pending" });
        } else {
          if (hasStreamingMessage) {
            setTimeline((prev) =>
              prev.map((item) =>
                item.id === streamingId && item.kind === "assistant_message"
                  ? { ...item, text: res.reply, streaming: false }
                  : item
              )
            );
          } else {
            append({ id: uid(), kind: "assistant_message", at: Date.now(), text: res.reply });
          }
        }
      } catch (err) {
        if (hasStreamingMessage) setTimeline((prev) => prev.filter((item) => item.id !== streamingId));
        append({
          id: uid(),
          kind: "chat_error",
          at: Date.now(),
          message: err instanceof ApiError ? err.message : "החיבור לעוזרת נקטע לפני שהתקבלה תשובה מלאה.",
          retryText: trimmed,
          retryable: [...streamedTools].every(toolIsSafeToRetry),
        });
      } finally {
        setSending(false);
      }
    },
    [append, sending, bumpDataVersion, refreshConstraintsSummary]
  );

  const decideProposal = useCallback(
    async (itemId: string, decision: "confirm" | "reject") => {
      try {
        setTimeline((prev) =>
          prev.map((it) => (it.id === itemId && it.kind === "constraint_proposal" ? { ...it, error: undefined } : it))
        );
        if (decision === "confirm") {
          const res = await confirmChatProposal();
          const result = res.result as { label_hebrew?: string } | undefined;
          setTimeline((prev) =>
            prev.map((it) => (it.id === itemId && it.kind === "constraint_proposal" ? { ...it, status: "confirmed" } : it))
          );
          if (res.action_kind) {
            append({
              id: uid(),
              kind: "assistant_message",
              at: Date.now(),
              text: res.confirmation_message ?? "שינוי השיבוץ אושר ועודכן.",
            });
          } else {
            append({ id: uid(), kind: "constraint_event", at: Date.now(), action: "applied", label: result?.label_hebrew ?? "הכלל עודכן" });
          }
          if (res.result_state) setResultState(res.result_state);
          if (res.solver_run_requested) setSolverRunRequested(1);
          bumpDataVersion();
          void refreshConstraintsSummary();
          void refreshResultState();
        } else {
          await rejectChatProposal();
          setTimeline((prev) =>
            prev.map((it) => (it.id === itemId && it.kind === "constraint_proposal" ? { ...it, status: "rejected" } : it))
          );
          bumpDataVersion();
        }
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "לא הצלחתי לעדכן את ההצעה";
        setTimeline((prev) =>
          prev.map((it) => (it.id === itemId && it.kind === "constraint_proposal" ? { ...it, error: message } : it))
        );
      }
    },
    [append, refreshConstraintsSummary, refreshResultState, bumpDataVersion]
  );

  // Generate a small portfolio by default, even when the coordinator only
  // clicks "solve" once. Explicit conversational requests can still choose
  // a bounded count below.
  const runSolve = useCallback(async (requestedAlternatives = 3) => {
    if (solving) return;
    setSolving(true);
    setSolverVisualActive(true);
    let startingVersionId: string | null | undefined;
    const createdVersionIds: string[] = [];
    try {
      // A restore or a manual edit can change the authoritative current
      // assignment without remounting this hook. Snapshot that server state
      // before the solver overwrites it, otherwise the comparison can count
      // moves against an older in-memory run and report the wrong tradeoff.
      try {
        const versions = await getVersions();
        startingVersionId = versions.current_version_id;
        const current = versions.versions.find((version) => version.id === versions.current_version_id);
        if (current) {
          const [metrics, students] = await Promise.all([getResultsMetrics(), getResultsStudents()]);
          const assignments: Record<number, number> = {};
          for (const row of students.rows) {
            const id = Number(row["מזהה"]);
            const cls = Number(row["כיתה משובצת"]);
            if (Number.isFinite(id) && Number.isFinite(cls)) assignments[id] = cls;
          }
          lastRunRef.current = { metrics, assignments, version: current.number };
        } else {
          lastRunRef.current = null;
        }
      } catch {
        // A transient history read must not prevent solving. The existing
        // in-memory baseline is still preferable to omitting all comparison.
      }
      const alternatives = Math.max(1, Math.min(3, requestedAlternatives));
      let fallbackComment: string | null = null;
      for (let optionIndex = 0; optionIndex < alternatives; optionIndex++) {
        const res: OptimizeResponse = await runOptimize(optionIndex > 0, optionIndex === alternatives - 1);
        if (res.result_state) setResultState(res.result_state);
        if (res.no_distinct_alternative) break;
        if (res.is_feasible) {
        const [metrics, students] = await Promise.all([getResultsMetrics(), getResultsStudents()]);
        const assignments: Record<number, number> = {};
        for (const row of students.rows) {
          const id = Number(row["מזהה"]);
          const cls = Number(row["כיתה משובצת"]);
          if (Number.isFinite(id) && Number.isFinite(cls)) assignments[id] = cls;
        }
        const previous = lastRunRef.current;
        const version = res.version?.number ?? (previous?.version ?? 0) + 1;
        if (res.version?.id) createdVersionIds.push(res.version.id);
        append({ id: uid(), kind: "solve_result", at: Date.now(), metrics, version });
        setSolverVisualActive(false);
        if (previous) {
          const movedStudents = Object.entries(assignments).filter(([id, cls]) => previous.assignments[Number(id)] !== cls).length;
          append({ id: uid(), kind: "solve_comparison", at: Date.now(), fromVersion: previous.version, toVersion: version, before: previous.metrics, after: metrics, movedStudents });
        }
        lastRunRef.current = { metrics, assignments, version };
        bumpDataVersion();
        // Factual commentary follows the structured result, so the evidence
        // lands before the conversational read of it.
        if (res.result_comment) fallbackComment = res.result_comment;
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
        setSolverVisualActive(false);
        void refreshConstraintsSummary();
        break;
        }
      }
      if (createdVersionIds.length > 0) {
        const followupId = uid();
        const streamedFollowupTools = new Set<string>();
        append({ id: followupId, kind: "assistant_message", at: Date.now(), text: "", streaming: true });
        try {
          const followup = await streamAfterSolver(createdVersionIds, {
            onDelta: (delta) =>
              setTimeline((prev) =>
                prev.map((item) =>
                  item.id === followupId && item.kind === "assistant_message" ? { ...item, text: item.text + delta } : item
                )
              ),
            onTool: (step) => {
              if (!step.ok) return;
              streamedFollowupTools.add(step.tool);
              append({ id: uid(), kind: "agent_steps", at: Date.now(), tools: [step.tool] });
            },
          });
          const tools = (followup.steps ?? [])
            .filter((step) => step.ok && !streamedFollowupTools.has(step.tool))
            .map((step) => step.tool);
          if (tools.length > 0) append({ id: uid(), kind: "agent_steps", at: Date.now(), tools });
          setTimeline((prev) =>
            prev.map((item) =>
              item.id === followupId && item.kind === "assistant_message"
                ? { ...item, text: followup.reply, streaming: false }
                : item
            )
          );
          setSuggestions(followup.suggestions ?? []);
        } catch {
          // A configured AI adds the contextual comparison. The measured
          // solver summary remains a complete fallback for local installs.
          setTimeline((prev) => prev.filter((item) => item.id !== followupId));
          if (fallbackComment) append({ id: uid(), kind: "assistant_message", at: Date.now(), text: fallbackComment });
        }
      }
    } catch (err) {
      // A timed-out request can still have finished on the server. Never
      // offer a blind retry until we have reconciled the authoritative
      // version history, otherwise one click can silently create two runs.
      setSolverVisualActive(false);
      const message = err instanceof ApiError ? err.message : "לא הצלחתי להשלים את יצירת השיבוץ";
      try {
        const versions = await getVersions();
        const current = versions.versions.find((version) => version.id === versions.current_version_id);
        const currentWasAlreadyRendered = current ? createdVersionIds.includes(current.id) : false;

        if (current && startingVersionId !== undefined && current.id !== startingVersionId && !currentWasAlreadyRendered) {
          const [metrics, students] = await Promise.all([getResultsMetrics(), getResultsStudents()]);
          const assignments: Record<number, number> = {};
          for (const row of students.rows) {
            const id = Number(row["מזהה"]);
            const cls = Number(row["כיתה משובצת"]);
            if (Number.isFinite(id) && Number.isFinite(cls)) assignments[id] = cls;
          }
          const previous = lastRunRef.current;
          append({ id: uid(), kind: "solve_result", at: Date.now(), metrics, version: current.number });
          if (previous && previous.version !== current.number) {
            const movedStudents = Object.entries(assignments).filter(([id, cls]) => previous.assignments[Number(id)] !== cls).length;
            append({ id: uid(), kind: "solve_comparison", at: Date.now(), fromVersion: previous.version, toVersion: current.number, before: previous.metrics, after: metrics, movedStudents });
          }
          lastRunRef.current = { metrics, assignments, version: current.number };
          append({
            id: uid(),
            kind: "assistant_message",
            at: Date.now(),
            text: `החיבור נקטע אחרי החישוב, אבל בדקתי את היסטוריית הפרויקט ואישרתי שגרסה ${current.number} נשמרה בהצלחה. התוצאה שמוצגת כאן נלקחה מהמערכת ולא נוצרה מחדש.`,
          });
          bumpDataVersion();
          void refreshResultState();
        } else {
          append({
            id: uid(),
            kind: "solve_error",
            at: Date.now(),
            message,
            retryable: startingVersionId !== undefined && versions.current_version_id === startingVersionId && createdVersionIds.length === 0,
            completedVersions: createdVersionIds.length,
          });
          void refreshResultState();
        }
      } catch {
        append({ id: uid(), kind: "solve_error", at: Date.now(), message, retryable: false, completedVersions: createdVersionIds.length });
      }
    } finally {
      setSolverVisualActive(false);
      setSolving(false);
    }
  }, [solving, append, refreshConstraintsSummary, refreshResultState, bumpDataVersion]);

  const retrySolve = useCallback(
    (errorId: string) => {
      setTimeline((prev) => prev.filter((item) => item.id !== errorId));
      void runSolve();
    },
    [runSolve]
  );

  // The assistant can hand confirmed session inputs to the real solver when
  // the counselor explicitly asks in conversation. Keeping execution here
  // preserves the same progress and result artifacts as the visible button.
  useEffect(() => {
    if (solverRunRequested < 1 || solving) return;
    const id = window.setTimeout(() => {
      const requested = solverRunRequested;
      setSolverRunRequested(0);
      void runSolve(requested);
    }, 0);
    return () => window.clearTimeout(id);
  }, [solverRunRequested, solving, runSolve]);

  const appendDatasetReady = useCallback(
    (studentCount: number, schoolCount: number, levelCount: number, warningCount: number, levelCounts: Record<string, number>, detectedFields: string[], missingFields: string[], friendshipCount: number) => {
      append({ id: uid(), kind: "dataset_ready", at: Date.now(), studentCount, schoolCount, levelCount, warningCount, levelCounts, detectedFields, missingFields, friendshipCount });
      append({ id: uid(), kind: "assistant_message", at: Date.now(), text: `מצאתי ${studentCount} תלמידות והנתונים מוכנים לעבודה. לכמה כיתות תרצו לחלק אותן?` });
    },
    [append]
  );

  const retryMessage = useCallback(
    (errorId: string, text: string) => {
      setTimeline((prev) => prev.filter((item) => item.id !== errorId));
      void sendMessage(text, { appendUser: false });
    },
    [sendMessage]
  );

  const appendDataWarning = useCallback((problems: DataProblem[]) => append({ id: uid(), kind: "data_warning", at: Date.now(), problems }), [append]);

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

  const appendVersionRestore = useCallback(
    (version: number, reason: string) => append({ id: uid(), kind: "version_restore", at: Date.now(), version, reason }),
    [append]
  );

  const appendReoptimization = useCallback(
    (before?: number, after?: number) => append({ id: uid(), kind: "reoptimization", at: Date.now(), before, after }),
    [append]
  );

  const appendFinalApproval = useCallback(
    (exported: boolean) => append({ id: uid(), kind: "final_approval", at: Date.now(), exported }),
    [append]
  );

  return {
    timeline,
    setTimeline,
    historyReady,
    inspector,
    setInspector,
    highlight,
    setHighlight,
    workbench,
    setWorkbench,
    sending,
    solving,
    solverVisualActive,
    constraintsSummary,
    resultState,
    suggestions,
    refreshConstraintsSummary,
    refreshResultState,
    dataVersion,
    bumpDataVersion,
    sendMessage,
    retryMessage,
    retrySolve,
    decideProposal,
    runSolve,
    appendDatasetReady,
    appendDataWarning,
    appendManualMove,
    appendVersionRestore,
    appendReoptimization,
    appendFinalApproval,
    appendRunConfigChange,
  };
}

export type Workspace = ReturnType<typeof useWorkspace>;
