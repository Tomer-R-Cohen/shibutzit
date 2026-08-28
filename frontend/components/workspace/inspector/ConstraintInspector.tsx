"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button, Skeleton, StatusIndicator } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import { ApiError, ConstraintModel, deleteConstraint, getConstraints, patchConstraint } from "@/lib/api";
import { RANGE_TYPES, TYPE_LABELS } from "../constraintVisuals";
import { RangeBar } from "../RangeBar";

const SOURCE_LABELS: Record<string, string> = {
  builtin_default: "ברירת מחדל",
  chat: "מהשיחה",
  manual: "ידני",
};

/**
 * The rule's shape, not just its sentence -- capacity/balance constraints
 * read as a bounded range, separate/together as a relationship between two
 * students. Different semantics get different visuals instead of one
 * generic detail layout (student_a/b are raw ids on these two types, not
 * names, so the relationship itself is shown iconographically here; a
 * names-based version is natural to add once StudentInspector already has
 * student-lookup wired, in a later pass).
 */
function ConstraintShape({ constraint }: { constraint: ConstraintModel }) {
  if (RANGE_TYPES.includes(constraint.type)) {
    const min = constraint.args.min as number | null | undefined;
    const max = constraint.args.max as number | null | undefined;
    if (min == null && max == null) return null;
    return <RangeBar min={min} max={max} />;
  }
  if (constraint.type === "separate" || constraint.type === "together") {
    const isSeparate = constraint.type === "separate";
    return (
      <div className={`ws-relation-row ${isSeparate ? "separate" : "together"}`}>
        <Icon name={isSeparate ? "x" : "check"} size={13} />
        <span>{isSeparate ? "לא יהיו באותה כיתה" : "יהיו באותה כיתה"}</span>
      </div>
    );
  }
  if (constraint.type === "at_least_one_of") {
    return (
      <div className="ws-relation-row together">
        <Icon name="check" size={13} />
        <span>לפחות אחת מהקבוצה באותה כיתה</span>
      </div>
    );
  }
  return null;
}

/**
 * One rule's detail + actions, reached by selecting a row in ConstraintBrowser
 * (or a constraint_event artifact in the timeline). Same toggle/delete logic
 * as the old always-on ConstraintList, relocated into the inspector so it's
 * summoned on demand instead of parked permanently in the main column.
 */
export default function ConstraintInspector({
  id,
  onBack,
  onChanged,
  onRemoved,
}: {
  id: string;
  onBack: () => void;
  onChanged?: () => void;
  onRemoved?: () => void;
}) {
  const [constraint, setConstraint] = useState<ConstraintModel | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getConstraints()
      .then((r) => setConstraint(r.constraints.find((c) => c.id === id) ?? null))
      .catch(() => {
        toast.error("לא הצלחתי לטעון את הכלל");
        setConstraint(null);
      });
  }, [id]);

  async function handleToggleHard(hard: boolean) {
    if (!constraint) return;
    setConstraint({ ...constraint, hard });
    try {
      await patchConstraint(constraint.id, { hard });
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "לא הצלחתי לעדכן את הכלל");
      setConstraint(constraint);
    }
  }

  async function handleToggleActive(active: boolean) {
    if (!constraint) return;
    setConstraint({ ...constraint, active });
    try {
      await patchConstraint(constraint.id, { active });
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "לא הצלחתי לעדכן את הכלל");
      setConstraint(constraint);
    }
  }

  async function handleRemove() {
    if (!constraint) return;
    setBusy(true);
    try {
      await deleteConstraint(constraint.id);
      toast.success("הכלל הוסר");
      onChanged?.();
      onRemoved?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "לא הצלחתי להסיר את הכלל");
      setBusy(false);
    }
  }

  return (
    <div className="ws-insp-section">
      <button className="ws-insp-back" onClick={onBack}>
        <Icon name="chevron" size={13} style={{ transform: "rotate(90deg)" }} />
        חזרה
      </button>

      {constraint === undefined && <Skeleton className="h-40 w-full" />}

      {constraint === null && <p className="text-sm text-[var(--cw-ink-3)]">הכלל לא נמצא — כנראה הוסר.</p>}

      {constraint && (
        <>
          <span className="ws-insp-type-chip">{TYPE_LABELS[constraint.type] ?? constraint.type}</span>
          <div className="ws-insp-heading">{constraint.label_hebrew}</div>
          <div className="text-xs text-[var(--cw-ink-3)]">{SOURCE_LABELS[constraint.source] ?? constraint.source}</div>
          <ConstraintShape constraint={constraint} />

          <div className="ws-insp-kv" style={{ marginTop: 14 }}>
            <span>סטטוס</span>
            <button
              onClick={() => handleToggleActive(!constraint.active)}
              className="text-xs text-[var(--cw-ink-3)] hover:text-[var(--cw-ink-2)]"
              aria-pressed={constraint.active}
            >
              {constraint.active ? "פעיל" : "מושבת"}
            </button>
          </div>

          <div className="ws-insp-kv">
            <span>סוג הכלל</span>
            <button
              onClick={() => handleToggleHard(!constraint.hard)}
              aria-pressed={constraint.hard}
              aria-label={constraint.hard ? "מוגדר ככלל חובה, לחצו להפוך למועדף" : "מוגדר ככלל מועדף, לחצו להפוך לחובה"}
            >
              <StatusIndicator status={constraint.hard ? "blocking" : "info"} text={constraint.hard ? "חובה" : "מועדף"} />
            </button>
          </div>

          <Button variant="danger" size="sm" onClick={handleRemove} disabled={busy} className="mt-4 w-full">
            {busy ? "מסיר…" : "הסרת הכלל"}
          </Button>
        </>
      )}
    </div>
  );
}
