// Typed fetch client for the FastAPI backend.
// Session id is a per-browser random id sent via X-Session-Id, stored in
// localStorage so the backend's in-memory session state is preserved
// across page reloads within the wizard.

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

function getSessionId(): string {
  if (typeof window === "undefined") return "server";
  let id = window.localStorage.getItem("shibutz_session_id");
  if (!id) {
    id = crypto.randomUUID();
    window.localStorage.setItem("shibutz_session_id", id);
  }
  return id;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { params?: Record<string, string | number | boolean | undefined> }
): Promise<T> {
  const sid = getSessionId();
  let url = `${API_BASE}${path}`;
  if (init?.params) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(init.params)) {
      if (v !== undefined) qs.set(k, String(v));
    }
    const s = qs.toString();
    if (s) url += `?${s}`;
  }
  const headers: Record<string, string> = { "X-Session-Id": sid };
  if (init?.body && !(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(url, { ...init, headers: { ...headers, ...(init?.headers || {}) } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? JSON.stringify(j);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.blob()) as unknown as T;
}

export function resetSession() {
  const id = crypto.randomUUID();
  window.localStorage.setItem("shibutz_session_id", id);
  return request("/api/session", { method: "POST" });
}

export function ensureSession() {
  return request("/api/session", { method: "POST" });
}

// Clears the current session's loaded data + persisted state (keeps the id).
export function clearSession() {
  return request("/api/session", { method: "POST" });
}

// ---- Step 1: load ----
export interface LoadWorkbookResponse {
  row_count: number;
  active_sheet: string;
  sheet_names: string[];
  notes: string[];
  columns: string[];
}
export function loadWorkbook(opts: {
  useDefault: boolean;
  headerRow: number;
  firstDataRow: number;
  lastDataRow: number;
  file?: File;
}) {
  const params = {
    use_default: opts.useDefault,
    header_row: opts.headerRow,
    first_data_row: opts.firstDataRow,
    last_data_row: opts.lastDataRow,
  };
  if (opts.file) {
    const fd = new FormData();
    fd.append("file", opts.file);
    return request<LoadWorkbookResponse>("/api/workbook/load", { method: "POST", params, body: fd });
  }
  return request<LoadWorkbookResponse>("/api/workbook/load", { method: "POST", params });
}

// ---- Step 2: preview ----
export interface PreviewResponse {
  sheet_names: string[];
  columns: string[];
  total_rows: number;
  rows: Record<string, unknown>[];
}
export function getPreview() {
  return request<PreviewResponse>("/api/workbook/preview");
}

// ---- Step 3: mapping ----
export interface MappingGuessResponse {
  columns: string[];
  required_fields: string[];
  optional_fields: string[];
  labels: Record<string, string>;
  mapping: Record<string, string | null>;
  manual_fields: string[];
  problems: string[];
}
export function getMappingGuess() {
  return request<MappingGuessResponse>("/api/mapping/guess");
}
export function applyMapping(mapping: Record<string, string | null>, manualFields: string[]) {
  return request<{ student_count: number; manual_fields_needed: string[]; manual_entry: Record<string, unknown>[] }>(
    "/api/mapping/apply",
    { method: "POST", body: JSON.stringify({ mapping, manual_fields: manualFields }) }
  );
}
export function getManualEntry() {
  return request<{ rows: Record<string, unknown>[]; names: Record<string, string> }>("/api/mapping/manual-entry");
}
export interface StudentRecord {
  student_id: number;
  first_name?: string;
  last_name?: string;
  current_school?: string;
  current_class?: number | string | null;
  ethiopian_origin?: boolean;
  academic_level?: string;
  differential?: boolean;
  inclusion?: boolean;
  hamar?: boolean;
  friend_requests_raw?: string;
  _project_edited_fields?: string[];
  [key: string]: unknown;
}
export function getStudents() {
  return request<{ rows: StudentRecord[]; count: number }>("/api/students");
}
export function updateStudentData(studentId: number, field: "current_school" | "academic_level", value: string) {
  return request<{
    student_id: number;
    field: string;
    old_value: unknown;
    new_value: unknown;
    remaining_issues: number;
    result_state: ResultState;
  }>(`/api/students/${studentId}`, {
    method: "PATCH",
    body: JSON.stringify({ field, value }),
  });
}
export function updateManualEntry(rows: Record<string, unknown>[]) {
  return request<{ student_count: number; manual_entry: Record<string, unknown>[] }>("/api/mapping/manual-entry", {
    method: "POST",
    body: JSON.stringify({ rows }),
  });
}
export function importManualEntry(file: File) {
  const fd = new FormData();
  fd.append("file", file);
  return request<{ rows: Record<string, unknown>[] }>("/api/mapping/manual-entry/import", {
    method: "POST",
    body: fd,
  });
}

// ---- Step 4: validation / friendship ----
export interface ValidationResponse {
  has_errors: boolean;
  error_count: number;
  warning_count: number;
  issues: Record<string, unknown>[];
}
export function getValidation() {
  return request<ValidationResponse>("/api/validation");
}
export interface FriendshipDiagnostics {
  matched_count: number;
  unmatched_count: number;
  ambiguous_count: number;
  unmatched_rows: Record<string, unknown>[];
}
export function getFriendshipDiagnostics() {
  return request<FriendshipDiagnostics>("/api/friendship/diagnostics");
}

// ---- Step 5: feasibility ----
export interface FeasibilityResponse {
  total_students: number;
  ethiopian_count: number;
  differential_count: number;
  inclusion_count: number;
  hamar_count: number;
  current_class_distribution: Record<string, number>;
  all_feasible: boolean;
  findings: Record<string, unknown>[];
}
export function getFeasibility() {
  return request<FeasibilityResponse>("/api/feasibility");
}

// ---- Step 6: run parameters ----
// Every actual rule (including the built-in defaults) lives in the
// constraint list below -- this is just num_classes and the time budget.
export interface RunConfig {
  num_classes: number;
  denominator_all_students: boolean;
  mutual_target_pct: number;
  two_friends_target_pct: number;
  time_limit_seconds: number;
  /**
   * Round-tripped, never rendered and never edited. The seed exists so that
   * identical inputs produce an identical assignment; exposing it would only
   * let a user reshuffle between equally-good answers, which reads as the
   * app being unreliable. `setRunConfig` PUTs the whole object back, so the
   * field has to survive the trip -- it just has no UI.
   */
  random_seed: number;
}
export interface ResultState {
  has_result: boolean;
  is_stale: boolean;
  input_revision: number;
  solve_revision: number | null;
  result_mode: "solver" | "manual" | null;
}
export function getResultState() {
  return request<ResultState>("/api/result-state");
}
export function getRunConfig() {
  return request<RunConfig>("/api/run-config");
}
export function setRunConfig(cfg: RunConfig) {
  return request<RunConfig>("/api/run-config", { method: "POST", body: JSON.stringify(cfg) });
}

// ---- Constraints (built-in rules + chat/manual exceptions, unified) ----
export type ConstraintType = "capacity" | "separate" | "together" | "at_least_one_of" | "balance" | "locked" | "friendship_objective";
export type ConstraintSource = "builtin_default" | "chat" | "manual";
export interface ConstraintModel {
  id: string;
  type: ConstraintType;
  hard: boolean;
  args: Record<string, unknown>;
  label_hebrew: string;
  source: ConstraintSource;
  active: boolean;
}
export function getConstraints() {
  return request<{ constraints: ConstraintModel[] }>("/api/constraints");
}
export function patchConstraint(id: string, changes: { hard?: boolean; active?: boolean }) {
  return request<ConstraintModel>(`/api/constraints/${id}`, { method: "PATCH", body: JSON.stringify(changes) });
}
export function deleteConstraint(id: string) {
  return request<{ removed: boolean }>(`/api/constraints/${id}`, { method: "DELETE" });
}

// ---- Chat ----
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
export interface PendingProposal {
  kind: "propose" | "modify" | "remove" | "assignment_action" | "data_action";
  summary_hebrew: string;
  constraint?: ConstraintModel | null;
  target_constraint_id?: string | null;
  changes?: Record<string, unknown> | null;
  action?: "move_student" | "set_student_lock" | "restore_version" | "edit_student_data" | null;
  action_args?: Record<string, unknown> | null;
  evidence?: {
    basis?: "measured_trial" | "solver_conflict" | "arithmetic_feasibility_package";
    trial_feasible?: boolean | null;
    changes_hard_rule?: boolean;
    other_hard_rules_changed?: number;
    item_count?: number;
  } | null;
}
/** One read tool the agent ran while working on a turn. Reads execute
 *  immediately server-side; only writes come back as a proposal. */
export interface AgentStep {
  tool: string;
  ok: boolean;
}
export interface SuggestedAction {
  label: string;
  message: string;
}
export function getChatHistory() {
  return request<{ messages: ChatMessage[]; pending_proposal: PendingProposal | null }>("/api/chat/history");
}
export interface ChatResponse {
  reply: string;
  pending_proposal: PendingProposal | null;
  steps?: AgentStep[];
  state_changed?: boolean;
  suggestions?: SuggestedAction[];
  result_state?: ResultState;
  solver_run_requested?: boolean;
  solver_run_count?: number;
}
export function sendChatMessage(message: string) {
  return request<ChatResponse>("/api/chat/message", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}
type StreamHandlers = { onDelta?: (text: string) => void; onTool?: (step: AgentStep) => void };

async function streamRequest<T>(path: string, body: unknown, handlers: StreamHandlers): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "X-Session-Id": getSessionId(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, res.statusText || "Streaming response unavailable");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: T | null = null;
  let cancelled = false;
  // Providers often deliver a whole sentence in one network chunk, which
  // makes a technically-streaming answer flash onto the screen instantly.
  // Serialize those chunks into a calmer reading pace without delaying the
  // model, tools, or solver themselves.
  const STREAM_CHARS_PER_TICK = 2;
  const STREAM_TICK_MS = 38;
  let pacing = Promise.resolve();
  const paceText = (text: string) => {
    pacing = pacing.then(async () => {
      for (let index = 0; index < text.length && !cancelled; index += STREAM_CHARS_PER_TICK) {
        handlers.onDelta?.(text.slice(index, index + STREAM_CHARS_PER_TICK));
        if (index + STREAM_CHARS_PER_TICK < text.length) {
          await new Promise((resolve) => window.setTimeout(resolve, STREAM_TICK_MS));
        }
      }
    });
  };
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as {
        type: "status" | "delta" | "tool" | "result" | "error";
        text?: string;
        tool?: string;
        ok?: boolean;
        status?: number | string;
        detail?: string;
        data?: T;
      };
      if (event.type === "delta" && event.text) paceText(event.text);
      if (event.type === "tool" && event.tool) handlers.onTool?.({ tool: event.tool, ok: event.ok !== false });
      if (event.type === "result" && event.data) result = event.data;
      if (event.type === "error") {
        cancelled = true;
        throw new ApiError(typeof event.status === "number" ? event.status : 500, event.detail ?? "Streaming failed");
      }
    }
    if (done) break;
  }
  await pacing;
  if (!result) throw new ApiError(502, "The assistant stream ended before a final response was received.");
  return result;
}

export function streamChatMessage(message: string, handlers: StreamHandlers = {}): Promise<ChatResponse> {
  return streamRequest<ChatResponse>("/api/chat/message/stream", { message }, handlers);
}
/** One column the counselor agreed to add to the workbook, from planning. */
export interface DataRequirement {
  id: string;
  label: string;
  kind: "flag" | "category" | "number";
  kind_label: string;
  how_to_fill: string;
  reason: string;
  values: string[];
  satisfied: boolean;
  column_key: string | null;
}
export interface DataRequirementsResponse {
  requirements: DataRequirement[];
  total: number;
  satisfied: number;
  missing: number;
  has_dataset: boolean;
}
export function getDataRequirements() {
  return request<DataRequirementsResponse>("/api/data-requirements");
}
export function deleteDataRequirement(id: string) {
  return request<{ removed: boolean }>(`/api/data-requirements/${id}`, { method: "DELETE" });
}

export function confirmChatProposal() {
  return request<{
    applied: boolean;
    result: unknown;
    result_state?: ResultState;
    solver_run_requested?: boolean;
    state_changed?: boolean;
    confirmation_message?: string;
    action_kind?: PendingProposal["action"];
  }>("/api/chat/confirm", { method: "POST" });
}
export function rejectChatProposal() {
  return request<{ rejected: boolean }>("/api/chat/reject", { method: "POST" });
}

// ---- Step 7: locking ----
export function getLocking() {
  return request<{ rows: { student_id: number; locked_class: number }[]; locked_count: number }>("/api/locking");
}
export function setLocking(locks: Record<string, number>) {
  return request<{ locked_count: number }>("/api/locking", { method: "POST", body: JSON.stringify({ locks }) });
}

// ---- Step 8: optimize ----
export interface OptimizeResponse {
  status_name: string;
  is_feasible: boolean;
  wall_time_seconds: number;
  objective_value: number | null;
  infeasibility_notes: string[];
  conflicting_constraint_ids?: string[];
  infeasibility_explanation?: string | null;
  // On an infeasible solve the backend stages a concrete way out (soften
  // one conflicting hard rule) as a normal pending proposal, so confirming
  // it runs through the same path as a chat-proposed change.
  relaxation_proposal?: PendingProposal | null;
  // Short LLM read of a successful result; null when no LLM is configured.
  result_comment?: string | null;
  result_state?: ResultState;
  version?: { id: string; number: number } | null;
  verification?: VerificationReport | null;
  no_distinct_alternative?: boolean;
}
export interface RuleCheck {
  constraint_id: string;
  label: string;
  rule_type: string;
  hard: boolean;
  status: "satisfied" | "violated" | "not_applicable";
  summary: string;
  expected: unknown;
  actual: unknown;
  affected_students: number[];
  affected_groups: Array<number | string>;
}
export interface VerificationReport {
  is_valid: boolean;
  summary: string;
  students_expected: number;
  students_assigned: number;
  hard_rules_satisfied: number;
  hard_rules_violated: number;
  soft_rules_satisfied: number;
  soft_rules_violated: number;
  checks: RuleCheck[];
}
export interface DecisionOption {
  id: string;
  title: string;
  strategy: string;
  verification: VerificationReport;
  metrics: GlobalMetrics;
  compromises: string[];
  relaxed_constraint_ids: string[];
  objective_value: number | null;
  wall_time_seconds: number;
  differs_from_first: number;
}
export interface InferredPreference {
  key: string;
  description: string;
  kind: "inferred_preference";
  explicit: false;
  observations: number;
  confidence: number;
  last_updated?: string;
}
export function getResultsVerification() {
  return request<VerificationReport>("/api/results/verification");
}
export function generateDecisionPortfolio(maxOptions = 4) {
  return request<{
    has_perfect_solution: boolean;
    options: DecisionOption[];
    conflicts: Array<{ constraint_id: string; label: string }>;
    question: { question: string; options: string[]; reason: string } | null;
    message: string;
  }>("/api/decision-support/portfolio", { method: "POST", params: { max_options: maxOptions } });
}
export function getDecisionPortfolio() {
  return request<{ options: DecisionOption[]; inferred_preferences: InferredPreference[] }>("/api/decision-support/portfolio");
}
export function selectDecisionOption(optionId: string, reason?: string) {
  return request<{
    applied: boolean;
    requires_confirmation: boolean;
    proposal?: PendingProposal;
    version?: { id: string; number: number };
    verification?: VerificationReport;
    inferred_preferences: InferredPreference[];
  }>("/api/decision-support/select", { method: "POST", body: JSON.stringify({ option_id: optionId, reason }) });
}
export interface ProjectDecision {
  at: string;
  decision: "approved" | "rejected" | "applied";
  kind: string;
  summary: string;
}
export function getProjectMemory() {
  return request<{ notes: string[]; decisions: ProjectDecision[]; inferred_preferences?: InferredPreference[] }>("/api/project-memory");
}
export function runOptimize(alternative = false, includeComment = true) {
  return request<OptimizeResponse>("/api/optimize", {
    method: "POST",
    params: { alternative, include_comment: includeComment },
  });
}
export function continueAfterSolver(versionIds: string[]) {
  return request<{ reply: string; steps?: AgentStep[]; suggestions?: SuggestedAction[] }>("/api/chat/solver-result", {
    method: "POST",
    body: JSON.stringify({ version_ids: versionIds }),
  });
}
export function streamAfterSolver(versionIds: string[], handlers: StreamHandlers = {}) {
  return streamRequest<{ reply: string; steps?: AgentStep[]; suggestions?: SuggestedAction[] }>(
    "/api/chat/solver-result/stream",
    { version_ids: versionIds },
    handlers
  );
}

// ---- Step 9: results ----
// Mirrors class_overview_table() (src/metrics.py) field-for-field -- keys
// are the real Hebrew column names the backend returns, not translated.
export interface ClassOverviewRow {
  "כיתה": number;
  "גודל": number;
  "ציון לימודי ממוצע": number;
  "התפלגות הישגים": Record<string, number>;
  "דיפרנציאליות": number;
  "מוצא אתיופי": number;
  "שילוב": number;
  'ח"מ': number;
  'התפלגות ביה"ס': Record<string, number>;
  "התפלגות כיתה נוכחית": Record<string, number>;
  "אחוז חברות הדדית": number | null;
  "אחוז 2+ חברות": number | null;
  "חריגות": number;
  "ציון איכות": number;
}
export function getResultsOverview() {
  return request<{ rows: ClassOverviewRow[] }>("/api/results/overview");
}
export interface ReviewGroup {
  id: string;
  label: string;
  hard: boolean;
  min: number | null;
  max: number | null;
  member_ids: number[];
}
export function getResultsStudents() {
  return request<{ rows: Record<string, unknown>[]; review_groups: ReviewGroup[] }>("/api/results/students");
}
export interface GlobalMetrics {
  total_students: number;
  num_classes: number;
  class_sizes: number[];
  class_size_min: number;
  class_size_max: number;
  class_size_spread: number;
  academic_level_spread: number | null;
  mutual_satisfied_pct: number;
  two_friends_satisfied_pct: number;
  satisfied_requests: number;
  partial_requests: number;
  unsatisfied_requests: number;
  violations_count: number;
  // 0 means no friendship data exists for this run -- mutual_satisfied_pct
  // being 0 in that case means "no data", not "every request failed".
  students_with_requests: number;
  solver_status: string;
  solver_wall_time: number;
  objective_value: number | null;
}
export function getResultsMetrics() {
  return request<GlobalMetrics>("/api/results/metrics");
}
export function getResultsViolations() {
  return request<{ rows: Record<string, unknown>[] }>("/api/results/violations");
}
export function getResultsFriendship() {
  return request<{ unmatched_rows: Record<string, unknown>[]; no_request_data_count: number }>(
    "/api/results/friendship"
  );
}

export interface AssignmentVersionSummary {
  id: string;
  number: number;
  created_at: string;
  reason: string;
  mode: "solver" | "manual";
  approved: boolean;
  is_current: boolean;
  metrics: GlobalMetrics;
  locked_count: number;
  moved_students_from_previous: number | null;
}
export function getVersions() {
  return request<{ current_version_id: string | null; versions: AssignmentVersionSummary[] }>("/api/versions");
}
export function restoreVersion(versionId: string) {
  return request<{ restored: boolean; version_id: string; number: number; result_state: ResultState }>(
    `/api/versions/${versionId}/restore`,
    { method: "POST" }
  );
}
export function approveVersion(versionId: string) {
  return request<{ approved: boolean; version_id: string; number: number }>(`/api/versions/${versionId}/approve`, {
    method: "POST",
  });
}

// ---- Step 10: manual adjustment ----
export function moveStudent(studentId: number, newClass: number, locked?: boolean) {
  return request<{ assignment_updated: boolean; metrics: GlobalMetrics; result_state: ResultState; version?: { id: string; number: number } }>("/api/adjustment/move", {
    method: "POST",
    body: JSON.stringify({ student_id: studentId, new_class: newClass, locked }),
  });
}
export function reoptimize() {
  return request<OptimizeResponse>("/api/adjustment/reoptimize", { method: "POST" });
}

// ---- Step 11: export ----
export function exportXlsxUrl() {
  return `${API_BASE}/api/export.xlsx`;
}
export async function fetchExportBlob(): Promise<Blob> {
  const sid = getSessionId();
  const res = await fetch(`${API_BASE}/api/export.xlsx`, { headers: { "X-Session-Id": sid } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}

// The fill-in template: base fields plus whatever columns the planning
// conversation has since decided the workbook needs -- see
// RequirementsCard, which is the only place this is downloaded from.
export async function fetchTemplateBlob(): Promise<Blob> {
  const sid = getSessionId();
  const res = await fetch(`${API_BASE}/api/export-template.xlsx`, { headers: { "X-Session-Id": sid } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}
