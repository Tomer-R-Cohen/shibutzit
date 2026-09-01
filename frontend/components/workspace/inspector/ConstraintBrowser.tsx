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
  previewConstraints,
}: {
  onSelect: (id: string) => void;
  onBack: () => void;
  refreshKey?: number;
  highlight?: Highlight;
  onHighlight?: (h: Highlight) => void;
  /** Development-only deterministic data for rendered fixture audits. */
  previewConstraints?: ConstraintModel[];
}) {
  const [constraints, setConstraints] = useState<ConstraintModel[] | null>(previewConstraints ?? null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (previewConstraints) return;
    getConstraints()
      .then((r) => {
        setLoadError(null);
        setConstraints(r.constraints);
      })
      .catch(() => {
        setLoadError("לא הצלחנו לטעון את רשימת הכללים.");
        toast.error("לא הצלחתי לטעון את רשימת הכללים");
      });
  }, [refreshKey, previewConstraints, retryKey]);

  function retry() {
    setLoadError(null);
    setConstraints(null);
    setRetryKey((value) => value + 1);
  }

  if (loadError) {
    return (
      <div className="ws-insp-section">
        <button className="ws-insp-back" onClick={onBack}><Icon name="chevron" size={13} style={{ transform: "rotate(90deg)" }} />חזרה</button>
        <div className="ws-inline-error" role="alert">
          <Icon name="warning" size={16} />
          <div><strong>הכללים לא נטענו</strong><span>{loadError}</span></div>
          <button type="button" onClick={retry}>ניסיון נוסף</button>
        </div>
      </div>
    );
  }

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
      <div className="ws-rule-browser-head">
        <div>
          <div className="ws-insp-title">כללי השיבוץ</div>
          <p>זהו המידע שהמערכת תעביר לשיבוץ הבא.</p>
        </div>
        <span className="ws-rule-total" aria-label={`${constraints.length} כללים`}>{constraints.length}</span>
      </div>

      {hard.length > 0 && (
        <div className="ws-rule-group">
          <div className="ws-rule-group-title"><span>חובה</span><b>{hard.length}</b></div>
          {hard.map((c) => row(c, "hard"))}
        </div>
      )}

      {soft.length > 0 && (
        <div className="ws-rule-group">
          <div className="ws-rule-group-title"><span>העדפות ויעדים</span><b>{soft.length}</b></div>
          {soft.map((c) => row(c, "soft"))}
        </div>
      )}

      {inactive.length > 0 && (
        <div className="ws-rule-group">
          <div className="ws-rule-group-title"><span>לא פעילים</span><b>{inactive.length}</b></div>
          {inactive.map((c) => row(c, "soft", " inactive"))}
        </div>
      )}

      {constraints.length === 0 && <p className="text-sm text-[var(--cw-ink-3)]">אין עדיין כללים.</p>}
    </div>
  );
}
