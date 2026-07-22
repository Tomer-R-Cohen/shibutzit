"use client";

import { useMemo } from "react";
import clsx from "clsx";
import { StatusIndicator } from "@/components/ui/primitives";

export interface StudentRow {
  "מזהה": number;
  "שם פרטי"?: string;
  "שם משפחה"?: string;
  "כיתה משובצת": number | null;
  "ביה\"ס נוכחי"?: string;
  "הישגים לימודיים"?: string;
  "מוצא אתיופי"?: boolean;
  "שילוב"?: boolean;
  'ח"מ'?: boolean;
  "דיפרנציאלית"?: boolean;
  "נעולה"?: boolean;
  "בקשות חברות"?: number;
  "חברות מבוקשות באותה כיתה"?: number;
  "חברות הדדיות באותה כיתה"?: number;
  "לפחות חברה הדדית אחת"?: boolean;
  "אזהרות"?: string;
  [key: string]: unknown;
}

export interface ClassOverviewRow {
  "כיתה": number;
  "גודל": number;
  "חריגות"?: number;
  [key: string]: unknown;
}

export type CategoryKey = "מוצא אתיופי" | "שילוב" | 'ח"מ' | "דיפרנציאלית";

export function fullName(s: StudentRow) {
  const first = (s["שם פרטי"] ?? "").toString().trim();
  const last = (s["שם משפחה"] ?? "").toString().trim();
  return `${first} ${last}`.trim() || `תלמידה #${s["מזהה"]}`;
}

// A compact group of dots representing students — a roster motif, not a
// seating chart. Category students get a ring instead of a different color,
// keeping the strip visually quiet.
function OccupancyStrip({
  members,
  selectedId,
  onSelect,
  categoryFilter,
}: {
  members: StudentRow[];
  selectedId?: number | null;
  onSelect?: (s: StudentRow) => void;
  categoryFilter?: CategoryKey | null;
}) {
  return (
    <div className="flex flex-wrap content-start gap-[3px]" role="group" aria-label="תלמידות בכיתה">
      {members.map((s) => {
        const isSpecial = Boolean(s["מוצא אתיופי"] || s["שילוב"] || s['ח"מ'] || s["דיפרנציאלית"]);
        const isSelected = selectedId === s["מזהה"];
        const dim = categoryFilter ? !s[categoryFilter] : false;
        const warn = Boolean(s["אזהרות"]);
        return (
          <button
            key={s["מזהה"]}
            type="button"
            onClick={() => onSelect?.(s)}
            title={fullName(s)}
            aria-label={`${fullName(s)}, כיתה ${s["כיתה משובצת"]}${s["נעולה"] ? ", נעולה" : ""}${warn ? ", אזהרה" : ""}`}
            className={clsx(
              "h-2 w-2 rounded-full motion-safe:transition-transform focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-1",
              isSpecial ? "bg-slate-400 ring-2 ring-teal-300" : "bg-slate-300",
              warn && "ring-2 ring-amber-400",
              isSelected && "motion-safe:scale-150 bg-teal-600 ring-teal-600",
              dim && "opacity-20"
            )}
          />
        );
      })}
    </div>
  );
}

export function ClassBoardLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-slate-300" />
        תלמידה
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-slate-400 ring-2 ring-teal-300" />
        קטגוריית תמיכה
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-slate-300 ring-2 ring-amber-400" />
        אזהרה
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-teal-600" />
        נבחרה
      </span>
    </div>
  );
}

// One dense table row per class, so a whole grade reads as a single block
// rather than a stack of panels. Numbers sit in aligned columns to make
// imbalance between classes visible by scanning straight down.
export function ClassBoard({
  students,
  numClasses,
  overview,
  selectedId,
  onSelect,
  categoryFilter,
}: {
  students: StudentRow[];
  numClasses: number;
  overview?: ClassOverviewRow[];
  selectedId?: number | null;
  onSelect?: (student: StudentRow) => void;
  categoryFilter?: CategoryKey | null;
}) {
  const byClass = useMemo(() => {
    const map = new Map<number, StudentRow[]>();
    for (let c = 1; c <= numClasses; c++) map.set(c, []);
    for (const s of students) {
      const cls = s["כיתה משובצת"];
      if (cls == null) continue;
      if (!map.has(cls)) map.set(cls, []);
      map.get(cls)!.push(s);
    }
    return map;
  }, [students, numClasses]);

  const overviewByClass = useMemo(() => {
    const map = new Map<number, ClassOverviewRow>();
    overview?.forEach((r) => map.set(r["כיתה"], r));
    return map;
  }, [overview]);

  const sizes = Array.from(byClass.values()).map((v) => v.length).filter((n) => n > 0);
  const maxSize = Math.max(1, ...sizes);
  const avgSize = sizes.length ? Math.round(sizes.reduce((a, b) => a + b, 0) / sizes.length) : 0;

  const th = "border-b border-slate-200 px-2 py-1.5 font-medium text-slate-500 whitespace-nowrap";
  const num = "px-2 py-1.5 text-center tabular-nums text-slate-700";

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-right text-sm">
        <caption className="sr-only">סיכום הרכב הכיתות</caption>
        <thead>
          <tr>
            <th className={th}>כיתה</th>
            <th className={`${th} text-center`}>גודל</th>
            <th className={th}>תלמידות</th>
            <th className={`${th} text-center`}>חברות</th>
            <th className={`${th} text-center`}>שילוב</th>
            <th className={`${th} text-center`}>ח&quot;מ</th>
            <th className={`${th} text-center`}>אתיופי</th>
            <th className={th}>סטטוס</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {Array.from(byClass.entries()).map(([cls, members]) => {
            const imbalanced = avgSize > 0 && Math.abs(members.length - avgSize) > 1;
            const ov = overviewByClass.get(cls);
            const warnings = ov?.["חריגות"] ?? members.filter((m) => m["אזהרות"]).length;
            const mutualCount = members.filter((m) => m["חברות הדדיות באותה כיתה"]).length;
            const friendshipPct = members.length ? Math.round((mutualCount / members.length) * 100) : 0;

            return (
              <tr key={cls} id={`class-${cls}`} className="scroll-mt-24 align-middle">
                <td className="whitespace-nowrap px-2 py-1.5 font-semibold text-slate-800">כיתה {cls}</td>
                <td className={num}>
                  <span className={clsx(imbalanced && "text-amber-700")}>{members.length}</span>
                  <span className="text-slate-300"> / {maxSize}</span>
                </td>
                <td className="px-2 py-1.5">
                  <OccupancyStrip members={members} selectedId={selectedId} onSelect={onSelect} categoryFilter={categoryFilter} />
                </td>
                <td className={num}>{friendshipPct}%</td>
                <td className={num}>{members.filter((m) => m["שילוב"]).length}</td>
                <td className={num}>{members.filter((m) => m['ח"מ']).length}</td>
                <td className={num}>{members.filter((m) => m["מוצא אתיופי"]).length}</td>
                <td className="whitespace-nowrap px-2 py-1.5">
                  <StatusIndicator
                    status={warnings > 0 ? "warning" : imbalanced ? "warning" : "valid"}
                    text={warnings > 0 ? `${warnings} אזהרות` : imbalanced ? "גודל לא מאוזן" : "תקין"}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
