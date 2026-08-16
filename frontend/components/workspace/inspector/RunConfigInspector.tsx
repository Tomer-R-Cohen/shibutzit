"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Icon } from "@/components/Icon";
import { NumberField } from "@/components/FormField";
import { ApiError, RunConfig, getRunConfig, setRunConfig } from "@/lib/api";

/**
 * The three run parameters that live outside the constraint list (class
 * count, solver time budget, reproducibility seed) -- everything else
 * about how a solve behaves is a Constraint, edited via ConstraintInspector.
 * Auto-saves on change (debounced), matching RosterWorkbench's pattern --
 * no separate save button for three number fields.
 */
export default function RunConfigInspector({ onBack, onChanged }: { onBack: () => void; onChanged?: () => void }) {
  const [cfg, setCfg] = useState<RunConfig | null | undefined>(undefined);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    getRunConfig()
      .then(setCfg)
      .catch(() => {
        toast.error("שגיאה בטעינת הגדרות השיבוץ");
        setCfg(null);
      });
    return () => clearTimeout(saveTimer.current);
  }, []);

  function patch(next: RunConfig) {
    setCfg(next);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      setSaveState("saving");
      try {
        await setRunConfig(next);
        setSaveState("saved");
        onChanged?.();
      } catch (e) {
        setSaveState("idle");
        toast.error(e instanceof ApiError ? e.message : "שגיאה בשמירת ההגדרות");
      }
    }, 500);
  }

  return (
    <div className="ws-insp-section">
      <button className="ws-insp-back" onClick={onBack}>
        <Icon name="chevron" size={13} style={{ transform: "rotate(90deg)" }} />
        חזרה
      </button>

      {cfg === undefined && <p className="text-sm text-[var(--cw-ink-3)]">טוען…</p>}
      {cfg === null && <p className="text-sm text-[var(--cw-ink-3)]">שגיאה בטעינת ההגדרות.</p>}

      {cfg && (
        <>
          <div className="ws-insp-heading">הגדרות שיבוץ</div>

          <div className="flex flex-col gap-3" style={{ marginTop: 10 }}>
            <NumberField label="מספר כיתות" value={cfg.num_classes} min={2} onChange={(v) => patch({ ...cfg, num_classes: v })} />
            <NumberField
              label="זמן מקסימלי לחיפוש (שניות)"
              value={cfg.time_limit_seconds}
              min={5}
              step={5}
              onChange={(v) => patch({ ...cfg, time_limit_seconds: v })}
            />
            <NumberField label="זרע רנדומלי (לשחזור תוצאה)" value={cfg.random_seed} min={0} onChange={(v) => patch({ ...cfg, random_seed: v })} />
          </div>

          <p className="text-xs text-[var(--cw-ink-3)]" style={{ marginTop: 10 }} aria-live="polite">
            {saveState === "saving" ? "שומר…" : saveState === "saved" ? "✓ נשמר" : " "}
          </p>
        </>
      )}
    </div>
  );
}
