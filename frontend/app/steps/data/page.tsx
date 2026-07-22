"use client";

import { useEffect, useId, useState } from "react";
import { toast } from "sonner";
import clsx from "clsx";
import { Button, ErrorBanner, InfoBanner, Skeleton, SimpleTable, StatTile, StatusIndicator } from "@/components/ui/primitives";
import { AccordionSection } from "@/components/Accordion";
import {
  ApiError,
  FeasibilityResponse,
  FriendshipDiagnostics,
  MappingGuessResponse,
  PreviewResponse,
  ValidationResponse,
  applyMapping,
  getFeasibility,
  getFriendshipDiagnostics,
  getMappingGuess,
  getPreview,
  getValidation,
  importManualEntry,
  loadWorkbook,
  updateManualEntry,
} from "@/lib/api";
import { FLAGS_CHANGED_EVENT, getFlags, getSummaries, resetFlags, setFlag, setSummary } from "@/lib/steps";

type Section = "load" | "mapping" | "checks";

export default function DataStep() {
  const [open, setOpen] = useState<Section>(() => {
    const f = getFlags();
    if (!f.loaded) return "load";
    if (!f.mapped) return "mapping";
    return "checks";
  });
  const [summaries, setSummaries] = useState<Record<string, string>>({});
  const [flags, setFlagsState] = useState(getFlags());

  useEffect(() => {
    const refresh = () => {
      setSummaries(getSummaries());
      setFlagsState(getFlags());
    };
    refresh();
    window.addEventListener(FLAGS_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(FLAGS_CHANGED_EVENT, refresh);
  }, []);

  function complete(section: Section, summary: string, next?: Section) {
    setSummary(section, summary);
    if (next) setOpen(next);
  }

  return (
    <div className="flex flex-col divide-y divide-slate-100">
      <AccordionSection
        index={1}
        title="טעינת קובץ"
        summary={summaries.load}
        done={flags.loaded}
        open={open === "load"}
        onToggle={() => setOpen("load")}
      >
        <LoadSection onDone={(s) => complete("load", s, "mapping")} />
      </AccordionSection>

      <AccordionSection
        index={2}
        title="מיפוי עמודות"
        summary={summaries.mapping}
        done={flags.mapped}
        disabled={!flags.loaded}
        open={open === "mapping"}
        onToggle={() => flags.loaded && setOpen("mapping")}
      >
        {open === "mapping" && <MappingSection onDone={(s) => complete("mapping", s, "checks")} />}
      </AccordionSection>

      <AccordionSection
        index={3}
        title="בדיקת תקינות והיתכנות"
        summary={summaries.checks}
        done={Boolean(summaries.checks)}
        disabled={!flags.mapped}
        open={open === "checks"}
        onToggle={() => flags.mapped && setOpen("checks")}
      >
        {open === "checks" && <ChecksSection onDone={(s) => complete("checks", s)} />}
      </AccordionSection>
    </div>
  );
}

function LoadSection({ onDone }: { onDone: (summary: string) => void }) {
  const [useDefault, setUseDefault] = useState(true);
  const [file, setFile] = useState<File | undefined>(undefined);
  const [headerRow, setHeaderRow] = useState(4);
  const [firstDataRow, setFirstDataRow] = useState(5);
  const [lastDataRow, setLastDataRow] = useState(221);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);

  async function handleLoad() {
    setLoading(true);
    try {
      const res = await loadWorkbook({ useDefault, headerRow, firstDataRow, lastDataRow, file });
      resetFlags();
      setFlag("loaded", true);
      const p = await getPreview();
      setPreview(p);
      const summary = `${res.row_count} שורות · גיליון '${res.active_sheet}'`;
      toast.success(`נטען בהצלחה: ${summary}`);
      onDone(summary);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "שגיאה בטעינת הקובץ");
    } finally {
      setLoading(false);
    }
  }

  const rowInput = "w-16 rounded border border-slate-300 px-1.5 py-1 text-sm text-slate-800 tabular-nums";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={useDefault} onChange={(e) => setUseDefault(e.target.checked)} />
          קובץ ברירת המחדל
        </label>

        {!useDefault && <input type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0])} className="text-sm" />}

        <div className="flex items-center gap-3 text-xs text-slate-500">
          <label className="flex items-center gap-1.5">
            כותרות
            <input type="number" min={1} value={headerRow} onChange={(e) => setHeaderRow(Number(e.target.value))} className={rowInput} />
          </label>
          <label className="flex items-center gap-1.5">
            משורה
            <input type="number" min={1} value={firstDataRow} onChange={(e) => setFirstDataRow(Number(e.target.value))} className={rowInput} />
          </label>
          <label className="flex items-center gap-1.5">
            עד שורה
            <input type="number" min={0} value={lastDataRow} onChange={(e) => setLastDataRow(Number(e.target.value))} className={rowInput} />
          </label>
        </div>

        <Button disabled={loading} onClick={handleLoad}>
          {loading ? "טוען..." : "טען קובץ"}
        </Button>
      </div>

      {preview && (
        <details className="flex flex-col gap-2">
          <summary className="cursor-pointer text-sm text-slate-500">
            תצוגה מקדימה · {preview.total_rows} שורות, {preview.columns.length} עמודות
          </summary>
          <div className="mt-3">
            <SimpleTable columns={preview.columns} rows={preview.rows} />
          </div>
        </details>
      )}
    </div>
  );
}

const MANUAL_SENTINEL = "__manual__";

function MappingSection({ onDone }: { onDone: (summary: string) => void }) {
  const [guess, setGuess] = useState<MappingGuessResponse | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [manualFields, setManualFields] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<{ student_count: number; manual_fields_needed: string[] } | null>(null);
  const [manualRows, setManualRows] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    getMappingGuess()
      .then((g) => {
        setGuess(g);
        setMapping(g.mapping);
        setManualFields(new Set(g.manual_fields));
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "שגיאה"))
      .finally(() => setLoading(false));
  }, []);

  function updateField(field: string, value: string) {
    if (value === MANUAL_SENTINEL) {
      setManualFields((prev) => new Set(prev).add(field));
      setMapping((prev) => ({ ...prev, [field]: null }));
    } else {
      setManualFields((prev) => {
        const next = new Set(prev);
        next.delete(field);
        return next;
      });
      setMapping((prev) => ({ ...prev, [field]: value }));
    }
  }

  async function handleApply() {
    if (!guess) return;
    setApplying(true);
    try {
      const res = await applyMapping(mapping, Array.from(manualFields));
      setApplied(res);
      setManualRows(res.manual_entry);
      setFlag("mapped", true);
      const summary = `${res.student_count} תלמידות`;
      toast.success(`נבנתה טבלה עם ${summary}`);
      if (res.manual_fields_needed.length === 0) onDone(summary);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בהחלת המיפוי");
    } finally {
      setApplying(false);
    }
  }

  async function handleManualCellChange(rowIdx: number, key: string, value: string | boolean) {
    setManualRows((prev) => prev.map((r, i) => (i === rowIdx ? { ...r, [key]: value } : r)));
  }

  async function handleSaveManual() {
    try {
      const res = await updateManualEntry(manualRows);
      setManualRows(res.manual_entry);
      toast.success("הוחלו הנתונים הידניים על טבלת התלמידות");
      onDone(`${res.student_count} תלמידות · כולל שדות ידניים`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה");
    }
  }

  async function handleImport(file: File) {
    try {
      const res = await importManualEntry(file);
      setManualRows(res.rows);
      toast.success("טבלת ההזנה הידנית עודכנה מהקובץ שיובא");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בייבוא");
    }
  }

  if (loading) return <Skeleton className="h-48 w-full" />;
  if (error) return <ErrorBanner message={error} />;
  if (!guess) return null;

  const problems = computeProblems(guess, mapping, manualFields);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-x-10 gap-y-0.5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
        {guess.required_fields.map((f) => (
          <FieldSelect
            key={f}
            label={guess.labels[f] ?? f}
            value={manualFields.has(f) ? MANUAL_SENTINEL : mapping[f] ?? MANUAL_SENTINEL}
            columns={guess.columns}
            onChange={(v) => updateField(f, v)}
          />
        ))}
      </div>

      <details>
        <summary className="cursor-pointer text-sm text-slate-500">
          שדות אופציונליים ({guess.optional_fields.length})
        </summary>
        <div className="mt-3 grid grid-cols-1 gap-x-10 gap-y-0.5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {guess.optional_fields.map((f) => (
            <FieldSelect
              key={f}
              label={guess.labels[f] ?? f}
              value={manualFields.has(f) ? MANUAL_SENTINEL : mapping[f] ?? MANUAL_SENTINEL}
              columns={guess.columns}
              onChange={(v) => updateField(f, v)}
            />
          ))}
        </div>
      </details>

      {problems.length > 0 ? problems.map((p, i) => <ErrorBanner key={i} message={p} />) : <InfoBanner tone="success" message="המיפוי תקין." />}

      <div>
        <Button disabled={applying || problems.length > 0} onClick={handleApply}>
          {applying ? "מעבד..." : "בנה טבלת תלמידות"}
        </Button>
      </div>

      {applied && applied.manual_fields_needed.length > 0 && (
        <div className="flex flex-col gap-3 border-t border-slate-100 pt-4">
          <p className="text-sm text-slate-500">
            שדות שדורשים הזנה ידנית: {applied.manual_fields_needed.map((f) => guess.labels[f] ?? f).join(", ")}
          </p>
          <label className="text-sm text-slate-500">
            ייבוא טבלה משלימה (CSV/Excel, לפי מזהה תלמידה)
            <input type="file" accept=".csv,.xlsx" className="mt-1 block text-sm" onChange={(e) => e.target.files?.[0] && handleImport(e.target.files[0])} />
          </label>
          <ManualEditor rows={manualRows} onChange={handleManualCellChange} />
          <div>
            <Button variant="secondary" onClick={handleSaveManual}>
              החל שדות ידניים
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function computeProblems(guess: MappingGuessResponse, mapping: Record<string, string | null>, manualFields: Set<string>) {
  const problems: string[] = [];
  for (const f of guess.required_fields) {
    if (f === "ethiopian_origin") continue;
    const col = mapping[f];
    if (!col && !manualFields.has(f)) problems.push(`השדה '${guess.labels[f] ?? f}' לא מופה.`);
  }
  return problems;
}

// The backend already guesses the mapping, so the common case is "confirm
// what's there" — not "pick from a list". Shows the resolved column as plain
// text and only turns into a type-ahead field when the user chooses to change
// it, which keeps a screen of ~15 fields readable instead of a wall of selects.
function FieldSelect({ label, value, columns, onChange }: { label: string; value: string; columns: string[]; onChange: (v: string) => void }) {
  const listId = useId();
  const [editing, setEditing] = useState(false);
  const isManual = value === MANUAL_SENTINEL;

  if (editing) {
    return (
      <div className="flex items-center gap-2 py-1 text-sm">
        <span className="w-32 shrink-0 truncate text-slate-500">{label}</span>
        <input
          autoFocus
          list={listId}
          defaultValue={isManual ? "" : value}
          placeholder="הקלידו שם עמודה"
          onChange={(e) => {
            if (columns.includes(e.target.value)) {
              onChange(e.target.value);
              setEditing(false);
            }
          }}
          onBlur={() => setEditing(false)}
          className="min-w-0 flex-1 border-b border-teal-600 bg-transparent px-1 py-0.5 focus:outline-none"
        />
        <datalist id={listId}>
          {columns.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <button
          onMouseDown={(e) => {
            e.preventDefault();
            onChange(MANUAL_SENTINEL);
            setEditing(false);
          }}
          className="shrink-0 text-xs text-slate-400 hover:text-slate-700"
        >
          ידני
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className="flex w-full items-baseline gap-2 py-1 text-start text-sm hover:bg-slate-50"
      aria-label={`${label}: ${isManual ? "הזנה ידנית" : value}. לחצו לשינוי`}
    >
      <span className="w-32 shrink-0 truncate text-slate-500">{label}</span>
      <span
        className={clsx(
          "min-w-0 flex-1 truncate border-b border-dashed border-slate-200",
          isManual ? "text-amber-700" : "text-slate-800"
        )}
      >
        {isManual ? "הזנה ידנית" : value}
      </span>
    </button>
  );
}

function ManualEditor({ rows, onChange }: { rows: Record<string, unknown>[]; onChange: (rowIdx: number, key: string, value: string | boolean) => void }) {
  if (rows.length === 0) return <p className="text-sm text-slate-400">אין שורות</p>;
  const cols = Object.keys(rows[0]);
  return (
    <div className="max-h-96 overflow-auto">
      <table className="w-full text-right text-sm">
        <thead className="sticky top-0 bg-white">
          <tr>
            {cols.map((c) => (
              <th key={c} className="border-b border-slate-200 px-2 py-1.5 font-medium text-slate-500">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c} className="px-2 py-1">
                  {typeof row[c] === "boolean" ? (
                    <input type="checkbox" checked={row[c] as boolean} onChange={(e) => onChange(i, c, e.target.checked)} />
                  ) : (
                    <input
                      type="text"
                      value={(row[c] as string) ?? ""}
                      onChange={(e) => onChange(i, c, e.target.value)}
                      className="w-full min-w-[6rem] rounded border border-transparent bg-transparent px-1 py-0.5 hover:border-slate-300 focus:border-teal-500 focus:outline-none"
                    />
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Validation, friendship-name matching and constraint feasibility are all
// read-only reports that run automatically — they were three separate steps
// but require no user input, so they read better as one status page.
function ChecksSection({ onDone }: { onDone: (summary: string) => void }) {
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const [friendship, setFriendship] = useState<FriendshipDiagnostics | null>(null);
  const [feasibility, setFeasibility] = useState<FeasibilityResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getValidation(), getFriendshipDiagnostics(), getFeasibility()])
      .then(([v, f, fe]) => {
        setValidation(v);
        setFriendship(f);
        setFeasibility(fe);
        setFlag("validated", !v.has_errors);
        const parts = [v.has_errors ? `${v.error_count} שגיאות חוסמות` : "ללא שגיאות חוסמות"];
        if (!fe.all_feasible) parts.push("אילוצים לא ישימים");
        onDone(parts.join(" · "));
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "שגיאה"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <Skeleton className="h-48 w-full" />;
  if (error) return <ErrorBanner message={error} />;
  if (!validation || !friendship || !feasibility) return null;

  return (
    <div className="flex flex-col gap-4">
      {/* Headline status */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <StatusIndicator
          status={validation.has_errors ? "blocking" : "valid"}
          text={validation.has_errors ? `${validation.error_count} שגיאות חוסמות` : "נתונים תקינים"}
        />
        <StatusIndicator
          status={feasibility.all_feasible ? "valid" : "warning"}
          text={feasibility.all_feasible ? "כל האילוצים ישימים" : "חלק מהאילוצים אינם ישימים"}
        />
        <StatusIndicator
          status={friendship.unmatched_count + friendship.ambiguous_count === 0 ? "valid" : "warning"}
          text={`${friendship.matched_count} בקשות חברות זוהו`}
        />
      </div>

      {/* Composition */}
      <div className="flex flex-wrap gap-x-6 gap-y-3">
        <StatTile label='סה"כ תלמידות' value={feasibility.total_students} />
        <StatTile label="מוצא אתיופי" value={feasibility.ethiopian_count} />
        <StatTile label="דיפרנציאליות" value={feasibility.differential_count} />
        <StatTile label="שילוב" value={feasibility.inclusion_count} />
        <StatTile label='ח"מ' value={feasibility.hamar_count} />
      </div>

      {!feasibility.all_feasible && (
        <InfoBanner tone="warning" message="ניתן להפוך אילוצים לא ישימים לאילוצים מועדפים בשלב כללי השיבוץ." />
      )}

      {validation.issues.length > 0 && (
        <details open={validation.has_errors}>
          <summary className="cursor-pointer text-sm text-slate-500">ממצאי אימות ({validation.issues.length})</summary>
          <div className="mt-3">
            <SimpleTable columns={["קטגוריה", "חומרה", "הודעה", "תלמידות"]} rows={validation.issues} />
          </div>
        </details>
      )}

      {!feasibility.all_feasible && (
        <details>
          <summary className="cursor-pointer text-sm text-slate-500">פירוט היתכנות אילוצים</summary>
          <div className="mt-3">
            <SimpleTable columns={["חוק", "אפשרי", "הסבר"]} rows={feasibility.findings} />
          </div>
        </details>
      )}

      {friendship.unmatched_rows.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm text-slate-500">
            בקשות חברות שלא זוהו ({friendship.unmatched_count} לא מותאמים, {friendship.ambiguous_count} דו-משמעיים)
          </summary>
          <div className="mt-3">
            <SimpleTable columns={Object.keys(friendship.unmatched_rows[0])} rows={friendship.unmatched_rows} />
          </div>
        </details>
      )}
    </div>
  );
}
