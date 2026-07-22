"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button, InfoBanner, Skeleton, StatusIndicator } from "@/components/ui/primitives";
import { CheckboxField, NumberField, SliderField } from "@/components/FormField";
import { ApiError, SolverConfig, getConfig, setConfig, getLocking, setLocking } from "@/lib/api";

interface LockRow {
  student_id: number;
  locked_class: number;
}

function GroupHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="pt-5 pb-1 text-xs font-semibold tracking-wide text-slate-400">{children}</h2>;
}

// One rule = one row: name, plain-language current value, the inputs that
// change it, and a required/preferred toggle. No card, no tab.
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
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="min-w-0">
        <div className="text-sm font-medium text-slate-800">{title}</div>
        <div className="truncate text-xs text-slate-400">{explanation}</div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {children}
        {onToggleHard && (
          <button
            onClick={() => onToggleHard(!hard)}
            className="w-14 text-start"
            aria-pressed={hard}
            aria-label={hard ? "מוגדר כאילוץ חובה, לחצו להפוך למועדף" : "מוגדר כאילוץ מועדף, לחצו להפוך לחובה"}
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
          ? "min-w-[2.25rem] rounded border border-teal-600 bg-teal-50 px-2 py-0.5 text-xs font-semibold text-teal-700"
          : "min-w-[2.25rem] rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-500 hover:bg-slate-50"
      }
    >
      {label}
    </button>
  );
}

export default function ConfigureStep() {
  const [cfg, setCfg] = useState<SolverConfig | null>(null);
  const [locks, setLocks] = useState<LockRow[]>([]);
  const [lockQuery, setLockQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingLocks, setSavingLocks] = useState(false);

  useEffect(() => {
    Promise.all([getConfig(), getLocking()])
      .then(([c, l]) => {
        setCfg(c);
        setLocks(l.rows);
      })
      .finally(() => setLoading(false));
  }, []);

  function update<K extends keyof SolverConfig>(key: K, value: SolverConfig[K]) {
    setCfg((prev) => (prev ? { ...prev, [key]: value } : prev));
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

  async function handleSave() {
    if (!cfg) return;
    setSaving(true);
    try {
      const saved = await setConfig(cfg);
      setCfg(saved);
      toast.success("ההגדרות נשמרו.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בשמירת ההגדרות");
    } finally {
      setSaving(false);
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
    <div>
      <div className="grid gap-x-14 lg:grid-cols-2 xl:grid-cols-3">
        <section>
          <GroupHeading>מבנה כיתות</GroupHeading>
          <div className="divide-y divide-slate-100">
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

        <section>
          <GroupHeading>יעדים חברתיים</GroupHeading>
          <div className="divide-y divide-slate-100">
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

        <section className="lg:col-span-2 xl:col-span-1">
          <GroupHeading>תמיכה ואיזון דמוגרפי</GroupHeading>
          <div className="divide-y divide-slate-100">
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

      <div className="mt-6 flex items-center gap-3 border-t border-slate-100 pt-4">
        <Button disabled={saving} onClick={handleSave}>
          {saving ? "שומר..." : "שמור הגדרות"}
        </Button>
        <span className="text-xs text-slate-400">יש לשמור לפני הפקת שיבוץ.</span>
      </div>

      <details className="mt-4 border-t border-slate-100 pt-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-600">
          עדיפויות מתקדמות
          <span className="ms-2 font-normal text-slate-400">— כיוונון משקל היעדים ומנוע ההרצה</span>
        </summary>
        <div className="mt-4 flex flex-col gap-4">
          <InfoBanner tone="info" message="כברירת מחדל כל היעדים נשקלים באופן דומה. הגדילו ערך כדי לתת ליעד משקל רב יותר בשיבוץ." />
          <div className="grid grid-cols-1 gap-x-10 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            <SliderField label="חברות הדדית" value={cfg.weight_mutual} max={10} onChange={(v) => update("weight_mutual", v)} />
            <SliderField label="2+ חברות מבוקשות" value={cfg.weight_two_friends} max={10} onChange={(v) => update("weight_two_friends", v)} />
            <SliderField label="איזון הישגים לימודיים" value={cfg.weight_academic_balance} max={10} onChange={(v) => update("weight_academic_balance", v)} />
            <SliderField label="איזון בית ספר מקור" value={cfg.weight_school_balance} max={10} onChange={(v) => update("weight_school_balance", v)} />
            <SliderField label="שימור כיתה נוכחית" value={cfg.weight_current_class_balance} max={10} onChange={(v) => update("weight_current_class_balance", v)} />
            <SliderField label="איזון קטגוריות" value={cfg.weight_category_balance} max={10} onChange={(v) => update("weight_category_balance", v)} />
          </div>
          <div className="flex flex-wrap items-center gap-6 border-t border-slate-100 pt-3">
            <NumberField compact label="זמן הרצה מרבי (שניות)" value={cfg.time_limit_seconds} min={1} onChange={(v) => update("time_limit_seconds", v)} />
            <NumberField compact label="מספר קבוע לשחזור תוצאה זהה" value={cfg.random_seed} min={0} onChange={(v) => update("random_seed", v)} />
          </div>
        </div>
      </details>

      <details className="mt-3 border-t border-slate-100 pt-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-600">
          נעילת תלמידות מראש
          <span className="ms-2 font-normal text-slate-400">— {lockedCount} נעולות</span>
        </summary>
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-4">
            <p className="text-xs text-slate-400">תלמידה נעולה תשובץ לכיתה שנבחרה ולא תוזז על ידי מנוע השיבוץ.</p>
            <input
              value={lockQuery}
              onChange={(e) => setLockQuery(e.target.value)}
              placeholder="חיפוש לפי מזהה תלמידה"
              inputMode="numeric"
              className="w-52 border-b border-slate-300 bg-transparent px-1 py-1 text-sm focus:border-teal-600 focus:outline-none"
            />
            <Button variant="secondary" disabled={savingLocks} onClick={handleSaveLocks}>
              {savingLocks ? "שומר..." : "שמור נעילות"}
            </Button>
          </div>

          {visibleLocks.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400">
              {lockQuery ? "לא נמצאה תלמידה עם מזהה זה" : "אין תלמידות נעולות. חפשו מזהה כדי לנעול תלמידה."}
            </p>
          ) : (
            <div className="max-h-[420px] overflow-auto">
              <div className="divide-y divide-slate-100">
                {visibleLocks.map((r) => (
                  <div key={r.student_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
                    <span className="w-20 shrink-0 text-sm tabular-nums text-slate-700">{r.student_id}</span>
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
      </details>
    </div>
  );
}
