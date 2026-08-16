"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import Dialog from "@/components/ui/Dialog";
import { Icon } from "@/components/Icon";
import { Skeleton } from "@/components/ui/primitives";
import { ApiError, StudentRecord, getStudents, updateManualEntry } from "@/lib/api";

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
 * The full roster: search, category filters, and inline editing of the
 * manual fields (inclusion / ח"מ / differential / friend requests) --
 * everything DataZone's always-expanded table used to do, now reached on
 * demand instead of parked permanently on the main screen. Ported logic,
 * same debounce-then-save behavior and endpoint.
 */
export default function RosterWorkbench({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [students, setStudents] = useState<StudentRecord[]>([]);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<CatKey | null>(null);

  const studentsRef = useRef(students);
  useEffect(() => {
    studentsRef.current = students;
  }, [students]);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    (() => {
      if (!open) return;
      setLoading(true);
      setError(null);
      getStudents()
        .then((r) => setStudents(r.rows))
        .catch((e) => setError(e instanceof ApiError ? e.message : "שגיאה בטעינת רשימת התלמידות"))
        .finally(() => setLoading(false));
    })();
    return () => clearTimeout(saveTimer.current);
  }, [open]);

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
            {saveState === "saving" ? "שומר…" : saveState === "saved" ? "✓ נשמר" : ""}
          </span>
        </div>

        {loading ? (
          <Skeleton className="h-64 w-full" />
        ) : error ? (
          <p className="py-10 text-center text-sm text-[var(--cw-crit)]">{error}</p>
        ) : (
          <>
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
          </>
        )}
      </div>
    </Dialog>
  );
}
