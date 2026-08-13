"use client";

import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import clsx from "clsx";
import { Button, EmptyState } from "@/components/ui/primitives";
import { DataPageSkeleton } from "@/components/Skeletons";
import { Icon } from "@/components/Icon";
import {
  ApiError,
  MappingGuessResponse,
  StudentRecord,
  applyMapping,
  clearSession,
  getMappingGuess,
  getPreview,
  getStudents,
  loadWorkbook,
  updateManualEntry,
} from "@/lib/api";
import { resetFlags, setFlag } from "@/lib/steps";

const DEFAULT_FILE_NAME = "רשימה כללית לאיזונית.xlsx";
const LEVEL_LETTER: Record<string, string> = { "מצטיינת": "מ", "בינונית": "ב", "חלשה": "ח" };

type CatKey = "inclusion" | "hamar" | "ethiopian_origin" | "differential";
const FILTERS: { key: CatKey; cls: string; label: string }[] = [
  { key: "inclusion", cls: "incl", label: "שילוב" },
  { key: "hamar", cls: "hamar", label: 'ח"מ' },
  { key: "ethiopian_origin", cls: "eth", label: "מוצא אתיופי" },
  { key: "differential", cls: "diff", label: "דיפרנציאלית" },
];

function fullName(s: StudentRecord) {
  return `${(s.first_name ?? "").toString().trim()} ${(s.last_name ?? "").toString().trim()}`.trim() || `#${s.student_id}`;
}

/**
 * The data zone: load/upload, column mapping, and manual category entry --
 * everything that used to be the standalone /steps/data page. Once data is
 * loaded and mapped it collapses to a compact summary (this is the zone
 * users interact with least once things are working); it auto-expands if
 * the mapping actually needs attention. `onChanged` lets the host page
 * re-check overall readiness after a load/remap/manual-entry save.
 *
 * Deliberately does NOT call ensureDataReady() itself -- the host page
 * (app/page.tsx) is the single place that triggers the initial
 * load-the-default-workbook bootstrap, and only mounts this zone once that
 * has settled. Two components racing to bootstrap the same session
 * concurrently is exactly the bug that showed up (and got fixed) between
 * this page and the chat/constraints zone in the previous refactor -- this
 * zone assumes a workbook already exists by the time it mounts.
 */
export default function DataZone({ onChanged }: { onChanged?: () => void }) {
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cleared, setCleared] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [srcOpen, setSrcOpen] = useState(false);
  const [students, setStudents] = useState<StudentRecord[]>([]);
  const [guess, setGuess] = useState<MappingGuessResponse | null>(null);
  const [source, setSource] = useState<{ rows: number; sheet: string }>({ rows: 0, sheet: "" });
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<CatKey | null>(null);
  const [headerRow, setHeaderRow] = useState(4);
  const [firstRow, setFirstRow] = useState(5);
  const [lastRow, setLastRow] = useState(221);

  const fileInput = useRef<HTMLInputElement>(null);
  const dragCount = useRef(0);
  const studentsRef = useRef(students);
  useEffect(() => {
    studentsRef.current = students;
  }, [students]);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  async function loadEverything() {
    const [g, p] = await Promise.all([getMappingGuess(), getPreview()]);
    setGuess(g);
    // Auto-expand only when mapping actually needs attention -- otherwise
    // default to the collapsed summary, since this zone matters least once
    // things are already working.
    if (g.problems.length > 0) setExpanded(true);
    setSource({ rows: p.total_rows, sheet: p.sheet_names[0] ?? "" });
    try {
      const st = await getStudents();
      setStudents(st.rows);
    } catch {
      setStudents([]);
    }
  }

  useEffect(() => {
    (async () => {
      try {
        await loadEverything();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "שגיאה בטעינת הנתונים.");
      } finally {
        setBooting(false);
      }
    })();
    return () => clearTimeout(saveTimer.current);
  }, []);

  // Close the source popover on Escape while it is open.
  useEffect(() => {
    if (!srcOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSrcOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [srcOpen]);

  function scheduleSave() {
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      setSaveState("saving");
      try {
        const rows = studentsRef.current.map((s) => ({
          student_id: s.student_id,
          differential: !!s.differential,
          inclusion: !!s.inclusion,
          hamar: !!s.hamar,
          friend_requests_raw: (s.friend_requests_raw as string) ?? "",
        }));
        await updateManualEntry(rows);
        setSaveState("saved");
        onChanged?.();
      } catch (e) {
        setSaveState("idle");
        toast.error(e instanceof ApiError ? e.message : "שגיאה בשמירה");
      }
    }, 700);
  }

  function patch(id: number, key: "inclusion" | "hamar" | "differential" | "friend_requests_raw", value: boolean | string) {
    setStudents((prev) => prev.map((s) => (s.student_id === id ? { ...s, [key]: value } : s)));
    scheduleSave();
  }

  async function handleLoad(opts: { file?: File }) {
    setSrcOpen(false);
    setBooting(true);
    try {
      await loadWorkbook({ useDefault: !opts.file, headerRow, firstDataRow: firstRow, lastDataRow: lastRow, file: opts.file });
      setFlag("loaded", true);
      const g = await getMappingGuess();
      await applyMapping(g.mapping, g.manual_fields);
      setFlag("mapped", true);
      await loadEverything();
      setCleared(false);
      toast.success("הקובץ נטען");
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בטעינת הקובץ");
    } finally {
      setBooting(false);
    }
  }

  async function handleClear() {
    setSrcOpen(false);
    try {
      await clearSession();
      resetFlags();
      setStudents([]);
      setGuess(null);
      setSource({ rows: 0, sheet: "" });
      setSaveState("idle");
      setCleared(true);
      setExpanded(false);
      toast.success("הקובץ הוסר. גררו או בחרו קובץ חדש.");
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה במחיקת הקובץ");
    }
  }

  function onDropFile(file: File) {
    if (!/\.xlsx$/i.test(file.name)) {
      toast.error("יש לבחור קובץ .xlsx");
      return;
    }
    handleLoad({ file });
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

  const tallies = useMemo(() => {
    const c = { inclusion: 0, hamar: 0, ethiopian_origin: 0, differential: 0 };
    for (const s of students) {
      if (s.inclusion) c.inclusion++;
      if (s.hamar) c.hamar++;
      if (s.ethiopian_origin) c.ethiopian_origin++;
      if (s.differential) c.differential++;
    }
    return c;
  }, [students]);

  const visible = useMemo(() => {
    const q = query.trim();
    return students.filter((s) => {
      if (filter && !s[filter]) return false;
      if (q && !fullName(s).includes(q)) return false;
      return true;
    });
  }, [students, query, filter]);

  // Trust signal: how many of the detected fields the importer mapped on its own.
  const detectedCount = useMemo(() => {
    if (!guess) return 0;
    return [...guess.required_fields, ...guess.optional_fields].filter(
      (f) => guess.mapping[f] && !guess.manual_fields.includes(f)
    ).length;
  }, [guess]);

  if (error) return <EmptyState title="שגיאה" description={error} />;

  if (booting) return <DataPageSkeleton />;

  return (
    <div className="cw" {...dragProps}>
      {dragging && (
        <div className="dp-drag-overlay">
          <div className="box">
            <Icon name="upload" size={32} />
            שחררו כדי לטעון את הקובץ
          </div>
        </div>
      )}
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

      {cleared ? (
        <div className={clsx("dp-dropzone", dragging && "active")} style={{ maxWidth: 540, margin: "0 auto" }}>
          <Icon name="file" size={30} className="dp-dz-icon" />
          <h3>לא טעון קובץ</h3>
          <p>גררו לכאן קובץ אקסל (.xlsx) או בחרו קובץ מהמחשב</p>
          <div className="dp-drop-actions">
            <Button onClick={() => fileInput.current?.click()}>בחירת קובץ</Button>
            <Button variant="secondary" onClick={() => handleLoad({})}>טעינת קובץ ברירת המחדל</Button>
          </div>
        </div>
      ) : !expanded ? (
        <div className="dz-summary">
          <div className="dz-summary-main">
            <span className="ico" aria-hidden>
              XLS
            </span>
            <div className="txt">
              <span className="n">{DEFAULT_FILE_NAME}</span>
              <span className="m">
                <span className="d" aria-hidden />
                {students.length} תלמידות · {detectedCount} עמודות זוהו
              </span>
            </div>
          </div>
          <div className="dz-summary-tallies">
            {FILTERS.map((f) => (
              <span key={f.key} className="dz-tally">
                <span className="d" style={{ background: `var(--cw-${f.cls})` }} aria-hidden />
                {f.label} {tallies[f.key]}
              </span>
            ))}
          </div>
          <Button variant="secondary" size="sm" onClick={() => setExpanded(true)}>
            עריכת נתונים
          </Button>
        </div>
      ) : (
        <div className="dp">
          {/* header: title · source pill (with popover) · collapse */}
          <div className="dp-head">
            <div className="dp-title">
              <h1>רשימת התלמידות</h1>
              <span className="dp-count cw-num">{students.length} תלמידות</span>
            </div>
            <div className="dp-spacer" />

            <div className="dp-src-wrap">
              <button
                type="button"
                className="dp-src"
                aria-expanded={srcOpen}
                aria-haspopup="dialog"
                onClick={() => setSrcOpen((o) => !o)}
              >
                <span className="ico" aria-hidden>
                  XLS
                </span>
                <span className="txt">
                  <span className="n">{DEFAULT_FILE_NAME}</span>
                  <span className="m">
                    <span className="d" aria-hidden />
                    {source.rows} שורות · {detectedCount} עמודות זוהו
                  </span>
                </span>
                <Icon name="chevron" size={15} className="chev" />
              </button>

              {srcOpen && (
                <>
                  <div className="dp-pop-scrim" onClick={() => setSrcOpen(false)} aria-hidden />
                  <div className="dp-pop" role="dialog" aria-label="קובץ המקור והתאמת עמודות">
                    <div className="dp-pop-sec">
                      <h3>קובץ המקור</h3>
                      <div className="sub">כל העיבוד נעשה על עותק — הקובץ המקורי אינו משתנה.</div>
                      <div className="dp-file">
                        <div className="ico" aria-hidden>
                          XLS
                        </div>
                        <div>
                          <div className="f-name">{DEFAULT_FILE_NAME}</div>
                          <div className="f-meta">
                            <span className="d" aria-hidden />
                            {source.rows} שורות · גיליון {source.sheet || "—"} · נטען
                          </div>
                        </div>
                      </div>
                      <div className="dp-row-actions">
                        <button className="dp-link" onClick={() => fileInput.current?.click()}>
                          החלפת קובץ
                        </button>
                        <button className="dp-link dp-link-danger" onClick={handleClear}>
                          מחיקת הקובץ
                        </button>
                      </div>
                      <details className="dp-adv">
                        <summary>הגדרות טעינה מתקדמות</summary>
                        <div className="dp-adv-grid">
                          <label>
                            שורת כותרות
                            <input className="cw-num" type="number" value={headerRow} onChange={(e) => setHeaderRow(+e.target.value)} />
                          </label>
                          <label>
                            משורה
                            <input className="cw-num" type="number" value={firstRow} onChange={(e) => setFirstRow(+e.target.value)} />
                          </label>
                          <label>
                            עד שורה
                            <input className="cw-num" type="number" value={lastRow} onChange={(e) => setLastRow(+e.target.value)} />
                          </label>
                        </div>
                        <button className="dp-link" style={{ marginTop: 10 }} onClick={() => handleLoad({})}>
                          טעינה מחדש עם הגדרות אלו
                        </button>
                      </details>
                    </div>

                    <div className="dp-pop-sec">
                      <h3>התאמת עמודות</h3>
                      <div className="sub">זוהו אוטומטית מתוך הקובץ. השדות הידניים מוזנים ברשימה.</div>
                      <div>
                        {guess &&
                          [...guess.required_fields, ...guess.optional_fields].map((f) => {
                            const col = guess.mapping[f];
                            const manual = guess.manual_fields.includes(f) || !col;
                            return (
                              <div key={f} className="dp-map-row">
                                <span className="dp-map-field">{guess.labels[f] ?? f}</span>
                                {manual ? (
                                  <span className="dp-badge-manual">מוזן ברשימה</span>
                                ) : (
                                  <span className="dp-map-col">
                                    <span className="ok" aria-hidden>
                                      ✓
                                    </span>
                                    {col}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>

            <Button variant="secondary" onClick={() => setExpanded(false)}>
              כיווץ ←
            </Button>
          </div>

          {/* the few figures that matter */}
          <div className="dp-stats">
            <div className="dp-figure">
              <span className="lab">סה״כ תלמידות</span>
              <span className="val">{students.length}</span>
            </div>
            {FILTERS.map((f) => (
              <div key={f.key} className="dp-figure">
                <span className="lab">
                  <span className="d" style={{ background: `var(--cw-${f.cls})` }} aria-hidden />
                  {f.label}
                </span>
                <span className="val">{tallies[f.key]}</span>
              </div>
            ))}
            <span className="dp-legend">הישגים: מ=מצטיינת · ב=בינונית · ח=חלשה</span>
          </div>

          {/* one table surface */}
          <section className="dp-panel">
            <div className="dp-toolbar">
              <label className="dp-search">
                <Icon name="search" size={15} style={{ color: "var(--cw-ink-3)" }} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="חיפוש לפי שם" aria-label="חיפוש לפי שם" />
              </label>
              <div className="cw-filters" role="group" aria-label="סינון לפי קטגוריה">
                <button className="cw-fchip" aria-pressed={filter === null} onClick={() => setFilter(null)}>
                  הכל
                </button>
                {FILTERS.map((f) => (
                  <button key={f.key} className="cw-fchip" aria-pressed={filter === f.key} onClick={() => setFilter((p) => (p === f.key ? null : f.key))}>
                    <span className="sw" style={{ background: `var(--cw-${f.cls})` }} aria-hidden />
                    {f.label}
                  </button>
                ))}
              </div>
              <span className="dp-save" aria-live="polite" style={saveState === "saved" ? { color: "var(--cw-good)" } : undefined}>
                {saveState === "saving" ? "שומר…" : saveState === "saved" ? "✓ נשמר" : ""}
              </span>
            </div>

            <div className="dp-table-scroll">
              <table className="dp-table">
                <thead>
                  <tr className="dp-grp">
                    <th colSpan={6}>פרטי התלמידה · מהקובץ</th>
                    <th colSpan={4} className="manual edcol edstart">
                      הזנה ידנית · מלאו כאן
                    </th>
                  </tr>
                  <tr className="dp-cols">
                    <th className="c-num">#</th>
                    <th>שם מלא</th>
                    <th>בי&quot;ס נוכחי</th>
                    <th className="center">כיתה</th>
                    <th>מוצא</th>
                    <th className="center">הישגים</th>
                    <th className="center edcol edstart">שילוב</th>
                    <th className="center edcol">ח&quot;מ</th>
                    <th className="center edcol">דיפרנציאלית</th>
                    <th className="edcol">בקשות חברות</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((s) => {
                    const level = String(s.academic_level ?? "");
                    const cls = s.current_class;
                    return (
                      <tr key={s.student_id}>
                        <td className="c-num">{s.student_id}</td>
                        <td className="c-name">{fullName(s)}</td>
                        <td>{s.current_school ?? <span className="dp-muted">—</span>}</td>
                        <td className="center cw-num">{cls == null || cls === "" ? <span className="dp-muted">—</span> : String(cls)}</td>
                        <td>{s.ethiopian_origin ? <span className="dp-origin"><span className="d" aria-hidden />אתיופי</span> : <span className="dp-muted">—</span>}</td>
                        <td className="center">
                          <span className="dp-lvl" title={level}>
                            {LEVEL_LETTER[level] ?? "·"}
                          </span>
                        </td>
                        <td className="center edcol edstart">
                          <input
                            type="checkbox"
                            aria-label={`שילוב — ${fullName(s)}`}
                            checked={!!s.inclusion}
                            onChange={(e) => patch(s.student_id, "inclusion", e.target.checked)}
                          />
                        </td>
                        <td className="center edcol">
                          <input
                            type="checkbox"
                            aria-label={`ח"מ — ${fullName(s)}`}
                            checked={!!s.hamar}
                            onChange={(e) => patch(s.student_id, "hamar", e.target.checked)}
                          />
                        </td>
                        <td className="center edcol">
                          <input
                            type="checkbox"
                            aria-label={`דיפרנציאלית — ${fullName(s)}`}
                            checked={!!s.differential}
                            onChange={(e) => patch(s.student_id, "differential", e.target.checked)}
                          />
                        </td>
                        <td className="edcol">
                          <input
                            className="dp-friends"
                            aria-label={`בקשות חברות — ${fullName(s)}`}
                            value={(s.friend_requests_raw as string) ?? ""}
                            placeholder="שמות, מופרד בפסיקים"
                            onChange={(e) => patch(s.student_id, "friend_requests_raw", e.target.value)}
                          />
                        </td>
                      </tr>
                    );
                  })}
                  {visible.length === 0 && (
                    <tr>
                      <td colSpan={10} className="center dp-muted" style={{ padding: "28px" }}>
                        לא נמצאה תלמידה תואמת
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
