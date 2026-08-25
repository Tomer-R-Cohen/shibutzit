import { Icon } from "@/components/Icon";

import { formatTime } from "./shared";

export function ManualMoveEvent({ studentName, from, to, at }: { studentName: string; from: number; to: number; at: number }) {
  return (
    <div className="ws-event">
      <Icon name="edit" size={12} />
      <span>
        {studentName} הועברה מכיתה {from} לכיתה {to}
      </span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}

export function ReoptimizationEvent({ before, after, at }: { before?: number; after?: number; at: number }) {
  return (
    <div className="ws-event">
      <Icon name="check" size={12} />
      <span>
        בוצעה אופטימיזציה מחדש
        {before != null && after != null ? ` · ציון: ${Math.round(before)} → ${Math.round(after)}` : ""}
      </span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}

// Plain-Hebrew names for the read tools. Anything unmapped falls back to a
// generic phrase rather than leaking a snake_case function name into the UI.
const TOOL_LABELS: Record<string, string> = {
  get_solve_summary: "סיכום השיבוץ",
  get_class_sizes: "גדלי הכיתות",
  get_class_composition: "הרכב הכיתה",
  get_violations: "הפרות הכללים",
  get_active_rules: "הכללים הפעילים",
  explain_student_placement: "שיבוץ התלמידה",
  query_roster: "נתוני התלמידות",
};

// What-ifs get their own verb: these ran the solver on a hypothetical, which
// is a different kind of work from reading a number off the current result.
const SIM_LABELS: Record<string, string> = {
  simulate_capacity_change: "שינוי מכסה",
  simulate_class_count: "מספר כיתות אחר",
  simulate_rule_toggle: "כלל מופעל/מבוטל",
};

/**
 * What the agent read before answering. This is the quietest tier in the
 * timeline on purpose -- it is not a result, it is the evidence that the
 * answer above it came from the data rather than from the model's
 * imagination, which is exactly the failure this whole loop exists to fix.
 */
export function AgentStepsEvent({ tools, at }: { tools: string[]; at: number }) {
  const uniq = (xs: string[]) => xs.filter((x, i) => xs.indexOf(x) === i);
  const read = uniq(tools.filter((t) => !SIM_LABELS[t]).map((t) => TOOL_LABELS[t] ?? "נתוני השיבוץ"));
  const sims = uniq(tools.filter((t) => SIM_LABELS[t]).map((t) => SIM_LABELS[t]));

  return (
    <div className="ws-event">
      <Icon name={sims.length > 0 ? "sparkle" : "search"} size={12} />
      <span>
        {read.length > 0 && `בדק ${read.join(" · ")}`}
        {read.length > 0 && sims.length > 0 && " · "}
        {sims.length > 0 && `הריץ שיבוץ ניסיוני: ${sims.join(" · ")}`}
      </span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}
