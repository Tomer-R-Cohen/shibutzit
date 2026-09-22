"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import Dialog from "@/components/ui/Dialog";
import { Icon } from "@/components/Icon";
import { Skeleton } from "@/components/ui/primitives";
import { ClassFocus, ClassWall, ClassWallLegend, CategoryKey, StudentRow, Thresholds, fullName } from "@/components/ClassWall";
import { StudentDrawer } from "@/components/StudentDrawer";
import { ApiError, ConstraintModel, GlobalMetrics, ReviewGroup, VerificationReport, approveVersion, fetchExportBlob, getConstraints, getResultState, getResultsMetrics, getResultsStudents, getResultsVerification, getResultsViolations, getRunConfig, getVersions, moveStudent } from "@/lib/api";

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
export default function ResultsBoard({
  open,
  onClose,
  onResultChanged,
  onAskAI,
  onManualMove,
  onApproved,
  fixtureData,
}: {
  open: boolean;
  onClose: () => void;
  onResultChanged?: () => void;
  onAskAI?: (message: string) => void;
  onManualMove?: (studentName: string, fromClass: number, toClass: number) => void;
  onApproved?: (exported: boolean) => void;
  /** Dev-only visual fixture; bypasses API reads without changing runtime behavior. */
  fixtureData?: {
    students: StudentRow[];
    constraints: ConstraintModel[];
    numClasses: number;
    metrics: GlobalMetrics;
    reviewGroups?: ReviewGroup[];
    violationRows?: Record<string, unknown>[];
    verification?: VerificationReport;
    approved?: boolean;
    stale?: boolean;
    selectedStudentId?: number;
    pendingClass?: number;
    loadError?: string;
  };
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [reviewGroups, setReviewGroups] = useState<ReviewGroup[]>([]);
  const [thresholds, setThresholds] = useState<Thresholds | null>(null);
  const [numClasses, setNumClasses] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | null>(null);
  const [focus, setFocus] = useState<ClassFocus>("all");
  const [query, setQuery] = useState("");
  const [exporting, setExporting] = useState(false);
  const [approved, setApproved] = useState(false);
  const [currentVersionId, setCurrentVersionId] = useState<string | null>(null);
  const [violationsCount, setViolationsCount] = useState(0);
  const [violationRows, setViolationRows] = useState<Record<string, unknown>[]>([]);
  const [metrics, setMetrics] = useState<GlobalMetrics | null>(null);
  const [verification, setVerification] = useState<VerificationReport | null>(null);
  const [adjusting, setAdjusting] = useState(false);
  const adjustingRef = useRef(false);
  const [stale, setStale] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [loadKey, setLoadKey] = useState(0);

  useEffect(() => {
    (() => {
      if (!open) return;
      setSelectedId(fixtureData?.selectedStudentId ?? null);
      setApproved(false);
      setLoading(true);
      setError(null);
      setSyncError(null);
      setCategoryFilter(null);
      setFocus("all");
      setQuery("");
      if (fixtureData) {
        if (fixtureData.loadError) {
          setError(fixtureData.loadError);
          setLoading(false);
          return;
        }
        setStudents(fixtureData.students);
        setReviewGroups(fixtureData.reviewGroups ?? []);
        setThresholds(thresholdsOf(fixtureData.constraints));
        setNumClasses(fixtureData.numClasses);
        setCurrentVersionId("fixture-version");
        setApproved(fixtureData.approved ?? false);
        setViolationsCount(fixtureData.metrics.violations_count);
        setMetrics(fixtureData.metrics);
        setViolationRows(fixtureData.violationRows ?? []);
        setVerification(fixtureData.verification ?? null);
        setStale(fixtureData.stale ?? false);
        setLoading(false);
        return;
      }
      Promise.all([getResultsStudents(), getConstraints(), getRunConfig(), getVersions(), getResultsMetrics(), getResultsViolations(), getResultState(), getResultsVerification()])
        .then(([s, c, rc, vh, metrics, violations, state, verified]) => {
          setStudents(s.rows as unknown as StudentRow[]);
          setReviewGroups(s.review_groups ?? []);
          setThresholds(thresholdsOf(c.constraints));
          setNumClasses(rc.num_classes);
          setCurrentVersionId(vh.current_version_id);
          setApproved(vh.versions.find((v) => v.id === vh.current_version_id)?.approved ?? false);
          setViolationsCount(metrics.violations_count);
          setMetrics(metrics);
          setViolationRows(violations.rows);
          setStale(state.is_stale);
          setVerification(verified);
        })
        .catch((e) => setError(e instanceof ApiError ? e.message : "לא הצלחנו לטעון את התוצאות"))
        .finally(() => setLoading(false));
    })();
  }, [open, fixtureData, loadKey]);

  const selected = students.find((s) => s["מזהה"] === selectedId) ?? null;
  const classSizes = Array.from({ length: numClasses }, (_, index) =>
    students.filter((student) => Number(student["כיתה משובצת"]) === index + 1).length
  );
  const warningCount = students.filter((student) => Boolean(student["אזהרות"])).length;
  const lockedCount = students.filter((student) => Boolean(student["נעולה"])).length;
  const boardStatus = violationsCount > 0
    ? { label: "דורש תיקון", tone: "blocked" }
    : stale
      ? { label: "לא מעודכן", tone: "stale" }
      : approved
        ? { label: "מאושר", tone: "approved" }
        : { label: "טיוטה פעילה", tone: "draft" };
  const approvalBlocked = violationsCount > 0 || stale || Boolean(syncError);
  const approvalDescription = [
    violationsCount > 0 ? "cw-violation-warning" : null,
    stale ? "cw-stale-warning" : null,
    syncError ? "cw-sync-warning" : null,
  ].filter(Boolean).join(" ") || undefined;
  const normalizedQuery = query.trim().toLocaleLowerCase("he");
  const selectedReviewGroup = reviewGroups.find((group) => group.id === categoryFilter);
  const highlightedCount = students.filter((student) => {
    const haystack = `${fullName(student)} ${String(student['ביה"ס נוכחי'] ?? "")}`.toLocaleLowerCase("he");
    const matchesQuery = !normalizedQuery || haystack.includes(normalizedQuery);
    const matchesCategory = !categoryFilter || (selectedReviewGroup
      ? selectedReviewGroup.member_ids.includes(Number(student["מזהה"]))
      : Boolean(student[categoryFilter as string]));
    const matchesFocus = focus === "all" || (focus === "warnings" ? Boolean(student["אזהרות"]) : Boolean(student["נעולה"]));
    return matchesQuery && matchesCategory && matchesFocus;
  }).length;
  const reviewActive = Boolean(normalizedQuery || categoryFilter || focus !== "all");
  const closeStudent = useCallback(() => setSelectedId(null), []);

  function retryInitialLoad() {
    setError(null);
    setLoading(true);
    setLoadKey((value) => value + 1);
  }

  function askAI(message: string) {
    setSelectedId(null);
    onAskAI?.(message);
  }

  async function refreshViolationReport() {
    try {
      const [report, verified] = await Promise.all([getResultsViolations(), getResultsVerification()]);
      setViolationRows(report.rows);
      setVerification(verified);
    } catch {
      // Keep the authoritative count from the move response, but never show
      // stale per-rule details if the follow-up report could not be loaded.
      setViolationRows([]);
      setVerification(null);
    }
  }

  async function refreshStudentRows() {
    try {
      const response = await getResultsStudents();
      setStudents(response.rows as unknown as StudentRow[]);
      setReviewGroups(response.review_groups ?? []);
      setSyncError(null);
      return true;
    } catch {
      setSyncError("השינוי נשמר, אבל לא הצלחנו לרענן את פרטי התלמידות. נתוני החברות וסימוני הבדיקה שמוצגים עשויים להיות ישנים, ולכן העריכה והאישור נעצרו עד לרענון.");
      return false;
    }
  }

  async function retryBoardRefresh() {
    if (adjustingRef.current || fixtureData) return;
    adjustingRef.current = true;
    setAdjusting(true);
    try {
      const [studentRows, latestMetrics, violations, versions, state, verified] = await Promise.all([
        getResultsStudents(),
        getResultsMetrics(),
        getResultsViolations(),
        getVersions(),
        getResultState(),
        getResultsVerification(),
      ]);
      setStudents(studentRows.rows as unknown as StudentRow[]);
      setReviewGroups(studentRows.review_groups ?? []);
      setMetrics(latestMetrics);
      setViolationsCount(latestMetrics.violations_count);
      setViolationRows(violations.rows);
      setCurrentVersionId(versions.current_version_id);
      setApproved(versions.versions.find((version) => version.id === versions.current_version_id)?.approved ?? false);
      setStale(state.is_stale);
      setVerification(verified);
      setSyncError(null);
      toast.success("פרטי השיבוץ עודכנו");
    } catch (e) {
      setSyncError("עדיין לא הצלחנו לרענן את פרטי השיבוץ. אפשר לנסות שוב בעוד רגע.");
      toast.error(e instanceof ApiError ? e.message : "לא הצלחנו לרענן את פרטי השיבוץ");
    } finally {
      adjustingRef.current = false;
      setAdjusting(false);
    }
  }

  async function moveStudentTo(studentId: number, newClass: number) {
    if (adjustingRef.current) return;
    const student = students.find((s) => s["מזהה"] === studentId);
    if (!student || student["כיתה משובצת"] === newClass) return;
    const fromClass = student["כיתה משובצת"];
    const wasApproved = approved;
    const previousViolations = metrics?.violations_count ?? violationsCount;
    setApproved(false);
    adjustingRef.current = true;
    setAdjusting(true);
    setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": newClass } : s)));
    try {
      const moved = await moveStudent(studentId, newClass, undefined);
      if (moved.version) setCurrentVersionId(moved.version.id);
      setViolationsCount(moved.metrics.violations_count);
      setMetrics(moved.metrics);
      setStale(moved.result_state.is_stale);
      await Promise.all([refreshStudentRows(), refreshViolationReport()]);
      onResultChanged?.();
      onManualMove?.(fullName(student), Number(fromClass), newClass);
      const toastOptions = {
        action: {
          label: "בטל",
          onClick: async () => {
            // The toast is created just before the original move's `finally`
            // releases this lock. A quick user could therefore click Undo in
            // that tiny window and permanently lose the one-click recovery.
            // Wait for the authoritative refresh to settle, then acquire the
            // lock synchronously before another adjustment can begin.
            const deadline = Date.now() + 5000;
            while (adjustingRef.current && Date.now() < deadline) {
              await new Promise((resolve) => window.setTimeout(resolve, 50));
            }
            if (adjustingRef.current) {
              toast.info("יש להמתין לסיום העדכון הנוכחי לפני ביטול המעבר");
              return;
            }
            adjustingRef.current = true;
            setAdjusting(true);
            setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": fromClass } : s)));
            try {
              const restored = await moveStudent(studentId, Number(fromClass), undefined);
              if (restored.version) setCurrentVersionId(restored.version.id);
              setViolationsCount(restored.metrics.violations_count);
              setMetrics(restored.metrics);
              setStale(restored.result_state.is_stale);
              await Promise.all([refreshStudentRows(), refreshViolationReport()]);
              onResultChanged?.();
              onManualMove?.(fullName(student), newClass, Number(fromClass));
              toast.success("המעבר בוטל");
            } catch {
              setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": newClass } : s)));
              toast.error("לא הצלחנו לבטל את ההעברה");
            } finally {
              adjustingRef.current = false;
              setAdjusting(false);
            }
          },
        },
      };
      if (moved.metrics.violations_count > 0) {
        const currentViolations = moved.metrics.violations_count;
        const changeDescription = currentViolations < previousViolations
          ? `המעבר צמצם את חריגות החובה מ־${previousViolations} ל־${currentViolations}.`
          : currentViolations > previousViolations
            ? `המעבר הגדיל את חריגות החובה מ־${previousViolations} ל־${currentViolations}.`
            : `לאחר המעבר עדיין קיימות ${currentViolations} חריגות חובה.`;
        toast.warning(`${fullName(student)} הועברה — השיבוץ עדיין טיוטה`, {
          ...toastOptions,
          description: `${changeDescription} לא ניתן לאשר את השיבוץ עד לתיקונן.`,
        });
      } else {
        toast.success(`${fullName(student)} הועברה לכיתה ${newClass}`, toastOptions);
      }
    } catch (e) {
      setApproved(wasApproved);
      setStudents((prev) => prev.map((s) => (s["מזהה"] === studentId ? { ...s, "כיתה משובצת": fromClass } : s)));
      toast.error(e instanceof ApiError ? e.message : "לא הצלחנו לעדכן את השיבוץ");
    } finally {
      adjustingRef.current = false;
      setAdjusting(false);
    }
  }

  async function handleLockToggle() {
    if (!selected || adjustingRef.current) return;
    const nextLocked = !selected["נעולה"];
    const wasApproved = approved;
    setApproved(false);
    adjustingRef.current = true;
    setAdjusting(true);
    setStudents((prev) => prev.map((s) => (s["מזהה"] === selected["מזהה"] ? { ...s, "נעולה": nextLocked } : s)));
    try {
      const moved = await moveStudent(selected["מזהה"], selected["כיתה משובצת"] as number, nextLocked);
      if (moved.version) setCurrentVersionId(moved.version.id);
      setViolationsCount(moved.metrics.violations_count);
      setMetrics(moved.metrics);
      setStale(moved.result_state.is_stale);
      await Promise.all([refreshStudentRows(), refreshViolationReport()]);
      onResultChanged?.();
    } catch (e) {
      setApproved(wasApproved);
      setStudents((prev) => prev.map((s) => (s["מזהה"] === selected["מזהה"] ? { ...s, "נעולה": !nextLocked } : s)));
      toast.error(e instanceof ApiError ? e.message : "לא הצלחנו לעדכן את הקיבוע");
    } finally {
      adjustingRef.current = false;
      setAdjusting(false);
    }
  }

  async function approveAndExport() {
    if (fixtureData) {
      setApproved(true);
      return;
    }
    setExporting(true);
    let newlyApproved = false;
    let approvalSucceeded = approved;
    try {
      if (!currentVersionId) throw new ApiError(409, "אין גרסת שיבוץ פעילה לאישור");
      if (!approved) {
        await approveVersion(currentVersionId);
        approvalSucceeded = true;
        newlyApproved = true;
        setApproved(true);
        onResultChanged?.();
      }
      const blob = await fetchExportBlob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "שיבוץ-כיתות-מאושר.xlsx";
      link.click();
      URL.revokeObjectURL(url);
      if (newlyApproved) onApproved?.(true);
      toast.success("השיבוץ אושר וקובץ האקסל מוכן");
    } catch (e) {
      if (newlyApproved && approvalSucceeded) onApproved?.(false);
      toast.error(
        approvalSucceeded
          ? "השיבוץ אושר, אבל הורדת הקובץ נכשלה. אפשר לנסות להוריד שוב."
          : e instanceof ApiError ? e.message : "לא הצלחנו לאשר את השיבוץ"
      );
    } finally {
      setExporting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="הכיתות">
      <div className="cw cw-class-screen">
        <header className="cw-board-head">
          <div className="cw-board-heading">
            <span className="cw-board-eyebrow">השיבוץ הנוכחי</span>
            <div className="cw-board-titleline">
              <h1>חלוקת הכיתות</h1>
              <span className={boardStatus.tone}>{boardStatus.label}</span>
            </div>
            <p>סקירה, בדיקה והעברה ידנית של תלמידות בין הכיתות</p>
          </div>
          <div className="cw-board-actions">
            {onAskAI && (
              <button type="button" className="cw-board-ai" onClick={() => askAI("השווי בין הכיתות בשיבוץ הנוכחי: מה מאוזן היטב ואיפה כדאי לבדוק או לשפר?")}>
                <Icon name="sparkle" size={14} /> השוואה עם העוזרת
              </button>
            )}
            <button
              type="button"
              className={`ws-approve-export${approvalBlocked ? " is-blocked" : ""}`}
              onClick={() => {
                if (!approvalBlocked) void approveAndExport();
              }}
              disabled={loading || !!error || exporting}
              aria-disabled={approvalBlocked || undefined}
              aria-describedby={approvalDescription}
              title={syncError ? "יש לרענן את פרטי השיבוץ לפני אישור" : stale ? "הכללים או הנתונים השתנו — יש לעדכן את השיבוץ לפני אישור" : violationsCount > 0 ? "יש לתקן את חריגות החובה לפני אישור השיבוץ" : undefined}
            >
              {approvalBlocked ? <><Icon name="lock" size={13} /> אישור חסום</> : approved ? "הורדת Excel שוב" : exporting ? "מכינה את הקובץ…" : "אישור והורדת Excel"}
            </button>
          </div>
        </header>

        {!loading && !error && (
          <div className="cw-board-summary" aria-label="סיכום השיבוץ">
            <div><span>תלמידות</span><strong>{students.length}</strong></div>
            <div><span>כיתות</span><strong>{numClasses}</strong></div>
            <div><span>טווח גודל</span><strong>{Math.min(...classSizes)}–{Math.max(...classSizes)}</strong></div>
            <div className={!metrics?.students_with_requests ? "no-data" : ""}>
              <span>מענה לבקשה הדדית</span>
              <strong>{metrics?.students_with_requests ? `${metrics.mutual_satisfied_pct}%` : "אין נתונים"}</strong>
            </div>
            <div className={metrics?.academic_level_spread == null ? "no-data" : ""} title="פער מצטבר בין הכיתות בכל רמות ההישגים; מספר נמוך יותר משמעו חלוקה מאוזנת יותר">
              <span>פער בהרכב הלימודי</span>
              <strong>{metrics?.academic_level_spread ?? "אין נתונים"}</strong>
            </div>
            <div className={warningCount ? "attention" : ""}><span>דורשות בדיקה</span><strong>{warningCount}</strong></div>
            <div><span>מקובעות</span><strong>{lockedCount}</strong></div>
          </div>
        )}

        {!loading && !error && verification && (
          <details className={`cw-verification-report ${verification.is_valid ? "is-valid" : "is-invalid"}`}>
            <summary>
              <span>{verification.is_valid ? "הבדיקה העצמאית עברה" : "הבדיקה העצמאית מצאה חריגות"}</span>
              <strong>{verification.hard_rules_satisfied} כללי חובה תקינים · {verification.hard_rules_violated} חריגות</strong>
            </summary>
            <p>{verification.students_assigned} מתוך {verification.students_expected} תלמידים משובצים. התוצאה חושבה מחדש מכללי המערכת ואינה מסתמכת על דיווח הפותר.</p>
            <ul>
              {verification.checks.map((check) => (
                <li key={check.constraint_id} className={check.status}>
                  <span aria-hidden>{check.status === "satisfied" ? "✓" : check.status === "violated" ? "!" : "–"}</span>
                  <div><strong>{check.label}</strong><small>{check.summary}</small></div>
                </li>
              ))}
            </ul>
          </details>
        )}

        {!loading && !error && violationsCount > 0 && (
          <div id="cw-violation-warning" className="cw-hard-warning" role="alert">
            <Icon name="warning" size={16} />
            <div>
              <strong>השיבוץ כולל {violationsCount} חריגות מכללי חובה</strong>
              <span>השינויים נשמרו כטיוטה, אך אי אפשר לאשר ולייצא שיבוץ סופי עד שהחריגות יתוקנו.</span>
              {violationRows.length > 0 && (
                <ul className="cw-hard-warning-list">
                  {violationRows.slice(0, 4).map((row, index) => (
                    <li key={`${String(row["כלל"])}-${String(row["כיתה"])}-${index}`}>
                      <strong>{String(row["כלל"] ?? "כלל חובה")}</strong>
                      <span>כיתה {String(row["כיתה"])} · בפועל {String(row["בפועל"])} במקום {String(row["צפוי"])}</span>
                    </li>
                  ))}
                  {violationRows.length > 4 && <li className="more">ועוד {violationRows.length - 4} חריגות</li>}
                </ul>
              )}
            </div>
          </div>
        )}

        {!loading && !error && stale && (
          <div id="cw-stale-warning" className="cw-stale-warning" role="status">
            <Icon name="warning" size={16} />
            <div>
              <strong>השיבוץ אינו מעודכן לפי הכללים הנוכחיים</strong>
              <span>הכללים או הנתונים השתנו מאז יצירת הגרסה הזו. יש לעדכן את השיבוץ לפני שאפשר לאשר אותו.</span>
            </div>
            {onAskAI && <button type="button" onClick={() => askAI("הכללים או הנתונים השתנו מאז השיבוץ האחרון. בדקי מה השתנה ועדכני את השיבוץ בהתאם.")}>עדכון עם העוזרת</button>}
          </div>
        )}

        {!loading && !error && syncError && (
          <div id="cw-sync-warning" className="cw-hard-warning" role="alert">
            <Icon name="warning" size={16} />
            <div>
              <strong>פרטי השיבוץ זקוקים לרענון</strong>
              <span>{syncError}</span>
            </div>
            <button type="button" onClick={() => void retryBoardRefresh()} disabled={adjusting}>
              {adjusting ? "מרעננת…" : "רענון עכשיו"}
            </button>
          </div>
        )}

        <div className="cw-board-toolbar">
          <label className="cw-board-search">
            <Icon name="search" size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="חיפוש תלמידה או בית ספר…" aria-label="חיפוש תלמידה או בית ספר" />
            {query && <button type="button" onClick={() => setQuery("")} aria-label="ניקוי החיפוש"><Icon name="x" size={13} /></button>}
          </label>
          <div className="cw-filters" role="group" aria-label="סינון לפי קטגוריה">
            <button className="cw-fchip" aria-pressed={categoryFilter === null} onClick={() => setCategoryFilter(null)}>
              כל הקטגוריות
            </button>
            {(reviewGroups.length > 0
              ? reviewGroups.map((group, index) => ({ key: group.id, label: group.label, color: `hsl(${(index * 67 + 202) % 360} 58% 52%)` }))
              : CATEGORY_FILTERS.map((filter) => ({ key: filter.key, label: filter.label, color: `var(--cw-${filter.cls})` }))).map((f) => (
              <button
                key={f.key}
                className="cw-fchip"
                aria-pressed={categoryFilter === f.key}
                onClick={() => setCategoryFilter((p) => (p === f.key ? null : f.key))}
              >
                <span className="sw" style={{ background: f.color }} aria-hidden />
                {f.label}
              </button>
            ))}
          </div>
          <span className="cw-toolbar-separator" aria-hidden />
          <div className="cw-filters" role="group" aria-label="מיקוד לבדיקה">
            <button className="cw-fchip" aria-pressed={focus === "warnings"} onClick={() => setFocus((value) => value === "warnings" ? "all" : "warnings")}>
              <Icon name="warning" size={13} /> דורשות בדיקה
            </button>
            <button className="cw-fchip" aria-pressed={focus === "locked"} onClick={() => setFocus((value) => value === "locked" ? "all" : "locked")}>
              <Icon name="lock" size={12} /> מקובעות
            </button>
          </div>
          {reviewActive && <span className="cw-review-count">מודגשות {highlightedCount} מתוך {students.length}</span>}
        </div>

        {loading ? (
          <Skeleton className="h-64 w-full" />
        ) : error ? (
          <div className="ws-inline-error cw-board-load-error" role="alert">
            <Icon name="warning" size={16} />
            <div><strong>השיבוץ לא נטען</strong><span>{error}</span></div>
            <button type="button" onClick={retryInitialLoad}>ניסיון נוסף</button>
          </div>
        ) : (
          <>
            <ClassWallLegend />
            <ClassWall
              students={students}
              numClasses={numClasses}
              thresholds={thresholds ?? { incl: { min: 0, max: 2 }, hamar: { min: 0, max: 2 }, eth: { min: 0, max: 4 }, diff: { min: 0, max: 1 } }}
              categoryFilter={categoryFilter}
              query={query}
              focus={focus}
              reviewGroups={reviewGroups}
              onAskClass={onAskAI ? (classNumber) => askAI(`נתחי את כיתה ${classNumber}: מה מאוזן בה ומה דורש בדיקה?`) : undefined}
              interactionDisabled={adjusting || !!syncError || !!fixtureData}
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
          onClose={closeStudent}
          onMove={(newClass) => moveStudentTo(selected["מזהה"], newClass)}
          onLockToggle={handleLockToggle}
          onAskAI={onAskAI ? askAI : undefined}
          busy={adjusting || !!syncError || !!fixtureData}
          initialPendingClass={fixtureData?.pendingClass}
        />
      )}
    </Dialog>
  );
}
