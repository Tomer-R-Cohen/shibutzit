"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button, StatusIndicator } from "@/components/ui/primitives";
import { DataTable } from "@/components/DataTable";
import { ClassWall, ClassWallLegend, CategoryKey, StudentRow, Thresholds, fullName } from "@/components/ClassWall";
import { StudentDrawer } from "@/components/StudentDrawer";
import { WallSkeleton } from "@/components/Skeletons";
import {
  ApiError,
  ConstraintModel,
  GlobalMetrics,
  RunConfig,
  fetchExportBlob,
  getConstraints,
  getLocking,
  getResultsMetrics,
  getResultsStudents,
  getResultsViolations,
  getRunConfig,
  getValidation,
  getFeasibility,
  moveStudent,
  reoptimize,
  runOptimize,
} from "@/lib/api";
import { setFlag } from "@/lib/steps";

const CATEGORY_FILTERS: { key: CategoryKey; cls: string; label: string }[] = [
  { key: "שילוב", cls: "incl", label: "שילוב" },
  { key: 'ח"מ', cls: "hamar", label: 'ח"מ' },
  { key: "מוצא אתיופי", cls: "eth", label: "מוצא אתיופי" },
  { key: "דיפרנציאלית", cls: "diff", label: "דיפרנציאלית" },
];

interface DataStatus {
  studentCount: number | null;
  hasErrors: boolean;
  allFeasible: boolean;
}

// Demographic thresholds live as capacity-type entries in the unified
// constraint list (src/constraints.py) -- read them back out by the data
// field each capacity rule targets.
function thresholdsOf(constraints: ConstraintModel[]): Thresholds {
  const byField: Record<string, { min: number; max: number }> = {};
  for (const c of constraints) {
    if (c.type !== "capacity") continue;
    const group = c.args.group as { kind?: string; field?: string } | undefined;
    if (group?.kind !== "field" || !group.field) continue;
    byField[group.field] = { min: Number(c.args.min ?? 0), max: Number(c.args.max ?? 0) };
  }
  return {
    incl: byField["inclusion"] ?? { min: 0, max: 2 },
    hamar: byField["hamar"] ?? { min: 0, max: 2 },
    eth: byField["ethiopian_origin"] ?? { min: 3, max: 4 },
    diff: { min: 0, max: byField["differential"]?.max ?? 1 },
  };
}

/**
 * Results: class board, violations, manual moves, export. Assumes the
 * caller has already established the workbook is loaded/mapped/feasible
 * (see app/page.tsx's readiness gate) -- unlike the old standalone results
 * page, this component does no data-loading/mapping of its own, only reads
 * that are safe once that's already true.
 */
export default function ResultsZone() {
  const [booting, setBooting] = useState(true);
  const [dataStatus, setDataStatus] = useState<DataStatus | null>(null);

  const [readiness, setReadiness] = useState<{ lockedCount: number } | null>(null);
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);

  const [students, setStudents] = useState<StudentRow[]>([]);
  const [metrics, setMetrics] = useState<GlobalMetrics | null>(null);
  const [violations, setViolations] = useState<Record<string, unknown>[]>([]);
  const [runConfig, setRunConfig] = useState<RunConfig | null>(null);
  const [constraints, setConstraints] = useState<ConstraintModel[]>([]);
  const [hasResults, setHasResults] = useState(false);
  const [loadingResults, setLoadingResults] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | null>(null);
  const [reopt, setReopt] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [validation, feasibility, rc, cs, l] = await Promise.all([
          getValidation(),
          getFeasibility(),
          getRunConfig(),
          getConstraints(),
          getLocking(),
        ]);
        if (cancelled) return;
        setDataStatus({
          studentCount: feasibility.total_students,
          hasErrors: validation.has_errors,
          allFeasible: feasibility.all_feasible,
        });
        setRunConfig(rc);
        setConstraints(cs.constraints);
        setReadiness({ lockedCount: l.locked_count });
        await fetchResults(true);
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "שגיאה בטעינת נתוני התוצאות.");
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function fetchResults(silent = false) {
    if (!silent) setLoadingResults(true);
    try {
      const [s, m, v, rc, cs] = await Promise.all([
        getResultsStudents(),
        getResultsMetrics(),
        getResultsViolations(),
        getRunConfig(),
        getConstraints(),
      ]);
      setStudents(s.rows as unknown as StudentRow[]);
      setMetrics(m);
      setViolations(v.rows);
      setRunConfig(rc);
      setConstraints(cs.constraints);
      setHasResults(true);
    } catch {
      setHasResults(false);
    } finally {
      setLoadingResults(false);
    }
  }

  async function handleRun() {
    if (runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    try {
      const res = await runOptimize();
      if (res.is_feasible) {
        setFlag("optimized", true);
        toast.success(`נמצא שיבוץ ב-${res.wall_time_seconds.toFixed(1)} שניות`);
        await fetchResults();
      } else {
        toast.error(`לא נמצא שיבוץ אפשרי. סטטוס: ${res.status_name}`);
        res.infeasibility_notes.forEach((n) => toast.error(n));
        if (res.infeasibility_explanation) toast.error(res.infeasibility_explanation);
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בהרצת השיבוץ");
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  }

  const selected = students.find((s) => s["מזהה"] === selectedId) ?? null;

  // Move a student to a class: optimistic update, persist, offer undo.
  async function moveStudentTo(studentId: number, newClass: number) {
    const student = students.find((s) => s["מזהה"] === studentId);
    if (!student || student["כיתה משובצת"] === newClass) return;
    const fromClass = student["כיתה משובצת"];
    setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": newClass } : s)));
    try {
      const res = await moveStudent(studentId, newClass, undefined);
      setMetrics(res.metrics);
      toast.success(`${fullName(student)} → כיתה ${newClass}`, {
        action: {
          label: "בטל",
          onClick: async () => {
            try {
              const undoRes = await moveStudent(studentId, Number(fromClass), undefined);
              setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": fromClass } : s)));
              setMetrics(undoRes.metrics);
              toast.success("המעבר בוטל");
            } catch {
              toast.error("שגיאה בביטול המעבר");
            }
          },
        },
      });
    } catch (e) {
      setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": fromClass } : s)));
      toast.error(e instanceof ApiError ? e.message : "שגיאה בעדכון השיבוץ");
    }
  }

  async function handleLockToggle() {
    if (!selected) return;
    const nextLocked = !selected["נעולה"];
    try {
      const res = await moveStudent(selected["מזהה"], selected["כיתה משובצת"] as number, nextLocked);
      setStudents((prev) => prev.map((s) => (s["מזהה"] === selected["מזהה"] ? { ...s, "נעולה": nextLocked } : s)));
      setMetrics(res.metrics);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה");
    }
  }

  async function handleReoptimize() {
    setReopt(true);
    try {
      await reoptimize();
      toast.success("השיבוץ עודכן. שיבוצים ידניים נשמרו.");
      await fetchResults();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בשיבוץ מחדש");
    } finally {
      setReopt(false);
    }
  }

  async function handleExport() {
    setExporting(true);
    try {
      const blob = await fetchExportBlob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "שיבוץ_תלמידות.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("קובץ האקסל הורד בהצלחה.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בייצוא הקובץ");
    } finally {
      setExporting(false);
    }
  }

  if (booting) {
    return (
      <div className="cw flex flex-col gap-4">
        <div className="flex items-center gap-2 text-sm" style={{ color: "var(--cw-ink-2)" }}>
          <span className="h-2 w-2 shrink-0 rounded-full motion-safe:animate-pulse" style={{ background: "var(--cw-accent)" }} />
          טוען נתוני תוצאות…
        </div>
        <WallSkeleton />
      </div>
    );
  }

  return (
    <div className="cw flex flex-col" style={{ gap: 14 }}>
      <div className="dp-head">
        <div className="dp-title">
          <h1>שיבוץ כיתות</h1>
          {dataStatus?.studentCount != null && <span className="dp-count cw-num">{dataStatus.studentCount} תלמידות</span>}
        </div>
        <div className="dp-spacer" />
        {hasResults && metrics && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" size="sm" disabled={reopt} onClick={handleReoptimize} title="פותר מחדש תוך שמירת השיבוצים הידניים">
              {reopt ? "משבץ מחדש…" : "שבץ מחדש"}
            </Button>
            <Button variant="secondary" size="sm" disabled={exporting} onClick={handleExport}>
              {exporting ? "מייצא…" : "ייצוא לאקסל"}
            </Button>
            <Button disabled={running} onClick={handleRun}>
              {running ? "מריץ שיבוץ…" : "הפקת שיבוץ מחדש"}
            </Button>
          </div>
        )}
      </div>

      {!hasResults && !running && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pb-3.5 text-xs cw-t2" style={{ borderBottom: "1px solid var(--cw-line)" }}>
          <StatusIndicator status={dataStatus?.hasErrors ? "warning" : "valid"} text={dataStatus?.hasErrors ? "נתונים דורשים בדיקה" : "נתונים תקינים"} />
          {dataStatus && !dataStatus.allFeasible && <StatusIndicator status="warning" text="לא ניתן לקיים חלק מהכללים" />}
          {(readiness?.lockedCount ?? 0) > 0 && <span>{readiness?.lockedCount} תלמידות נעולות מראש</span>}
        </div>
      )}

      {running && (
        <div className="flex items-center gap-2 py-5 text-sm cw-t2">
          <span className="h-2 w-2 shrink-0 rounded-full motion-safe:animate-pulse" style={{ background: "var(--cw-accent)" }} />
          מחפש חלוקה מאוזנת לכיתות. פעולה זו עשויה לקחת מעט זמן.
        </div>
      )}

      {loadingResults && <WallSkeleton />}

      {!loadingResults && !hasResults && !running && (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <h3 className="text-sm font-semibold text-[var(--cw-ink)]">עדיין לא הופק שיבוץ</h3>
          <p className="max-w-md text-sm text-[var(--cw-ink-3)]">לחצו כדי לחפש חלוקה מאוזנת לכיתות לפי הכללים שהוגדרו.</p>
          <Button className="mt-1" onClick={handleRun} disabled={running}>
            הפקת שיבוץ
          </Button>
        </div>
      )}

      {!loadingResults && hasResults && metrics && (
        <>
          {violations.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm font-medium cw-warnc">חריגות מכללי חובה ({violations.length})</summary>
              <div className="mt-3">
                <DataTable rows={violations} />
              </div>
            </details>
          )}

          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="cw-filters" role="group" aria-label="סינון לפי קטגוריה">
                <button className="cw-fchip" aria-pressed={categoryFilter === null} onClick={() => setCategoryFilter(null)}>
                  הכל
                </button>
                {CATEGORY_FILTERS.map((f) => (
                  <button
                    key={f.key}
                    className="cw-fchip"
                    aria-pressed={categoryFilter === f.key}
                    onClick={() => setCategoryFilter((prev) => (prev === f.key ? null : f.key))}
                  >
                    <span className="sw" style={{ background: `var(--cw-${f.cls})` }} />
                    {f.label}
                  </button>
                ))}
              </div>
              <ClassWallLegend />
            </div>

            <ClassWall
              students={students}
              numClasses={runConfig?.num_classes ?? 6}
              thresholds={thresholdsOf(constraints)}
              categoryFilter={categoryFilter}
              onMove={moveStudentTo}
              onOpen={(s) => setSelectedId(s["מזהה"])}
            />
            <span className="text-xs cw-t3">גררו כרטיס תלמידה בין הכיתות · לחצו על כרטיס לפרטים והעברה מדויקת</span>
          </div>
        </>
      )}

      {selected && (
        <StudentDrawer
          student={selected}
          students={students}
          numClasses={runConfig?.num_classes ?? 6}
          onClose={() => setSelectedId(null)}
          onMove={(newClass) => moveStudentTo(selected["מזהה"], newClass)}
          onLockToggle={handleLockToggle}
        />
      )}
    </div>
  );
}
