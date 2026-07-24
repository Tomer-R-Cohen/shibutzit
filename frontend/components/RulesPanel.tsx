"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button, Skeleton, StatusIndicator } from "@/components/ui/primitives";
import { CheckboxField, NumberField, SliderField } from "@/components/FormField";
import { ApiError, SolverConfig, getConfig, setConfig, getLocking, setLocking } from "@/lib/api";

interface LockRow {
  student_id: number;
  locked_class: number;
}

// One rule = one row: name, plain-language current value, the inputs that
// change it, and a required/preferred toggle. Grouped inside section cards.
function RuleRow({
  title,
  explanation,
  hard,
  onToggleHard,
  children,
}: {
  title: string;
  explanation: string;
  hard?: boolean;
  onToggleHard?: (v: boolean) => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5">
      <div className="min-w-0">
        <div className="text-sm font-medium text-[var(--cw-ink)]">{title}</div>
        <div className="truncate text-xs text-[var(--cw-ink-3)]">{explanation}</div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {children}
        {onToggleHard && (
          <button
            onClick={() => onToggleHard(!hard)}
            className="w-14 text-start"
            aria-pressed={hard}
            aria-label={hard ? "מוגדר ככלל חובה, לחצו להפוך למועדף" : "מוגדר ככלל מועדף, לחצו להפוך לחובה"}
          >
            <StatusIndicator status={hard ? "blocking" : "info"} text={hard ? "חובה" : "מועדף"} />
          </button>
        )}
      </div>
    </div>
  );
}

function LockChoice({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={
        active
          ? "min-w-[2.25rem] rounded border border-[var(--cw-accent)] bg-[var(--cw-accent-tint)] px-2 py-0.5 text-xs font-semibold text-[var(--cw-accent-strong)]"
          : "min-w-[2.25rem] rounded border border-[var(--cw-line)] px-2 py-0.5 text-xs text-[var(--cw-ink-2)] hover:bg-[var(--cw-panel)]"
      }
    >
      {label}
    </button>
  );
}

type SaveState = "idle" | "saving" | "saved";

/**
 * The full "class rules" editor. Config changes auto-save (debounced) — there
 * is no explicit save gate anymore, so a user can never run the solver against
 * settings they forgot to save. `onConfigSaved` lets a host (e.g. the drawer on
 * the assignment screen) react to a saved config, such as re-reading
 * num_classes.
 */
export default function RulesPanel({ onConfigSaved }: { onConfigSaved?: (cfg: SolverConfig) => void }) {
  const [cfg, setCfg] = useState<SolverConfig | null>(null);
  const [locks, setLocks] = useState<LockRow[]>([]);
  const [lockQuery, setLockQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [dirty, setDirty] = useState(false);
  const [savingLocks, setSavingLocks] = useState(false);

  useEffect(() => {
    Promise.all([getConfig(), getLocking()])
      .then(([c, l]) => {
        setCfg(c);
        setLocks(l.rows);
      })
      .finally(() => setLoading(false));
  }, []);

  // Debounced auto-save. Only fires when the user has actually changed
  // something (dirty), never on the initial load.
  useEffect(() => {
    if (!cfg || !dirty) return;
    const t = setTimeout(async () => {
      setSaveState("saving");
      try {
        const saved = await setConfig(cfg);
        setCfg(saved);
        setDirty(false);
        setSaveState("saved");
        onConfigSaved?.(saved);
      } catch (e) {
        setSaveState("idle");
        toast.error(e instanceof ApiError ? e.message : "שגיאה בשמירת ההגדרות");
      }
    }, 600);
    return () => clearTimeout(t);
  }, [cfg, dirty, onConfigSaved]);

  function update<K extends keyof SolverConfig>(key: K, value: SolverConfig[K]) {
    setCfg((prev) => (prev ? { ...prev, [key]: value } : prev));
    setDirty(true);
  }

  function updateLock(studentId: number, cls: number) {
    setLocks((prev) => prev.map((r) => (r.student_id === studentId ? { ...r, locked_class: cls } : r)));
  }

  async function handleSaveLocks() {
    setSavingLocks(true);
    try {
      const payload: Record<string, number> = {};
      for (const r of locks) payload[String(r.student_id)] = r.locked_class;
      const res = await setLocking(payload);
      toast.success(`תלמידות נעולות: ${res.locked_count}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה");
    } finally {
      setSavingLocks(false);
    }
  }

  if (loading || !cfg) return <Skeleton className="h-96 w-full" />;

  const lockedCount = locks.filter((r) => r.locked_class >= 1).length;
  // Default to showing only students that are actually locked; searching by id
  // brings any other student into view so a lock can be added. Rendering all
  // ~200 rows up front was what forced a control-per-row in the first place.
  const visibleLocks = locks.filter(
    (r) => r.locked_class >= 1 || (lockQuery.trim() !== "" && String(r.student_id).includes(lockQuery.trim()))
  );

  return (
    <div className="@container">
      <div className="flex items-center justify-between gap-4 pb-2">
        <span className="text-xs text-[var(--cw-ink-3)]">
          סמנו כלל כ<b className="font-semibold text-[var(--cw-ink-2)]">חובה</b> כדי לאכוף אותו במלואו, או השאירו כ<b className="font-semibold text-[var(--cw-ink-2)]">מועדף</b> כיעד רך.
        </span>
        <span className="shrink-0 text-xs text-[var(--cw-ink-3)]" aria-live="polite">
          {saveState === "saving" ? "שומר…" : saveState === "saved" ? "✓ נשמר אוטומטית" : "השינויים נשמרים אוטומטית"}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3.5 @2xl:grid-cols-2 @5xl:grid-cols-3">
        <section className="cfg-card">
          <div className="cfg-card-head"><span className="t">מבנה כיתות</span></div>
          <div className="divide-y divide-[var(--cw-line-2)]">
            <RuleRow title="מספר כיתות" explanation="לכמה כיתות יחולקו התלמידות">
              <NumberField compact label="" value={cfg.num_classes} min={1} onChange={(v) => update("num_classes", v)} />
            </RuleRow>
            <RuleRow
              title="איזון גודל כיתות"
              explanation={`פער מרבי של ${cfg.max_class_size_diff} תלמידות בין הגדולה לקטנה`}
              hard={cfg.class_size_hard}
              onToggleHard={(v) => update("class_size_hard", v)}
            >
              <NumberField compact label="פער" value={cfg.max_class_size_diff} onChange={(v) => update("max_class_size_diff", v)} />
            </RuleRow>
          </div>
        </section>

        <section className="cfg-card">
          <div className="cfg-card-head"><span className="t">יעדים חברתיים</span></div>
          <div className="divide-y divide-[var(--cw-line-2)]">
            <RuleRow title="חברות הדדית" explanation="יעד באחוזים: חברה הדדית אחת לפחות">
              <NumberField compact label="%" value={cfg.mutual_target_pct} min={0} onChange={(v) => update("mutual_target_pct", v)} />
            </RuleRow>
            <RuleRow title="שתי חברות ומעלה" explanation="יעד באחוזים: 2+ בקשות שמומשו">
              <NumberField compact label="%" value={cfg.two_friends_target_pct} min={0} onChange={(v) => update("two_friends_target_pct", v)} />
            </RuleRow>
            <RuleRow
              title="בסיס חישוב האחוזים"
              explanation={cfg.denominator_all_students ? "מתוך כלל התלמידות" : "מתוך מי שהגישו בקשות בלבד"}
            >
              <CheckboxField label="כלל התלמידות" checked={cfg.denominator_all_students} onChange={(v) => update("denominator_all_students", v)} />
            </RuleRow>
          </div>
        </section>

        <section className="cfg-card">
          <div className="cfg-card-head"><span className="t">איזון דמוגרפי</span></div>
          <div className="divide-y divide-[var(--cw-line-2)]">
            <RuleRow
              title="דיפרנציאליות"
              explanation={`עד ${cfg.max_differential_per_class} בכל כיתה`}
              hard={cfg.differential_hard}
              onToggleHard={(v) => update("differential_hard", v)}
            >
              <NumberField compact label="עד" value={cfg.max_differential_per_class} onChange={(v) => update("max_differential_per_class", v)} />
            </RuleRow>
            <RuleRow
              title="מוצא אתיופי"
              explanation={`${cfg.min_ethiopian_per_class}–${cfg.max_ethiopian_per_class} בכל כיתה`}
              hard={cfg.ethiopian_hard}
              onToggleHard={(v) => update("ethiopian_hard", v)}
            >
              <NumberField compact label="" value={cfg.min_ethiopian_per_class} onChange={(v) => update("min_ethiopian_per_class", v)} />
              <NumberField compact label="–" value={cfg.max_ethiopian_per_class} onChange={(v) => update("max_ethiopian_per_class", v)} />
            </RuleRow>
            <RuleRow
              title="שילוב"
              explanation={`${cfg.min_inclusion_per_class}–${cfg.max_inclusion_per_class} בכל כיתה`}
              hard={cfg.inclusion_hard}
              onToggleHard={(v) => update("inclusion_hard", v)}
            >
              <NumberField compact label="" value={cfg.min_inclusion_per_class} onChange={(v) => update("min_inclusion_per_class", v)} />
              <NumberField compact label="–" value={cfg.max_inclusion_per_class} onChange={(v) => update("max_inclusion_per_class", v)} />
            </RuleRow>
            <RuleRow
              title='ח"מ'
              explanation={`${cfg.min_hamar_per_class}–${cfg.max_hamar_per_class} בכל כיתה`}
              hard={cfg.hamar_hard}
              onToggleHard={(v) => update("hamar_hard", v)}
            >
              <NumberField compact label="" value={cfg.min_hamar_per_class} onChange={(v) => update("min_hamar_per_class", v)} />
              <NumberField compact label="–" value={cfg.max_hamar_per_class} onChange={(v) => update("max_hamar_per_class", v)} />
            </RuleRow>
          </div>
        </section>
      </div>

      <section className="cfg-card wide mt-3.5">
        <div className="cfg-card-head">
          <span className="t">עדיפויות מתקדמות</span>
          <span className="d">משקל היעדים ומנוע ההרצה — כברירת מחדל כולם שקולים</span>
        </div>
        <div className="grid grid-cols-1 gap-x-8 gap-y-2.5 pt-1 @xl:grid-cols-2 @4xl:grid-cols-3">
          <SliderField label="חברות הדדית" value={cfg.weight_mutual} max={10} onChange={(v) => update("weight_mutual", v)} />
          <SliderField label="2+ חברות מבוקשות" value={cfg.weight_two_friends} max={10} onChange={(v) => update("weight_two_friends", v)} />
          <SliderField label="איזון הישגים לימודיים" value={cfg.weight_academic_balance} max={10} onChange={(v) => update("weight_academic_balance", v)} />
          <SliderField label="איזון בית ספר מקור" value={cfg.weight_school_balance} max={10} onChange={(v) => update("weight_school_balance", v)} />
          <SliderField label="שימור כיתה נוכחית" value={cfg.weight_current_class_balance} max={10} onChange={(v) => update("weight_current_class_balance", v)} />
          <SliderField label="איזון קטגוריות" value={cfg.weight_category_balance} max={10} onChange={(v) => update("weight_category_balance", v)} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-6 border-t border-[var(--cw-line-2)] pt-3">
          <NumberField compact label="זמן הרצה מרבי (שניות)" value={cfg.time_limit_seconds} min={1} onChange={(v) => update("time_limit_seconds", v)} />
          <NumberField compact label="מספר קבוע לשחזור תוצאה זהה" value={cfg.random_seed} min={0} onChange={(v) => update("random_seed", v)} />
        </div>
      </section>

      <section className="cfg-card wide mt-3.5">
        <div className="cfg-card-head">
          <span className="t">נעילת תלמידות מראש</span>
          <span className="d">{lockedCount} נעולות</span>
        </div>
        <div className="mt-1 flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <p className="text-xs text-[var(--cw-ink-3)]">תלמידה נעולה תשובץ לכיתה שנבחרה ולא תוזז על ידי מנוע השיבוץ.</p>
            <input
              value={lockQuery}
              onChange={(e) => setLockQuery(e.target.value)}
              placeholder="חיפוש לפי מזהה תלמידה"
              inputMode="numeric"
              className="w-52 border-b border-[var(--cw-line)] bg-transparent px-1 py-1 text-sm focus:border-[var(--cw-accent)] focus:outline-none"
            />
            <Button variant="secondary" disabled={savingLocks} onClick={handleSaveLocks}>
              {savingLocks ? "שומר..." : "שמור נעילות"}
            </Button>
          </div>

          {visibleLocks.length === 0 ? (
            <p className="py-4 text-center text-sm text-[var(--cw-ink-3)]">
              {lockQuery ? "לא נמצאה תלמידה עם מזהה זה" : "אין תלמידות נעולות. חפשו מזהה כדי לנעול תלמידה."}
            </p>
          ) : (
            <div className="max-h-[320px] overflow-auto">
              <div className="grid grid-cols-1 gap-x-8 @2xl:grid-cols-2">
                {visibleLocks.map((r) => (
                  <div key={r.student_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[var(--cw-line-2)] py-1.5">
                    <span className="w-16 shrink-0 text-sm tabular-nums text-[var(--cw-ink)]">{r.student_id}</span>
                    <div className="flex flex-wrap gap-1" role="group" aria-label={`כיתה נעולה לתלמידה ${r.student_id}`}>
                      <LockChoice label="ללא" active={r.locked_class === 0} onClick={() => updateLock(r.student_id, 0)} />
                      {Array.from({ length: cfg.num_classes }, (_, c) => c + 1).map((c) => (
                        <LockChoice key={c} label={String(c)} active={r.locked_class === c} onClick={() => updateLock(r.student_id, c)} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
