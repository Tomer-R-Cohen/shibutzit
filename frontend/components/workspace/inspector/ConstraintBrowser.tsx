"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import { ConstraintModel, getConstraints } from "@/lib/api";
import { Highlight } from "@/lib/workspace";

/**
 * All rules, grouped hard/soft/inactive -- the full-list replacement for
 * the old permanent ConstraintList table. Lives in the inspector, reached
 * by selection, not parked in the main column at all times. Rows respond
 * to the shared `highlight` so pointing at a rule anywhere else in the
 * workspace lights up the matching row here.
 */
export default function ConstraintBrowser({
  onSelect,
  onBack,
  refreshKey,
  highlight,
  onHighlight,
}: {
  onSelect: (id: string) => void;
  onBack: () => void;
  refreshKey?: number;
  highlight?: Highlight;
  onHighlight?: (h: Highlight) => void;
}) {
  const [constraints, setConstraints] = useState<ConstraintModel[] | null>(null);

  useEffect(() => {
    getConstraints()
      .then((r) => setConstraints(r.constraints))
      .catch(() => toast.error("לא הצלחתי לטעון את רשימת הכללים"));
  }, [refreshKey]);

  if (!constraints) return <Skeleton className="h-64 w-full" />;

  const highlightedId = highlight?.kind === "constraint" ? highlight.id : null;
  const hard = constraints.filter((c) => c.active && c.hard);
  const soft = constraints.filter((c) => c.active && !c.hard);
  const inactive = constraints.filter((c) => !c.active);

  const row = (c: ConstraintModel, dot: "hard" | "soft", extraClass = "") => (
    <button
      key={c.id}
      className={`ws-rule-row${extraClass}${highlightedId === c.id ? " is-highlighted" : ""}`}
      onClick={() => onSelect(c.id)}
      onMouseEnter={() => onHighlight?.({ kind: "constraint", id: c.id })}
      onMouseLeave={() => onHighlight?.(null)}
      onFocus={() => onHighlight?.({ kind: "constraint", id: c.id })}
      onBlur={() => onHighlight?.(null)}
    >
      <span className={`d ${dot}`} aria-hidden />
      <span className="ws-rule-row-label">{c.label_hebrew}</span>
      <Icon name="chevron" size={12} className="ws-chev" style={{ transform: "rotate(-90deg)" }} />
    </button>
  );

  return (
    <div className="ws-insp-section">
      <button className="ws-insp-back" onClick={onBack}>
        <Icon name="chevron" size={13} style={{ transform: "rotate(90deg)" }} />
        חזרה
      </button>
      <div className="ws-insp-title">כל הכללים</div>

      {hard.length > 0 && (
        <div className="ws-rule-group">
          <div className="ws-rule-group-title">כללי חובה</div>
          {hard.map((c) => row(c, "hard"))}
        </div>
      )}

      {soft.length > 0 && (
        <div className="ws-rule-group">
          <div className="ws-rule-group-title">כללים מועדפים</div>
          {soft.map((c) => row(c, "soft"))}
        </div>
      )}

      {inactive.length > 0 && (
        <div className="ws-rule-group">
          <div className="ws-rule-group-title">לא פעילים</div>
          {inactive.map((c) => row(c, "soft", " inactive"))}
        </div>
      )}

      {constraints.length === 0 && <p className="text-sm text-[var(--cw-ink-3)]">אין עדיין כללים.</p>}
    </div>
  );
}
