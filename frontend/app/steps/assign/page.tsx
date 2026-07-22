"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import clsx from "clsx";
import { Button, EmptyState, Skeleton, StatusIndicator } from "@/components/ui/primitives";
import { DataTable } from "@/components/DataTable";
import { ClassBoard, ClassBoardLegend, ClassOverviewRow, CategoryKey, StudentRow } from "@/components/ClassBoard";
import { ClassBalanceComparison } from "@/components/ClassBalanceComparison";
import { AssignmentHealthSummary } from "@/components/AssignmentHealthSummary";
import { StudentDrawer } from "@/components/StudentDrawer";
import {
  ApiError,
  GlobalMetrics,
  fetchExportBlob,
  getConfig,
  getFriendshipDiagnostics,
  getLocking,
  getResultsMetrics,
  getResultsOverview,
  getResultsStudents,
  getResultsViolations,
  getValidation,
  moveStudent,
  reoptimize,
  runOptimize,
} from "@/lib/api";
import { setFlag } from "@/lib/steps";

const CATEGORY_FILTERS: { key: CategoryKey; label: string }[] = [
  { key: "מוצא אתיופי", label: "מוצא אתיופי" },
  { key: "שילוב", label: "שילוב" },
  { key: 'ח"מ', label: 'ח"מ' },
  { key: "דיפרנציאלית", label: "דיפרנציאלית" },
];

type View = "classes" | "students";

export default function AssignStep() {
  const [blocked, setBlocked] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<{ dataValid: boolean; lockedCount: number } | null>(null);
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);

  const [students, setStudents] = useState<StudentRow[]>([]);
  const [overview, setOverview] = useState<ClassOverviewRow[] | null>(null);
  const [metrics, setMetrics] = useState<GlobalMetrics | null>(null);
  const [violations, setViolations] = useState<Record<string, unknown>[]>([]);
  const [friendshipDiag, setFriendshipDiag] = useState<{ unmatched_count: number; ambiguous_count: number } | null>(null);
  const [numClasses, setNumClasses] = useState(6);
  const [hasResults, setHasResults] = useState(false);
  const [loadingResults, setLoadingResults] = useState(false);

  const [view, setView] = useState<View>("classes");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | null>(null);
  const [reopt, setReopt] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    Promise.all([getValidation(), getConfig(), getLocking()])
      .then(([v, c, l]) => {
        if (v.has_errors) setBlocked("קיימות שגיאות אימות חוסמות בשלב הנתונים. יש לתקן לפני ההרצה.");
        setNumClasses(c.num_classes);
        setReadiness({ dataValid: !v.has_errors, lockedCount: l.locked_count });
      })
      .catch((e) => setBlocked(e instanceof ApiError ? e.message : "יש להשלים שלבים קודמים תחילה."));
    fetchResults(true);
  }, []);

  async function fetchResults(silent = false) {
    if (!silent) setLoadingResults(true);
    try {
      const [o, s, m, v, fd, c] = await Promise.all([
        getResultsOverview(),
        getResultsStudents(),
        getResultsMetrics(),
        getResultsViolations(),
        getFriendshipDiagnostics(),
        getConfig(),
      ]);
      setOverview(o.rows as unknown as ClassOverviewRow[]);
      setStudents(s.rows as unknown as StudentRow[]);
      setMetrics(m);
      setViolations(v.rows);
      setFriendshipDiag(fd);
      setNumClasses(c.num_classes);
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
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בהרצת השיבוץ");
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  }

  const selected = students.find((s) => s["מזהה"] === selectedId) ?? null;

  async function commitMove(newClass: number) {
    if (!selected) return;
    const movedId = selected["מזהה"];
    const fromClass = selected["כיתה משובצת"];
    try {
      const res = await moveStudent(movedId, newClass, undefined);
      setStudents((prev) => prev.map((s) => (s["מזהה"] === movedId ? { ...s, "כיתה משובצת": newClass } : s)));
      setMetrics(res.metrics);
      toast.success(`הועברה לכיתה ${newClass}`, {
        action: {
          label: "בטל",
          onClick: async () => {
            try {
              const undoRes = await moveStudent(movedId, Number(fromClass), undefined);
              setStudents((prev) => prev.map((s) => (s["מזהה"] === movedId ? { ...s, "כיתה משובצת": fromClass } : s)));
              setMetrics(undoRes.metrics);
              toast.success("המעבר בוטל");
            } catch {
              toast.error("שגיאה בביטול המעבר");
            }
          },
        },
      });
    } catch (e) {
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

  if (blocked) return <EmptyState title="לא ניתן להריץ שיבוץ" description={blocked} actionHref="/steps/data" actionLabel="לשלב הנתונים" />;

  const statusStatement =
    metrics && metrics.violations_count === 0
      ? "השיבוץ עומד בכל כללי החובה"
      : metrics
      ? `נמצאו ${metrics.violations_count} חריגות מכללי חובה`
      : "";

  const filteredStudents = students.filter((s) => !categoryFilter || s[categoryFilter]);

  return (
    <div className="flex flex-col divide-y divide-slate-100">
      {/* Readiness + the one primary action */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4">
        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
          <StatusIndicator
            status={readiness?.dataValid ? "valid" : "warning"}
            text={readiness?.dataValid ? "נתונים תקינים" : "נתונים דורשים בדיקה"}
          />
          {(readiness?.lockedCount ?? 0) > 0 && <span>{readiness?.lockedCount} תלמידות נעולות</span>}
        </div>
        <Button disabled={running} onClick={handleRun}>
          {running ? "מריץ שיבוץ..." : hasResults ? "הפקת שיבוץ מחדש" : "הפקת שיבוץ"}
        </Button>
      </div>

      {running && (
        <div className="flex items-center gap-2 py-5 text-sm text-slate-500">
          <span className="h-2 w-2 shrink-0 rounded-full bg-teal-600 motion-safe:animate-pulse" />
          מחפש חלוקה מאוזנת לכיתות. פעולה זו עשויה לקחת מעט זמן.
        </div>
      )}

      {loadingResults && (
        <div className="py-5">
          <Skeleton className="h-64 w-full" />
        </div>
      )}

      {!loadingResults && !hasResults && !running && (
        <EmptyState title="עדיין לא הופק שיבוץ" description="לחצו על 'הפקת שיבוץ' כדי לחפש חלוקה מאוזנת לכיתות." />
      )}

      {!loadingResults && hasResults && metrics && overview && (
        <>
          {/* Result summary: headline carries the context counts, the four
              measured dimensions sit in one horizontal strip below it. */}
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
              <h2 className="text-sm font-semibold text-slate-800">
                {statusStatement}
                <span className="ms-2 font-normal text-slate-400">
                  {metrics.total_students} תלמידות · {metrics.num_classes} כיתות
                </span>
              </h2>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" disabled={reopt} onClick={handleReoptimize}>
                  {reopt ? "משבץ מחדש..." : "שבץ מחדש ושמור שינויים ידניים"}
                </Button>
                <Button variant="secondary" size="sm" disabled={exporting} onClick={handleExport}>
                  {exporting ? "מייצא..." : "ייצוא לאקסל"}
                </Button>
              </div>
            </div>
            <AssignmentHealthSummary
              metrics={metrics}
              unmatchedCount={friendshipDiag?.unmatched_count ?? 0}
              ambiguousCount={friendshipDiag?.ambiguous_count ?? 0}
            />
          </div>

          {/* Violations surface themselves only when they exist */}
          {violations.length > 0 && (
            <details className="py-4" open>
              <summary className="cursor-pointer text-sm font-medium text-amber-700">
                חריגות מכללי חובה ({violations.length})
              </summary>
              <div className="mt-3">
                <DataTable rows={violations} />
              </div>
            </details>
          )}

          {/* Classes / students */}
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-4" role="tablist" aria-label="תצוגה">
                {([
                  { id: "classes", label: "כיתות" },
                  { id: "students", label: "תלמידות" },
                ] as const).map((v) => (
                  <button
                    key={v.id}
                    role="tab"
                    aria-selected={view === v.id}
                    onClick={() => setView(v.id)}
                    className={clsx(
                      "border-b-2 pb-1 text-sm font-medium motion-safe:transition-colors",
                      view === v.id ? "border-teal-600 text-teal-700" : "border-transparent text-slate-500 hover:text-slate-800"
                    )}
                  >
                    {v.label}
                  </button>
                ))}
              </div>

              {view === "classes" && (
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    onClick={() => setCategoryFilter(null)}
                    className={clsx("text-xs font-medium", categoryFilter === null ? "text-teal-700" : "text-slate-500 hover:text-slate-800")}
                  >
                    הכל
                  </button>
                  {CATEGORY_FILTERS.map((f) => (
                    <button
                      key={f.key}
                      onClick={() => setCategoryFilter((prev) => (prev === f.key ? null : f.key))}
                      className={clsx("text-xs font-medium", categoryFilter === f.key ? "text-teal-700" : "text-slate-500 hover:text-slate-800")}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {view === "students" ? (
              <DataTable rows={students} />
            ) : filteredStudents.length === 0 ? (
              <EmptyState title="לא נמצאו תלמידות התואמות לסינון" description="נסו לבחור קטגוריה אחרת או להציג הכל." />
            ) : (
              <>
                <ClassBoard
                  students={students}
                  numClasses={numClasses}
                  overview={overview}
                  selectedId={selectedId}
                  categoryFilter={categoryFilter}
                  onSelect={(s) => setSelectedId(s["מזהה"])}
                />
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <ClassBoardLegend />
                  <span className="text-xs text-slate-400">לחצו על תלמידה כדי לפתוח את פרטיה ולהעביר אותה</span>
                </div>
                <details className="border-t border-slate-100 pt-3">
                  <summary className="cursor-pointer text-sm text-slate-500">השוואת איזון מפורטת בין הכיתות</summary>
                  <div className="mt-4">
                    <ClassBalanceComparison overview={overview} />
                  </div>
                </details>
              </>
            )}
          </div>
        </>
      )}

      {selected && (
        <StudentDrawer
          student={selected}
          students={students}
          numClasses={numClasses}
          onClose={() => setSelectedId(null)}
          onMove={commitMove}
          onLockToggle={handleLockToggle}
        />
      )}
    </div>
  );
}
