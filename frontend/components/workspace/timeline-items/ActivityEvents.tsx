import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/primitives";
import { GlobalMetrics } from "@/lib/api";

import { formatTime } from "./shared";

export function ManualMoveEvent({ studentName, from, to, at }: { studentName: string; from: number; to: number; at: number }) {
  return (
    <div className="ws-event ws-event-boxed">
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
    <div className="ws-event ws-event-boxed">
      <Icon name="check" size={12} />
      <span>
        השיבוץ חושב מחדש
        {before != null && after != null ? ` · ציון: ${Math.round(before)} → ${Math.round(after)}` : ""}
      </span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}

export function VersionRestoreEvent({ version, reason, at }: { version: number; reason: string; at: number }) {
  return (
    <div className="ws-event ws-event-boxed" role="status">
      <Icon name="history" size={12} />
      <span>
        שוחזרה גרסה {version} · {reason}
      </span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}

export function FinalApprovalEvent({ exported, at }: { exported: boolean; at: number }) {
  return (
    <div className="ws-event ws-event-boxed ws-event-approved" role="status">
      <Icon name="check" size={12} />
      <span>{exported ? "השיבוץ אושר וקובץ ה־Excel הורד" : "השיבוץ אושר · הורדת הקובץ עדיין ממתינה"}</span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}

export function ChatErrorArtifact({
  message,
  retryable,
  onRetry,
  onReview,
}: {
  message: string;
  retryable: boolean;
  onRetry: () => void;
  onReview: () => void;
}) {
  return (
    <div className="ws-artifact ws-chat-error" role="alert">
      <div className="ws-artifact-head"><Icon name="warning" size={15} /><span>לא התקבלה תשובה מלאה</span></div>
      <p className="ws-artifact-note">{message}</p>
      <p className="ws-chat-error-guidance">
        {retryable
          ? "לא בוצע שינוי בלתי הפיך. אפשר לנסות שוב בלי לשלוח את הבקשה מחדש."
          : "ייתכן שחלק מהפעולות כבר הושלמו. כדי לא לבצע שינוי פעמיים, בדקו קודם את מצב הפרויקט."}
      </p>
      <div className="ws-artifact-actions">
        {retryable && <Button size="sm" onClick={onRetry}>ניסיון נוסף</Button>}
        <Button size="sm" variant={retryable ? "ghost" : "secondary"} onClick={onReview}>בדיקת מצב הפרויקט</Button>
      </div>
    </div>
  );
}

export function SolveErrorArtifact({
  message,
  retryable,
  completedVersions,
  onRetry,
  onReview,
}: {
  message: string;
  retryable: boolean;
  completedVersions: number;
  onRetry: () => void;
  onReview: () => void;
}) {
  const partial = completedVersions > 0;
  return (
    <div className="ws-artifact ws-chat-error ws-solve-error" role="alert">
      <div className="ws-artifact-head"><Icon name="warning" size={15} /><span>{partial ? "הריצה הושלמה רק בחלקה" : "ריצת השיבוץ נקטעה"}</span></div>
      <p className="ws-artifact-note">{message}</p>
      <p className="ws-chat-error-guidance">
        {partial
          ? `${completedVersions === 1 ? "גרסה אחת נשמרה" : `${completedVersions} גרסאות נשמרו`}, אבל לא כל החלופות שביקשת הושלמו. לא אריץ שוב אוטומטית כדי לא ליצור גרסאות כפולות.`
          : retryable
            ? "בדקתי את היסטוריית הגרסאות ולא נוצר שיבוץ חדש. אפשר לנסות שוב בבטחה; הכללים והנתונים נשארו ללא שינוי."
            : "לא הצלחתי לוודא אם החישוב הסתיים במערכת. לפני ניסיון נוסף, כדאי לבדוק את השיבוץ הנוכחי כדי למנוע יצירת גרסה כפולה."}
      </p>
      <div className="ws-artifact-actions">
        {retryable && <Button size="sm" onClick={onRetry}>ניסיון נוסף</Button>}
        <Button size="sm" variant={retryable ? "ghost" : "secondary"} onClick={onReview}>בדיקת השיבוץ הנוכחי</Button>
      </div>
    </div>
  );
}

function delta(after: number, before: number) {
  const d = Math.round(after - before);
  return `${d > 0 ? "+" : ""}${d}`;
}

export function SolveComparisonArtifact({
  fromVersion,
  toVersion,
  before,
  after,
  movedStudents,
  onOpenResults,
  onOpenHistory,
}: {
  fromVersion: number;
  toVersion: number;
  before: GlobalMetrics;
  after: GlobalMetrics;
  movedStudents: number;
  onOpenResults: () => void;
  onOpenHistory: () => void;
}) {
  const friendshipAvailable = before.students_with_requests > 0 && after.students_with_requests > 0;
  const friendshipImproved = friendshipAvailable && (after.mutual_satisfied_pct > before.mutual_satisfied_pct || after.two_friends_satisfied_pct > before.two_friends_satisfied_pct);
  const friendshipWorsened = friendshipAvailable && (after.mutual_satisfied_pct < before.mutual_satisfied_pct || after.two_friends_satisfied_pct < before.two_friends_satisfied_pct);
  const balanceImproved = after.class_size_spread < before.class_size_spread;
  const academicAvailable = before.academic_level_spread != null && after.academic_level_spread != null;
  const academicImproved = academicAvailable && after.academic_level_spread! < before.academic_level_spread!;
  const academicWorsened = academicAvailable && after.academic_level_spread! > before.academic_level_spread!;
  const displayedImprovement = after.violations_count === 0 && (friendshipImproved || balanceImproved || academicImproved) && !friendshipWorsened && !academicWorsened && after.class_size_spread <= before.class_size_spread;
  return (
    <div className="ws-artifact ws-comparison">
      <div className="ws-artifact-head"><Icon name="sliders" size={14} /><span>מה השתנה מגרסה {fromVersion} לגרסה {toVersion}</span></div>
      <div className="ws-comparison-grid">
        <div><span>חברה הדדית</span><strong dir={friendshipAvailable ? "ltr" : undefined}>{friendshipAvailable ? `${Math.round(before.mutual_satisfied_pct)}% → ${Math.round(after.mutual_satisfied_pct)}%` : "אין נתוני חברות"}</strong><small>{friendshipAvailable ? `${delta(after.mutual_satisfied_pct, before.mutual_satisfied_pct)} נק׳` : "לא נכלל בהשוואה"}</small></div>
        <div><span>לפחות שתי חברות</span><strong dir={friendshipAvailable ? "ltr" : undefined}>{friendshipAvailable ? `${Math.round(before.two_friends_satisfied_pct)}% → ${Math.round(after.two_friends_satisfied_pct)}%` : "אין נתוני חברות"}</strong><small>{friendshipAvailable ? `${delta(after.two_friends_satisfied_pct, before.two_friends_satisfied_pct)} נק׳` : "לא נכלל בהשוואה"}</small></div>
        <div><span>פער בגודל הכיתות</span><strong dir="ltr">{before.class_size_spread} → {after.class_size_spread}</strong><small>{after.class_size_spread <= before.class_size_spread ? "נשמר או השתפר" : "גדל מעט"}</small></div>
        <div><span>פער בהרכב הלימודי</span><strong dir={academicAvailable ? "ltr" : undefined}>{academicAvailable ? `${before.academic_level_spread} → ${after.academic_level_spread}` : "אין נתונים"}</strong><small>{academicAvailable ? "נמוך יותר = מאוזן יותר" : "לא נכלל בהשוואה"}</small></div>
        <div><span>תלמידות שעברו</span><strong>{movedStudents}</strong><small>כל כללי החובה {after.violations_count === 0 ? "נשמרו" : "דורשים בדיקה"}</small></div>
      </div>
      <div className="ws-comparison-recommend"><Icon name={displayedImprovement ? "check" : "warning"} size={13} /><span>{displayedImprovement ? `במדדים המוצגים גרסה ${toVersion} השתפרה, וכל כללי החובה נשמרו. ההמלצה בשיחה מביאה בחשבון גם את יתר מדדי האיזון.` : `אין כאן שיפור חד-משמעי בכל המדדים המוצגים. כדאי לעיין בהסבר בשיחה לפני בחירת גרסה.`}</span></div>
      <div className="ws-artifact-actions">
        <Button size="sm" variant="secondary" onClick={onOpenResults}>פתיחת השיבוץ החדש</Button>
        <Button size="sm" variant="ghost" onClick={onOpenHistory}>היסטוריית גרסאות</Button>
      </div>
    </div>
  );
}

// Plain-Hebrew names for the read tools. Anything unmapped falls back to a
// generic phrase rather than leaking a snake_case function name into the UI.
const TOOL_LABELS: Record<string, string> = {
  get_solve_summary: "סיכום השיבוץ",
  get_class_sizes: "גדלי הכיתות",
  get_class_composition: "הרכב הכיתה",
  get_violations: "חריגות מהכללים",
  get_active_rules: "הכללים הפעילים",
  analyze_assignment_quality: "ניתוח השיבוץ המלא",
  explain_student_placement: "שיבוץ התלמידה",
  compare_student_versions: "השינוי בשיבוץ התלמידה בין גרסאות",
  query_roster: "נתוני התלמידות",
  request_solver_run: "הכללים המאושרים והנתונים הועברו למנוע השיבוץ",
};

// What-ifs get their own verb: these ran the solver on a hypothetical, which
// is a different kind of work from reading a number off the current result.
const SIM_LABELS: Record<string, string> = {
  simulate_capacity_change: "שינוי הטווח המותר",
  simulate_class_count: "מספר כיתות אחר",
  simulate_rule_toggle: "הפעלה או השבתה של כלל",
  simulate_friendship_priority: "עדיפות לבקשות חברות",
  simulate_balance_priority: "עדיפות לאיזון שנבחר",
};

/**
 * What the agent read before answering. This is the quietest tier in the
 * timeline on purpose -- it is not a result, it is the evidence that the
 * answer above it came from the data rather than from the model's
 * imagination, which is exactly the failure this whole loop exists to fix.
 */
export function AgentStepsEvent({ tools, at, onOpenResults }: { tools: string[]; at: number; onOpenResults?: () => void }) {
  const uniq = (xs: string[]) => xs.filter((x, i) => xs.indexOf(x) === i);
  const read = uniq(tools.filter((t) => !SIM_LABELS[t]).map((t) => TOOL_LABELS[t] ?? "נתוני השיבוץ"));
  const sims = uniq(tools.filter((t) => SIM_LABELS[t]).map((t) => SIM_LABELS[t]));
  const inspectedAssignment = tools.some((tool) => [
    "get_solve_summary",
    "get_class_sizes",
    "get_class_composition",
    "get_violations",
    "analyze_assignment_quality",
    "explain_student_placement",
    "compare_student_versions",
  ].includes(tool));

  return (
    <div className="ws-event ws-event-inline">
      <Icon name={sims.length > 0 ? "sparkle" : "search"} size={12} />
      <span>
        {read.length > 0 && `בדקתי: ${read.join(" · ")}`}
        {read.length > 0 && sims.length > 0 && " · "}
        {sims.length > 0 && `הרצתי שיבוץ לניסיון: ${sims.join(" · ")}`}
      </span>
      {inspectedAssignment && onOpenResults && (
        <button type="button" className="ws-event-action" onClick={onOpenResults}>פתיחת הראיות</button>
      )}
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}
