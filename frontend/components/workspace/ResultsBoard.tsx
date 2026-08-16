"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import Dialog from "@/components/ui/Dialog";
import { Skeleton } from "@/components/ui/primitives";
import { ClassWall, ClassWallLegend, CategoryKey, StudentRow, Thresholds, fullName } from "@/components/ClassWall";
import { StudentDrawer } from "@/components/StudentDrawer";
import { ApiError, ConstraintModel, getConstraints, getResultsStudents, getRunConfig, moveStudent } from "@/lib/api";

const CATEGORY_FILTERS: { key: CategoryKey; cls: string; label: string }[] = [
  { key: "שילוב", cls: "incl", label: "שילוב" },
  { key: 'ח"מ', cls: "hamar", label: 'ח"מ' },
  { key: "מוצא אתיופי", cls: "eth", label: "מוצא אתיופי" },
  { key: "דיפרנציאלית", cls: "diff", label: "דיפרנציאלית" },
];

// Category min/max now live as capacity Constraints (unified rule model),
// not on the run config -- pull them back out into the shape ClassWall
// expects, one lookup per known field.
function thresholdsOf(constraints: ConstraintModel[]): Thresholds {
  const of = (field: string, fallback: { min: number; max: number }) => {
    const c = constraints.find(
      (c) => c.type === "capacity" && (c.args.group as { kind?: string; field?: string } | undefined)?.field === field
    );
    if (!c) return fallback;
    return { min: (c.args.min as number | null) ?? 0, max: (c.args.max as number | null) ?? fallback.max };
  };
  return {
    incl: of("inclusion", { min: 0, max: 2 }),
    hamar: of("hamar", { min: 0, max: 2 }),
    eth: of("ethiopian_origin", { min: 0, max: 4 }),
    diff: of("differential", { min: 0, max: 1 }),
  };
}

/**
 * The class board: full screen, one column per class, real student cards
 * with drag-and-drop reassignment. Opened from "פתיחת הכיתות" once a solve
 * exists -- reuses ClassWall/StudentDrawer as-is (unchanged since the
 * earlier step-based UI), just re-fed from the workspace's own state.
 */
export default function ResultsBoard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [thresholds, setThresholds] = useState<Thresholds | null>(null);
  const [numClasses, setNumClasses] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | null>(null);

  useEffect(() => {
    (() => {
      if (!open) return;
      setLoading(true);
      setError(null);
      Promise.all([getResultsStudents(), getConstraints(), getRunConfig()])
        .then(([s, c, rc]) => {
          setStudents(s.rows as unknown as StudentRow[]);
          setThresholds(thresholdsOf(c.constraints));
          setNumClasses(rc.num_classes);
        })
        .catch((e) => setError(e instanceof ApiError ? e.message : "שגיאה בטעינת התוצאות"))
        .finally(() => setLoading(false));
    })();
  }, [open]);

  const selected = students.find((s) => s["מזהה"] === selectedId) ?? null;

  async function moveStudentTo(studentId: number, newClass: number) {
    const student = students.find((s) => s["מזהה"] === studentId);
    if (!student || student["כיתה משובצת"] === newClass) return;
    const fromClass = student["כיתה משובצת"];
    setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": newClass } : s)));
    try {
      await moveStudent(studentId, newClass, undefined);
      toast.success(`${fullName(student)} → כיתה ${newClass}`, {
        action: {
          label: "בטל",
          onClick: async () => {
            try {
              await moveStudent(studentId, Number(fromClass), undefined);
              setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": fromClass } : s)));
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
      await moveStudent(selected["מזהה"], selected["כיתה משובצת"] as number, nextLocked);
      setStudents((prev) => prev.map((s) => (s["מזהה"] === selected["מזהה"] ? { ...s, "נעולה": nextLocked } : s)));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה");
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="הכיתות">
      <div className="cw flex h-full flex-col" style={{ gap: 12 }}>
        <div className="dp-head">
          <div className="dp-title">
            <h1>הכיתות</h1>
            <span className="dp-count cw-num">{students.length} תלמידות</span>
          </div>
          <div className="dp-spacer" />
          <div className="cw-filters" role="group" aria-label="סינון לפי קטגוריה">
            <button className="cw-fchip" aria-pressed={categoryFilter === null} onClick={() => setCategoryFilter(null)}>
              הכל
            </button>
            {CATEGORY_FILTERS.map((f) => (
              <button
                key={f.key}
                className="cw-fchip"
                aria-pressed={categoryFilter === f.key}
                onClick={() => setCategoryFilter((p) => (p === f.key ? null : f.key))}
              >
                <span className="sw" style={{ background: `var(--cw-${f.cls})` }} aria-hidden />
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <Skeleton className="h-64 w-full" />
        ) : error ? (
          <p className="py-10 text-center text-sm text-[var(--cw-crit)]">{error}</p>
        ) : (
          <>
            <ClassWallLegend />
            <ClassWall
              students={students}
              numClasses={numClasses}
              thresholds={thresholds ?? { incl: { min: 0, max: 2 }, hamar: { min: 0, max: 2 }, eth: { min: 0, max: 4 }, diff: { min: 0, max: 1 } }}
              categoryFilter={categoryFilter}
              onMove={moveStudentTo}
              onOpen={(s) => setSelectedId(s["מזהה"])}
            />
          </>
        )}
      </div>

      {selected && (
        <StudentDrawer
          student={selected}
          students={students}
          numClasses={numClasses}
          onClose={() => setSelectedId(null)}
          onMove={(newClass) => moveStudentTo(selected["מזהה"], newClass)}
          onLockToggle={handleLockToggle}
        />
      )}
    </Dialog>
  );
}
