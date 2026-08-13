"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Skeleton, StatusIndicator } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import { ApiError, ConstraintModel, deleteConstraint, getConstraints, patchConstraint } from "@/lib/api";

const SOURCE_LABELS: Record<string, string> = {
  builtin_default: "ברירת מחדל",
  chat: "מהצ'אט",
  manual: "ידני",
};

function ConstraintRow({
  c,
  justAdded,
  onToggleHard,
  onToggleActive,
  onRemove,
}: {
  c: ConstraintModel;
  justAdded: boolean;
  onToggleHard: (v: boolean) => void;
  onToggleActive: (v: boolean) => void;
  onRemove: () => void;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-md py-2 px-2 -mx-2 ${c.active ? "" : "opacity-45"} ${justAdded ? "constraint-row-new" : ""}`}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-[var(--cw-ink)]">{c.label_hebrew}</span>
          {justAdded && <span className="constraint-new-badge">חדש</span>}
        </div>
        <div className="text-xs text-[var(--cw-ink-3)]">{SOURCE_LABELS[c.source] ?? c.source}</div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <button
          onClick={() => onToggleActive(!c.active)}
          className="text-xs text-[var(--cw-ink-3)] hover:text-[var(--cw-ink-2)]"
          aria-pressed={c.active}
        >
          {c.active ? "פעיל" : "מושבת"}
        </button>
        <button
          onClick={() => onToggleHard(!c.hard)}
          className="w-14 text-start"
          aria-pressed={c.hard}
          aria-label={c.hard ? "מוגדר ככלל חובה, לחצו להפוך למועדף" : "מוגדר ככלל מועדף, לחצו להפוך לחובה"}
        >
          <StatusIndicator status={c.hard ? "blocking" : "info"} text={c.hard ? "חובה" : "מועדף"} />
        </button>
        <button onClick={onRemove} className="text-[var(--cw-ink-3)] hover:text-[var(--cw-crit)]" aria-label="הסר כלל">
          <Icon name="x" size={14} />
        </button>
      </div>
    </div>
  );
}

/**
 * The structured, directly-editable view of every active rule -- built-in
 * defaults and chat/manual exceptions alike, all in one list (see
 * src/constraints.py). Chat writes to the same list this reads/edits, so
 * `refreshKey` should bump whenever a chat proposal is confirmed elsewhere
 * on the page.
 *
 * Rows that are new since the last load get a brief entrance + highlight
 * (see `justAddedIds`) -- this is what makes confirming something in chat
 * visibly land here, instead of the list just silently refreshing.
 */
export default function ConstraintList({ refreshKey }: { refreshKey?: number }) {
  const [constraints, setConstraints] = useState<ConstraintModel[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [justAddedIds, setJustAddedIds] = useState<Set<string>>(new Set());
  const prevIdsRef = useRef<Set<string> | null>(null);
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  function load() {
    getConstraints()
      .then((r) => {
        const nextIds = new Set(r.constraints.map((c) => c.id));
        if (prevIdsRef.current) {
          const added = [...nextIds].filter((id) => !prevIdsRef.current!.has(id));
          if (added.length > 0) {
            setJustAddedIds(new Set(added));
            clearTimeout(highlightTimer.current);
            highlightTimer.current = setTimeout(() => setJustAddedIds(new Set()), 2200);
          }
        }
        prevIdsRef.current = nextIds;
        setConstraints(r.constraints);
      })
      .catch(() => toast.error("שגיאה בטעינת רשימת הכללים"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    return () => clearTimeout(highlightTimer.current);
  }, [refreshKey]);

  async function handleToggleHard(c: ConstraintModel, hard: boolean) {
    setConstraints((prev) => prev?.map((x) => (x.id === c.id ? { ...x, hard } : x)) ?? prev);
    try {
      await patchConstraint(c.id, { hard });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בעדכון הכלל");
      load();
    }
  }

  async function handleToggleActive(c: ConstraintModel, active: boolean) {
    setConstraints((prev) => prev?.map((x) => (x.id === c.id ? { ...x, active } : x)) ?? prev);
    try {
      await patchConstraint(c.id, { active });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בעדכון הכלל");
      load();
    }
  }

  async function handleRemove(c: ConstraintModel) {
    const prev = constraints;
    setConstraints((p) => p?.filter((x) => x.id !== c.id) ?? p);
    try {
      await deleteConstraint(c.id);
      toast.success("הכלל הוסר");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "שגיאה בהסרת הכלל");
      setConstraints(prev ?? null);
    }
  }

  if (loading || !constraints) return <Skeleton className="h-64 w-full" />;

  const activeCount = constraints.filter((c) => c.active).length;

  return (
    <section className="cfg-card wide">
      <div className="cfg-card-head">
        <span className="t">כללי שיבוץ</span>
        <span className="d">
          {activeCount} פעילים מתוך {constraints.length}
        </span>
      </div>
      {constraints.length === 0 ? (
        <p className="py-6 text-center text-sm text-[var(--cw-ink-3)]">אין עדיין כללים. אפשר להוסיף דרך הצ&apos;אט.</p>
      ) : (
        <div className="divide-y divide-[var(--cw-line-2)]">
          {constraints.map((c) => (
            <ConstraintRow
              key={c.id}
              c={c}
              justAdded={justAddedIds.has(c.id)}
              onToggleHard={(v) => handleToggleHard(c, v)}
              onToggleActive={(v) => handleToggleActive(c, v)}
              onRemove={() => handleRemove(c)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
