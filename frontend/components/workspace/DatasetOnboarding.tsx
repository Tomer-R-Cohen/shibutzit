"use client";

import { DragEvent, useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import clsx from "clsx";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import { ApiError, applyMapping, getFriendshipDiagnostics, getMappingGuess, getStudents, getValidation, loadWorkbook, type MappingGuessResponse } from "@/lib/api";
import { ensureDataReady } from "@/lib/bootstrap";
import { setFlag } from "@/lib/steps";
import type { DataProblem } from "@/lib/workspace";

export interface DatasetReadyInfo {
  studentCount: number;
  schoolCount: number;
  levelCount: number;
  warningCount: number;
  levelCounts: Record<string, number>;
  detectedFields: string[];
  missingFields: string[];
  friendshipCount: number;
}

// Zero asks the existing upload endpoint to infer the table bounds. The
// The bundled stress workbook uses its known layout through ensureDataReady;
// user files must not inherit any sample-specific row limits.
const DEFAULT_LOAD = { headerRow: 0, firstDataRow: 0, lastDataRow: 0 };
type LoadStage = "upload" | "columns" | "mapping" | "validation";
export interface DatasetOnboardingPreview {
  phase: "needsFile" | "mapping" | "error";
  busy?: boolean;
  loadStage?: LoadStage;
  selectedFileName?: string;
  mappingGuess?: MappingGuessResponse | null;
}
const LOAD_STAGES: { id: LoadStage; label: string }[] = [
  { id: "upload", label: "קוראת את הקובץ" },
  { id: "columns", label: "מזהה עמודות" },
  { id: "mapping", label: "מתאימה את הנתונים" },
  { id: "validation", label: "בודקת את רשימת התלמידות" },
];

// These two fields have safe data-model defaults: row order becomes a stable
// generated id, and a missing origin column means no student is flagged. All
// other unresolved required fields need one focused question before import.
const SAFE_UNMAPPED_FIELDS = new Set(["student_id", "ethiopian_origin"]);
function fieldsNeedingChoice(guess: MappingGuessResponse, mapping: Record<string, string | null>) {
  return guess.required_fields.filter((field) => !SAFE_UNMAPPED_FIELDS.has(field) && !mapping[field]);
}

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
  preview,
}: {
  onReady: (info: DatasetReadyInfo) => void;
  onWarning: (problems: DataProblem[]) => void;
  onBack?: () => void;
  /** Development-only visual state. Runtime callers leave this undefined. */
  preview?: DatasetOnboardingPreview;
}) {
  const [phase, setPhase] = useState<"needsFile" | "mapping" | "error">(preview?.phase ?? "needsFile");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(preview?.busy ?? false);
  const [loadStage, setLoadStage] = useState<LoadStage>(preview?.loadStage ?? "upload");
  const [selectedFileName, setSelectedFileName] = useState(preview?.selectedFileName ?? "");
  const [mappingGuess, setMappingGuess] = useState<MappingGuessResponse | null>(preview?.mappingGuess ?? null);
  const [mappingDraft, setMappingDraft] = useState<Record<string, string | null>>({ ...(preview?.mappingGuess?.mapping ?? {}) });
  const fileInput = useRef<HTMLInputElement>(null);
  const dragCount = useRef(0);

  const finishReady = useCallback(
    async (problems: string[]) => {
      const [st, validation, friendship, mappingInfo] = await Promise.all([
        getStudents(),
        getValidation().catch(() => null),
        getFriendshipDiagnostics().catch(() => null),
        getMappingGuess().catch(() => null),
      ]);
      const schools = new Set(st.rows.map((s) => s.current_school).filter((v): v is string => !!v));
      const levelCounts: Record<string, number> = {};
      for (const s of st.rows) {
        const level = s.academic_level;
        if (!level) continue;
        levelCounts[level] = (levelCounts[level] ?? 0) + 1;
      }
      const fieldOptions = [
        ["current_school", "בית ספר נוכחי"],
        ["academic_level", "רמה לימודית"],
        ["friend_requests_raw", "בקשות חברות"],
        ["inclusion", "שילוב"],
        ["hamar", 'ח״מ'],
        ["differential", "דיפרנציאליות"],
        ["ethiopian_origin", "מוצא אתיופי"],
      ] as const;
      // Presence is a property of the workbook mapping, not of normalized
      // values. Missing flag columns become `false` in the student model;
      // inspecting values would therefore falsely claim those columns were
      // found in the uploaded file.
      const isMapped = (key: string) => Boolean(mappingInfo?.mapping[key]);
      const detectedFields = fieldOptions.filter(([key]) => isMapped(key)).map(([, label]) => label);
      const missingFields = fieldOptions.filter(([key]) => !isMapped(key)).map(([, label]) => label);
      const validationProblems: DataProblem[] = (validation?.issues ?? [])
        .map((issue) => {
          const message = String(issue["הודעה"] ?? "").trim();
          const studentIds = String(issue["תלמידות"] ?? "")
            .split(",")
            .map((value) => Number(value.trim()))
            .filter(Number.isFinite);
          const field = message.includes("הישגים לימודיים")
            ? "academic_level" as const
            : message.includes("בית ספר נוכחי")
              ? "current_school" as const
              : undefined;
          return { message, studentIds, field };
        })
        .filter((problem) => Boolean(problem.message));
      const dataProblems: DataProblem[] = [
        ...problems.map((message) => ({ message })),
        ...validationProblems,
      ];
      onReady({
        studentCount: st.rows.length,
        schoolCount: schools.size,
        levelCount: Object.keys(levelCounts).length,
        warningCount: (friendship?.unmatched_count ?? 0) + (friendship?.ambiguous_count ?? 0),
        levelCounts,
        detectedFields,
        missingFields,
        friendshipCount: friendship?.matched_count ?? 0,
      });
      if (dataProblems.length > 0) onWarning(dataProblems);
    },
    [onReady, onWarning]
  );

  // Loading the bundled sample is now an explicit button, not something
  // that happens on mount -- see Welcome. `ensureDataReady` is still the
  // path it takes, because it handles the load/guess/apply sequence.
  const loadSampleFile = useCallback(async () => {
    setBusy(true);
    setSelectedFileName("קובץ לדוגמה");
    setLoadStage("upload");
    try {
      const rd = await ensureDataReady();
      if (rd.needsMapping) {
        const guess = await getMappingGuess();
        setMappingGuess(guess);
        setMappingDraft({ ...guess.mapping });
        setPhase("mapping");
        return;
      }
      setLoadStage("columns");
      const guess = await getMappingGuess().catch(() => null);
      setLoadStage("validation");
      await finishReady(guess?.problems ?? []);
    } catch {
      setPhase("error");
    } finally {
      setBusy(false);
    }
  }, [finishReady]);

  async function handleLoad(file?: File) {
    setBusy(true);
    setSelectedFileName(file?.name ?? "קובץ לדוגמה");
    setLoadStage("upload");
    try {
      await loadWorkbook({ useDefault: !file, ...DEFAULT_LOAD, file });
      setFlag("loaded", true);
      setLoadStage("columns");
      const guess = await getMappingGuess();
      if (fieldsNeedingChoice(guess, guess.mapping).length > 0) {
        setMappingGuess(guess);
        setMappingDraft({ ...guess.mapping });
        setPhase("mapping");
        return;
      }
      setLoadStage("mapping");
      await applyMapping(guess.mapping, guess.manual_fields);
      setFlag("mapped", true);
      setLoadStage("validation");
      await finishReady(guess.problems);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "לא הצלחתי לטעון את הקובץ");
      setPhase("needsFile");
    } finally {
      setBusy(false);
    }
  }

  async function confirmMapping() {
    if (!mappingGuess || fieldsNeedingChoice(mappingGuess, mappingDraft).length > 0) return;
    setBusy(true);
    setLoadStage("mapping");
    try {
      await applyMapping(mappingDraft, mappingGuess.manual_fields);
      setFlag("mapped", true);
      setLoadStage("validation");
      await finishReady([]);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "לא הצלחתי להתאים את העמודות");
    } finally {
      setBusy(false);
    }
  }

  function chooseAnotherFile() {
    setMappingGuess(null);
    setMappingDraft({});
    setPhase("needsFile");
    fileInput.current?.click();
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
        <div className={clsx("ws-onboarding-box", dragging && "dragging", busy && "busy", phase === "mapping" && "mapping", phase === "error" && "error")} aria-busy={busy}>
          {phase === "mapping" && mappingGuess && !busy ? (
            <div className="ws-mapping-review">
              <span className="ws-mapping-icon" aria-hidden><Icon name="sliders" size={18} /></span>
              <div className="ws-mapping-copy">
                <h2>צריך לזהות עוד כמה עמודות</h2>
                <p>לא ניחשתי בבטחה מה משמעות העמודות הבאות. בחרו את העמודה המתאימה מהקובץ.</p>
              </div>
              <div className="ws-mapping-fields">
                {fieldsNeedingChoice(mappingGuess, mappingGuess.mapping).map((field) => (
                  <label key={field}>
                    <span>{mappingGuess.labels[field] ?? field}</span>
                    <select
                      value={mappingDraft[field] ?? ""}
                      onChange={(event) => setMappingDraft((current) => ({ ...current, [field]: event.target.value || null }))}
                    >
                      <option value="">בחרו עמודה…</option>
                      {mappingGuess.columns.map((column) => {
                        const usedElsewhere = Object.entries(mappingDraft).some(([otherField, selected]) => otherField !== field && selected === column);
                        return <option key={column} value={column} disabled={usedElsewhere}>{column}</option>;
                      })}
                    </select>
                  </label>
                ))}
              </div>
              <div className="ws-onboarding-actions">
                <Button onClick={() => void confirmMapping()} disabled={fieldsNeedingChoice(mappingGuess, mappingDraft).length > 0}>אישור והמשך</Button>
                <Button variant="secondary" onClick={chooseAnotherFile}>בחירת קובץ אחר</Button>
              </div>
            </div>
          ) : (
            <>
              {busy ? <span className="ws-upload-spinner" aria-hidden /> : <Icon name={phase === "error" ? "warning" : "upload"} size={24} />}
              <h2>{busy ? "אני בודקת את הקובץ" : phase === "error" ? "לא הצלחנו לטעון את הנתונים" : "גררו לכאן קובץ אקסל"}</h2>
              <p aria-live="polite">
                {busy
                  ? selectedFileName
                  : phase === "error"
                    ? "נסו שוב עם קובץ ‎.xlsx‎ אחר, או טענו את קובץ ברירת המחדל."
                    : "קובץ ‎.xlsx‎ עם רשימת התלמידות."}
              </p>
              {busy ? (
            <ol className="ws-upload-stages" aria-label="התקדמות ניתוח הקובץ">
              {LOAD_STAGES.map((stage, index) => {
                const currentIndex = LOAD_STAGES.findIndex((item) => item.id === loadStage);
                const state = index < currentIndex ? "complete" : index === currentIndex ? "current" : "pending";
                return (
                  <li key={stage.id} className={state} aria-current={state === "current" ? "step" : undefined}>
                    <span aria-hidden>{state === "complete" ? "✓" : index + 1}</span>
                    {stage.label}
                  </li>
                );
              })}
            </ol>
              ) : (
                <div className="ws-onboarding-actions">
                  <Button onClick={() => fileInput.current?.click()}>בחירת קובץ</Button>
                  <Button variant="secondary" onClick={() => void loadSampleFile()}>
                    שימוש בקובץ לדוגמה
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
        <div className="ws-onboarding-assurance">
          <Icon name="lock" size={13} />
          <span>לפני יצירת שיבוץ נציג מה זיהינו בקובץ ואת כל כללי החובה הפעילים.</span>
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
