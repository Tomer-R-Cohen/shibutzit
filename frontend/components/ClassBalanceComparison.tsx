"use client";

import type { ClassOverviewRow } from "@/components/ClassBoard";

interface MetricRow {
  label: string;
  get: (r: ClassOverviewRow) => number;
}

const METRICS: MetricRow[] = [
  { label: "גודל כיתה", get: (r) => Number(r["גודל"] ?? 0) },
  { label: "מוצא אתיופי", get: (r) => Number(r["מוצא אתיופי"] ?? 0) },
  { label: "שילוב", get: (r) => Number(r["שילוב"] ?? 0) },
  { label: 'ח"מ', get: (r) => Number(r['ח"מ'] ?? 0) },
  { label: "דיפרנציאליות", get: (r) => Number(r["דיפרנציאליות"] ?? 0) },
];

// Aligned horizontal bars, one row per metric, one bar per class — lets an
// imbalance be spotted in a couple of seconds without a charting library.
export function ClassBalanceComparison({ overview }: { overview: ClassOverviewRow[] }) {
  return (
    <div className="grid grid-cols-1 gap-x-10 gap-y-4 sm:grid-cols-2 xl:grid-cols-3">
      {METRICS.map((m) => {
        const values = overview.map((r) => m.get(r));
        const max = Math.max(1, ...values);
        return (
          <div key={m.label} className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-slate-600">{m.label}</span>
            {overview.map((r, i) => {
              const v = values[i];
              const pct = (v / max) * 100;
              return (
                <div key={String(r["כיתה"])} className="flex items-center gap-2 text-xs">
                  <span className="w-10 shrink-0 text-slate-400">כיתה {String(r["כיתה"])}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-teal-600 motion-safe:transition-all" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="w-5 shrink-0 text-left font-medium tabular-nums text-slate-700">{v}</span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
