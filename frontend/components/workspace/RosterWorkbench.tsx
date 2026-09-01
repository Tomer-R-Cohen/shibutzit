"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import Dialog from "@/components/ui/Dialog";
import { Icon } from "@/components/Icon";
import { Skeleton } from "@/components/ui/primitives";
import { ApiError, StudentRecord, getStudents, updateManualEntry, updateStudentData } from "@/lib/api";
import type { RosterCorrectionField, RosterFocus } from "@/lib/workspace";

const ACADEMIC_LEVELS = ["מצטיינת", "בינונית", "חלשה"] as const;

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
 * The full roster: search, category filters, and inline editing of the
 * manual fields (inclusion / ח"מ / differential / friend requests) --
 * everything DataZone's always-expanded table used to do, now reached on
 * demand instead of parked permanently on the main screen. Ported logic,
 * same debounce-then-save behavior and endpoint.
 */
export default function RosterWorkbench({ open, onClose, focus, fixtureData, fixtureError, fixtureSaveError }: { open: boolean; onClose: () => void; focus?: RosterFocus; fixtureData?: StudentRecord[]; fixtureError?: string; fixtureSaveError?: string }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [students, setStudents] = useState<StudentRecord[]>([]);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">(fixtureSaveError ? "error" : "idle");
  const [saveError, setSaveError] = useState<string | null>(fixtureSaveError ?? null);
  const [loadKey, setLoadKey] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<CatKey | null>(null);

  const studentsRef = useRef(students);
  useEffect(() => {
    studentsRef.current = students;
  }, [students]);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const dataOriginals = useRef(new Map<string, unknown>());

  useEffect(() => {
    (() => {
      if (!open) return;
      setLoading(true);
      setError(null);
      if (fixtureError) {
        setError(fixtureError);
        setLoading(false);
        return;
      }
      if (fixtureData) {
        setStudents(fixtureData);
        setLoading(false);
        return;
      }
      getStudents()
        .then((r) => setStudents(r.rows))
        .catch((e) => setError(e instanceof ApiError ? e.message : "לא הצלחנו לטעון את רשימת התלמידות"))
        .finally(() => setLoading(false));
    })();
    return () => clearTimeout(saveTimer.current);
  }, [open, fixtureData, fixtureError, loadKey]);

  function scheduleSave() {
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      setSaveState("saving");
      setSaveError(null);
      if (fixtureData) {
        setSaveState("saved");
        return;
      }
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
      } catch (e) {
        const message = e instanceof ApiError ? e.message : "לא הצלחנו לשמור את השינויים.";
        setSaveState("error");
        setSaveError(message);
        toast.error(message);
      }
    }, 700);
  }

  function patch(id: number, key: "inclusion" | "hamar" | "differential" | "friend_requests_raw", value: boolean | string) {
    setStudents((prev) => prev.map((s) => (s.student_id === id ? { ...s, [key]: value } : s)));
    scheduleSave();
  }

  function dataKey(id: number, field: RosterCorrectionField) {
    return `${id}:${field}`;
  }

  function patchDataDraft(id: number, field: RosterCorrectionField, value: string) {
    const key = dataKey(id, field);
    if (!dataOriginals.current.has(key)) {
      const student = studentsRef.current.find((row) => row.student_id === id);
      dataOriginals.current.set(key, student?.[field]);
    }
    setStudents((prev) => prev.map((student) => student.student_id === id ? { ...student, [field]: value } : student));
  }

  async function commitDataPatch(id: number, field: RosterCorrectionField, nextValue?: string) {
    const key = dataKey(id, field);
    if (!dataOriginals.current.has(key)) return;
    const original = dataOriginals.current.get(key);
    const value = String(nextValue ?? studentsRef.current.find((student) => student.student_id === id)?.[field] ?? "").trim();
    setSaveState("saving");
    setSaveError(null);
    try {
      if (!fixtureData) await updateStudentData(id, field, value);
      dataOriginals.current.delete(key);
      setStudents((prev) => prev.map((student) => student.student_id === id
        ? { ...student, [field]: value, _project_edited_fields: [...new Set([...(student._project_edited_fields ?? []), field])] }
        : student));
      setSaveState("saved");
    } catch (error) {
      setStudents((prev) => prev.map((student) => student.student_id === id ? { ...student, [field]: original } : student));
      dataOriginals.current.delete(key);
      const message = error instanceof ApiError ? error.message : "לא הצלחנו לשמור את התיקון.";
      setSaveState("error");
      setSaveError(message);
      toast.error(message);
    }
  }

  function retryInitialLoad() {
    setError(null);
    setLoading(true);
    setLoadKey((value) => value + 1);
  }

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
  const editedCount = useMemo(() => students.filter((student) => (student._project_edited_fields?.length ?? 0) > 0).length, [students]);

  const visible = useMemo(() => {
    const q = query.trim();
    return students.filter((s) => {
      if (focus?.studentIds.length && !focus.studentIds.includes(s.student_id)) return false;
      if (filter && !s[filter]) return false;
      if (q && !fullName(s).includes(q)) return false;
      return true;
    });
  }, [students, query, filter, focus]);

  const focusRemaining = useMemo(() => {
    if (!focus) return 0;
    return students.filter((student) => focus.studentIds.includes(student.student_id) && focus.fields.some((field) => {
      const value = String(student[field] ?? "").trim();
      return field === "academic_level" ? !ACADEMIC_LEVELS.includes(value as typeof ACADEMIC_LEVELS[number]) : !value;
    })).length;
  }, [students, focus]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="רשימת התלמידות">
      <div className="dp">
        <div className="dp-head">
          <div className="dp-title">
            <h1>רשימת התלמידות</h1>
            <span className="dp-count cw-num">{students.length} תלמידות</span>
          </div>
          <div className="dp-spacer" />
          <span className="dp-save" aria-live="polite" style={saveState === "saved" ? { color: "var(--cw-good)" } : undefined}>
            {saveState === "saving" ? "שומרת…" : saveState === "saved" ? "✓ נשמר" : saveState === "error" ? "לא נשמר" : ""}
          </span>
        </div>

        {saveError && (
          <div className="ws-inline-error dp-save-error" role="alert">
            <Icon name="warning" size={16} />
            <div><strong>השינויים עדיין לא נשמרו</strong><span>{saveError} הערכים נשארו פתוחים במסך ואפשר לנסות שוב.</span></div>
            <button type="button" onClick={scheduleSave}>ניסיון נוסף</button>
          </div>
        )}

        {focus && !loading && !error && (
          <div className={`dp-correction-guide${focusRemaining === 0 ? " complete" : ""}`} role="status">
            <Icon name={focusRemaining === 0 ? "check" : "edit"} size={16} />
            <div>
              <strong>{focusRemaining === 0 ? "כל הפרטים הושלמו" : `נותרו ${focusRemaining} תלמידות לתיקון`}</strong>
              <span>
                {focusRemaining === 0
                  ? "התיקונים נשמרו בעותק העבודה. אפשר לסגור ולחזור לשיחה."
                  : "השורות הרלוונטיות בלבד מוצגות כאן. השלימו בית ספר חסר ובחרו אחת משלוש רמות ההישגים התקינות; כל שינוי נשמר אוטומטית."}
              </span>
            </div>
          </div>
        )}

        {loading ? (
          <Skeleton className="h-64 w-full" />
        ) : error ? (
          <div className="ws-inline-error dp-load-error" role="alert">
            <Icon name="warning" size={16} />
            <div><strong>רשימת התלמידות לא נטענה</strong><span>{error}</span></div>
            <button type="button" onClick={retryInitialLoad}>ניסיון נוסף</button>
          </div>
        ) : (
          <>
            <div className="dp-stats">
              <div className="dp-figure">
                <span className="lab">סה״כ תלמידות</span>
                <span className="val">{students.length}</span>
              </div>
              {editedCount > 0 && (
                <div className="dp-figure">
                  <span className="lab">תוקנו בפרויקט</span>
                  <span className="val">{editedCount}</span>
                </div>
              )}
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
                    <button
                      key={f.key}
                      className="cw-fchip"
                      aria-pressed={filter === f.key}
                      onClick={() => setFilter((p) => (p === f.key ? null : f.key))}
                    >
                      <span className="sw" style={{ background: `var(--cw-${f.cls})` }} aria-hidden />
                      {f.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="dp-mobile-scroll-hint">
                <Icon name="chevron" size={12} aria-hidden />
                גללו לצד השני כדי לראות ולערוך את פרטי ההשלמה הידנית
              </div>

              <div className="dp-table-scroll">
                <table className="dp-table">
                  <thead>
                    <tr className="dp-grp">
                      <th colSpan={6}>פרטי התלמידה · אפשר לתקן פרטים מסומנים</th>
                      <th colSpan={4} className="manual edcol edstart">
                        פרטים להשלמה ידנית
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
                          <td className="c-name">
                            {fullName(s)}
                            {(s._project_edited_fields?.length ?? 0) > 0 && (
                              <span
                                className="dp-edited"
                                title={`תוקן בעותק העבודה: ${s._project_edited_fields?.join(", ")}`}
                              >
                                תוקן
                              </span>
                            )}
                          </td>
                          <td className={focus?.studentIds.includes(s.student_id) && focus.fields.includes("current_school") && !String(s.current_school ?? "").trim() ? "dp-needs-correction" : undefined}>
                            <input
                              className="dp-data-input"
                              aria-label={`בית ספר נוכחי — ${fullName(s)}`}
                              aria-invalid={!String(s.current_school ?? "").trim()}
                              value={String(s.current_school ?? "")}
                              placeholder="השלימו בית ספר"
                              onChange={(event) => patchDataDraft(s.student_id, "current_school", event.target.value)}
                              onBlur={() => void commitDataPatch(s.student_id, "current_school")}
                            />
                          </td>
                          <td className="center cw-num">{cls == null || cls === "" ? <span className="dp-muted">—</span> : String(cls)}</td>
                          <td>
                            {s.ethiopian_origin ? (
                              <span className="dp-origin">
                                <span className="d" aria-hidden />
                                אתיופי
                              </span>
                            ) : (
                              <span className="dp-muted">—</span>
                            )}
                          </td>
                          <td className={`center${focus?.studentIds.includes(s.student_id) && focus.fields.includes("academic_level") && !ACADEMIC_LEVELS.includes(level as typeof ACADEMIC_LEVELS[number]) ? " dp-needs-correction" : ""}`}>
                            <select
                              className="dp-level-select"
                              aria-label={`הישגים לימודיים — ${fullName(s)}`}
                              aria-invalid={!ACADEMIC_LEVELS.includes(level as typeof ACADEMIC_LEVELS[number])}
                              value={ACADEMIC_LEVELS.includes(level as typeof ACADEMIC_LEVELS[number]) ? level : ""}
                              onChange={(event) => {
                                patchDataDraft(s.student_id, "academic_level", event.target.value);
                                void commitDataPatch(s.student_id, "academic_level", event.target.value);
                              }}
                            >
                              <option value="">בחרו</option>
                              {ACADEMIC_LEVELS.map((option) => <option key={option} value={option}>{option}</option>)}
                            </select>
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
                              placeholder="שמות, מופרדים בפסיקים"
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
          </>
        )}
      </div>
    </Dialog>
  );
}
