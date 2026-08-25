"use client";

import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import { toast } from "sonner";
import { Icon } from "@/components/Icon";
import { DataRequirement, deleteDataRequirement, getDataRequirements } from "@/lib/api";

/**
 * The Excel checklist: what the planning conversation decided the file has
 * to contain.
 *
 * This is the visible output of talking to the agent before any data exists.
 * Every time the counselor mentions a consideration with no column behind it
 * -- twins, siblings, behaviour -- a row lands here, live. Once a workbook is
 * loaded the rows tick themselves off by matching the header she typed, so
 * the same list doubles as "did I remember everything".
 */
export default function RequirementsCard({ refreshKey }: { refreshKey?: number }) {
  const [reqs, setReqs] = useState<DataRequirement[] | null>(null);
  const [hasDataset, setHasDataset] = useState(false);

  const load = useCallback(() => {
    getDataRequirements()
      .then((r) => {
        setReqs(r.requirements);
        setHasDataset(r.has_dataset);
      })
      .catch(() => setReqs([]));
  }, []);

  useEffect(load, [load, refreshKey]);

  async function drop(id: string) {
    try {
      await deleteDataRequirement(id);
      load();
    } catch {
      toast.error("שגיאה בהסרת העמודה");
    }
  }

  // An empty checklist before planning has happened isn't worth a card --
  // it would just be a box saying nothing, on the one screen that most needs
  // to feel uncluttered.
  if (!reqs || reqs.length === 0) return null;

  const missing = reqs.filter((r) => !r.satisfied).length;

  return (
    <div className="ws-insp-card">
      <div className="ws-insp-card-head as-heading">
        <span className="ws-insp-icon-lg">
          <Icon name="file" size={16} />
        </span>
        <span className="ws-insp-card-title">עמודות להכנה באקסל</span>
      </div>

      <div className="ws-req-list">
        {reqs.map((r) => (
          <div key={r.id} className={clsx("ws-req", r.satisfied && "done")}>
            <span className="mark" aria-hidden>
              <Icon name="check" size={11} />
            </span>
            <span className="txt">
              <span className="t">{r.label}</span>
              <span className="m">
                {r.kind_label}
                {r.values.length > 0 ? ` · ${r.values.join(", ")}` : ""}
                {r.reason ? ` · ${r.reason}` : ""}
              </span>
            </span>
            <button
              type="button"
              className="ws-req-drop"
              onClick={() => drop(r.id)}
              aria-label={`הסרת ${r.label} מהרשימה`}
            >
              <Icon name="x" size={12} />
            </button>
          </div>
        ))}
      </div>

      <p className="ws-insp-strip" style={{ margin: 0 }}>
        {hasDataset
          ? missing === 0
            ? "כל העמודות נמצאו בקובץ."
            : `חסרות ${missing} עמודות בקובץ שנטען.`
          : "הוסיפו את העמודות האלה לאקסל לפני הטעינה."}
      </p>
    </div>
  );
}
