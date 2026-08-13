"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { NumberField } from "@/components/FormField";
import { ApiError, RunConfig, getRunConfig, setRunConfig } from "@/lib/api";

type SaveState = "idle" | "saving" | "saved";

/**
 * Run parameters only -- num_classes, the solver time budget, and the
 * reproducibility seed. Every actual rule (including the built-in
 * defaults) lives in ConstraintList now, not here. Deliberately styled as
 * a slim strip, not a card with the same visual weight as the composer or
 * the rule list -- these are administrative knobs, not part of the
 * conversation, and shouldn't compete with it for attention.
 */
export default function RunSettingsPanel({ onSaved }: { onSaved?: (cfg: RunConfig) => void }) {
  const [cfg, setCfg] = useState<RunConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");

  useEffect(() => {
    getRunConfig().then(setCfg);
  }, []);

  useEffect(() => {
    if (!cfg || !dirty) return;
    const t = setTimeout(async () => {
      setSaveState("saving");
      try {
        const saved = await setRunConfig(cfg);
        setCfg(saved);
        setDirty(false);
        setSaveState("saved");
        onSaved?.(saved);
      } catch (e) {
        setSaveState("idle");
        toast.error(e instanceof ApiError ? e.message : "שגיאה בשמירת ההגדרות");
      }
    }, 600);
    return () => clearTimeout(t);
  }, [cfg, dirty, onSaved]);

  function update<K extends keyof RunConfig>(key: K, value: RunConfig[K]) {
    setCfg((prev) => (prev ? { ...prev, [key]: value } : prev));
    setDirty(true);
  }

  if (!cfg) return null;

  return (
    <div className="run-strip">
      <span className="run-strip-label">הגדרות הרצה</span>
      <NumberField compact label="כיתות" value={cfg.num_classes} min={1} onChange={(v) => update("num_classes", v)} />
      <NumberField compact label="זמן (שנ')" value={cfg.time_limit_seconds} min={1} onChange={(v) => update("time_limit_seconds", v)} />
      <NumberField compact label="Seed" value={cfg.random_seed} min={0} onChange={(v) => update("random_seed", v)} />
      <span className="run-strip-save" aria-live="polite">
        {saveState === "saving" ? "שומר…" : saveState === "saved" ? "✓ נשמר" : ""}
      </span>
    </div>
  );
}
