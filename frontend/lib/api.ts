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
  [key: string]: unknown;
}
export function getStudents() {
  return request<{ rows: StudentRecord[]; count: number }>("/api/students");
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
// constraint list below -- this is just num_classes / time limit / seed.
export interface RunConfig {
  num_classes: number;
  denominator_all_students: boolean;
  mutual_target_pct: number;
  two_friends_target_pct: number;
  time_limit_seconds: number;
  random_seed: number;
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
  kind: "propose" | "modify" | "remove";
  summary_hebrew: string;
  constraint?: ConstraintModel | null;
  target_constraint_id?: string | null;
  changes?: Record<string, unknown> | null;
}
export function getChatHistory() {
  return request<{ messages: ChatMessage[]; pending_proposal: PendingProposal | null }>("/api/chat/history");
}
export function sendChatMessage(message: string) {
  return request<{ reply: string; pending_proposal: PendingProposal | null }>("/api/chat/message", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}
export function confirmChatProposal() {
  return request<{ applied: boolean; result: unknown }>("/api/chat/confirm", { method: "POST" });
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
}
export function runOptimize() {
  return request<OptimizeResponse>("/api/optimize", { method: "POST" });
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
export function getResultsStudents() {
  return request<{ rows: Record<string, unknown>[] }>("/api/results/students");
}
export interface GlobalMetrics {
  total_students: number;
  num_classes: number;
  class_sizes: number[];
  class_size_min: number;
  class_size_max: number;
  class_size_spread: number;
  mutual_satisfied_pct: number;
  two_friends_satisfied_pct: number;
  satisfied_requests: number;
  partial_requests: number;
  unsatisfied_requests: number;
  violations_count: number;
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

// ---- Step 10: manual adjustment ----
export function moveStudent(studentId: number, newClass: number, locked?: boolean) {
  return request<{ assignment_updated: boolean; metrics: GlobalMetrics }>("/api/adjustment/move", {
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
