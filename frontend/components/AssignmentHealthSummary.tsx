"use client";

import { ProgressTrack } from "@/components/ui/primitives";
import type { GlobalMetrics } from "@/lib/api";

// Four explained dimensions instead of one opaque score, per spec: no
// unexplained gauge — each track has an exact value and a plain-language hint.
export function AssignmentHealthSummary({
  metrics,
  unmatchedCount,
  ambiguousCount,
}: {
  metrics: GlobalMetrics;
  unmatchedCount: number;
  ambiguousCount: number;
}) {
  const rulesPct = metrics.violations_count === 0 ? 100 : Math.max(20, 100 - metrics.violations_count * 10);
  const balancePct = Math.max(0, 100 - metrics.class_size_spread * 20);
  const friendshipPct = metrics.mutual_satisfied_pct;
  const qualityIssues = unmatchedCount + ambiguousCount;
  const qualityPct = metrics.total_students ? Math.max(0, 100 - (qualityIssues / metrics.total_students) * 100) : 100;

  return (
    <div className="grid grid-cols-2 gap-x-8 gap-y-3 lg:grid-cols-4">
      <ProgressTrack
        label="עמידה בכללי חובה"
        value={rulesPct}
        tone={metrics.violations_count === 0 ? "success" : "danger"}
        displayValue={metrics.violations_count === 0 ? "ללא חריגות" : `${metrics.violations_count} חריגות`}
        hint="מספר החריגות מכללים מחייבים בשיבוץ הנוכחי."
      />
      <ProgressTrack
        label="איזון בין הכיתות"
        value={balancePct}
        tone={metrics.class_size_spread > 1 ? "warning" : "success"}
        displayValue={`פער גודל: ${metrics.class_size_spread}`}
        hint="הפרש מספר התלמידות בין הכיתה הגדולה לקטנה ביותר."
      />
      <ProgressTrack
        label="מענה לבקשות חברות"
        value={friendshipPct}
        tone={friendshipPct >= 70 ? "success" : friendshipPct >= 40 ? "warning" : "danger"}
        displayValue={`${friendshipPct}% הדדיות`}
        hint="אחוז התלמידות עם לפחות בקשת חברות הדדית אחת שמומשה."
      />
      <ProgressTrack
        label="איכות הנתונים"
        value={qualityPct}
        tone={qualityIssues === 0 ? "success" : "warning"}
        displayValue={qualityIssues === 0 ? "תקינה" : `${qualityIssues} רשומות לבדיקה`}
        hint="שמות בקשות חברות שלא הותאמו או שהיו דו-משמעיים."
      />
    </div>
  );
}
