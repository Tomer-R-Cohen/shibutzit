"use client";

import { DragEvent, useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import clsx from "clsx";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import { ApiError, applyMapping, getMappingGuess, getStudents, loadWorkbook } from "@/lib/api";
import { ensureDataReady } from "@/lib/bootstrap";
import { setFlag } from "@/lib/steps";

export interface DatasetReadyInfo {
  studentCount: number;
  schoolCount: number;
  levelCount: number;
  warningCount: number;
  levelCounts: Record<string, number>;
}

const DEFAULT_LOAD = { headerRow: 4, firstDataRow: 5, lastDataRow: 221 };

/**
 * The pre-data state: a full-screen-focused dropzone, shown only until a
 * workbook is loaded and mapped. Once ready this hands off to the timeline
 * (dataset_ready / data_warning artifacts) and gets out of the way -- the
 * full roster table lives in the RosterWorkbench (Milestone 2), not here.
 */
export default function DatasetOnboarding({
  onReady,
  onWarning,
  onBack,
}: {
  onReady: (info: DatasetReadyInfo) => void;
  onWarning: (problems: string[]) => void;
  onBack?: () => void;
}) {
  const [phase, setPhase] = useState<"needsFile" | "error">("needsFile");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const dragCount = useRef(0);

  const finishReady = useCallback(
    async (problems: string[]) => {
      const st = await getStudents();
      const schools = new Set(st.rows.map((s) => s.current_school).filter((v): v is string => !!v));
      const levelCounts: Record<string, number> = {};
      for (const s of st.rows) {
        const level = s.academic_level;
        if (!level) continue;
        levelCounts[level] = (levelCounts[level] ?? 0) + 1;
      }
      if (problems.length > 0) onWarning(problems);
      onReady({
        studentCount: st.rows.length,
        schoolCount: schools.size,
        levelCount: Object.keys(levelCounts).length,
        warningCount: problems.length,
        levelCounts,
      });
    },
    [onReady, onWarning]
  );

  // Loading the bundled sample is now an explicit button, not something
  // that happens on mount -- see Welcome. `ensureDataReady` is still the
  // path it takes, because it handles the load/guess/apply sequence.
  const loadSampleFile = useCallback(async () => {
    setBusy(true);
    try {
      const rd = await ensureDataReady();
      if (rd.needsMapping) {
        toast.error("קובץ ברירת המחדל דורש מיפוי עמודות ידני");
        setPhase("needsFile");
        return;
      }
      const guess = await getMappingGuess().catch(() => null);
      await finishReady(guess?.problems ?? []);
    } catch {
      setPhase("error");
    } finally {
      setBusy(false);
    }
  }, [finishReady]);

  async function handleLoad(file?: File) {
    setBusy(true);
    try {
      await loadWorkbook({ useDefault: !file, ...DEFAULT_LOAD, file });
      setFlag("loaded", true);
      const guess = await getMappingGuess();
      await applyMapping(guess.mapping, guess.manual_fields);
      setFlag("mapped", true);
      await finishReady(guess.problems);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "לא הצלחתי לטעון את הקובץ");
      setPhase("needsFile");
    } finally {
      setBusy(false);
    }
  }

  function onDropFile(file: File) {
    if (!/\.xlsx$/i.test(file.name)) {
      toast.error("יש לבחור קובץ .xlsx");
      return;
    }
    void handleLoad(file);
  }

  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  const dragProps = {
    onDragEnter: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      dragCount.current++;
      setDragging(true);
    },
    onDragOver: (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    },
    onDragLeave: (e: DragEvent) => {
      if (!hasFiles(e)) return;
      dragCount.current--;
      if (dragCount.current <= 0) {
        dragCount.current = 0;
        setDragging(false);
      }
    },
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      dragCount.current = 0;
      setDragging(false);
      const f = e.dataTransfer?.files?.[0];
      if (f) onDropFile(f);
    },
  };

  return (
    <div className="ws-onboarding" {...dragProps}>
      <input
        ref={fileInput}
        type="file"
        accept=".xlsx"
        hidden
        onChange={(e) => {
          if (e.target.files?.[0]) onDropFile(e.target.files[0]);
          e.target.value = "";
        }}
      />
      {/* This is the first screen anyone ever sees, and it used to open with
          "טרם נטען קובץ" -- a status, not an introduction. Say what the
          product does first, then ask for the file. */}
      <div className="ws-onboarding-inner">
        <div className="ws-onboarding-head">
          <h1>שיבוץ תלמידות לכיתות ז׳</h1>
          <p>העלו את רשימת התלמידות, ואז נסחו את כללי השיבוץ בשיחה — הרכב הכיתות ייבנה סביבם.</p>
        </div>
        <div className={clsx("ws-onboarding-box", dragging && "dragging")}>
          <Icon name="upload" size={24} />
          <h2>{phase === "error" ? "לא הצלחנו לטעון את הנתונים" : "גררו לכאן קובץ אקסל"}</h2>
          <p>
            {phase === "error"
              ? "נסו שוב עם קובץ ‎.xlsx‎ אחר, או טענו את קובץ ברירת המחדל."
              : "קובץ ‎.xlsx‎ עם רשימת התלמידות."}
          </p>
          <div className="ws-onboarding-actions">
            <Button onClick={() => fileInput.current?.click()} disabled={busy}>
              בחירת קובץ
            </Button>
            <Button variant="secondary" onClick={() => void loadSampleFile()} disabled={busy}>
              {busy ? "טוענת…" : "שימוש בקובץ לדוגמה"}
            </Button>
          </div>
        </div>
        <p className="ws-onboarding-foot">
          העמודות מזוהות אוטומטית, כולל עמודות ייחודיות לבית הספר שלכם.
          {onBack && (
            <>
              {" · "}
              <button type="button" className="ws-link" style={{ display: "inline" }} onClick={onBack}>
                חזרה
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
