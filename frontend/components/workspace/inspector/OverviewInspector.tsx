"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ConstraintsSummary } from "@/lib/workspace";
import { ApiError, AssignmentVersionSummary, ProjectDecision, RunConfig, StudentRecord, getProjectMemory, getRunConfig, getStudents, getVersions, restoreVersion, setRunConfig } from "@/lib/api";
import { Icon, IconName } from "@/components/Icon";
import { Button } from "@/components/ui/primitives";
import RequirementsCard from "./RequirementsCard";

const CATEGORY_TALLY: { key: keyof StudentRecord; cls: string; label: string }[] = [
  { key: "differential", cls: "diff", label: "דיפרנציאלית" },
  { key: "ethiopian_origin", cls: "eth", label: "מוצא אתיופי" },
  { key: "inclusion", cls: "incl", label: "שילוב" },
  { key: "hamar", cls: "hamar", label: 'ח"מ' },
];

const MIN_CLASSES = 2;
const MAX_CLASSES = 20;

export interface OverviewInspectorPreview {
  runConfig: RunConfig;
  tallies: Record<string, number>;
  memory: { notes: string[]; decisions: ProjectDecision[] };
  versions: { current: string | null; items: AssignmentVersionSummary[] };
  restoreCandidate?: string | null;
}

/**
 * The default inspector pane: roster / rules / how the run is set up.
 *
 * The third section used to be a flat strip of three figures behind a
 * sub-view -- class count, search budget, and a random seed that had no
 * business being on screen at all (it exists so identical inputs give
 * identical output; turning it just reshuffles which of several equally
 * good assignments you get, which reads as the app being unreliable). The
 * seed is gone from the UI entirely and the sub-view with it, because the
 * class count -- the one run parameter anyone actually reasons about -- is
 * now edited right here.
 *
 * The two display figures in the pane are deliberately different in kind:
 * the roster count is a static readout annotated with category dots, the
 * class count is a control with a stepper beside it. Nothing else in the
 * pane competes with them.
 */
export default function OverviewInspector({
  studentCount,
  constraintsSummary,
  onOpenConstraints,
  onOpenRoster,
  onOpenResults,
  onConstraintsChanged,
  onRunConfigChange,
  onVersionRestored,
  refreshKey,
  hasDataset = true,
  preview,
}: {
  studentCount: number | null;
  constraintsSummary: ConstraintsSummary | null;
  onOpenConstraints: () => void;
  onOpenRoster?: () => void;
  onOpenResults?: () => void;
  /** Class count drives the capacity rule's bounds server-side. */
  onConstraintsChanged?: () => void;
  /** Logs the change to the timeline so the result is marked stale. */
  onRunConfigChange?: (label: string) => void;
  /** Keeps a restore made in the structured UI visible in conversation. */
  onVersionRestored?: (version: number, reason: string) => void;
  /** Bumped when the agent changes state, so panels re-read. */
  refreshKey?: number;
  hasDataset?: boolean;
  /** Development-only deterministic state for rendered audits. */
  preview?: OverviewInspectorPreview;
}) {
  const [runConfig, setCfg] = useState<RunConfig | null>(preview?.runConfig ?? null);
  const [tallies, setTallies] = useState<Record<string, number> | null>(preview?.tallies ?? null);
  const [memory, setMemory] = useState<{ notes: string[]; decisions: ProjectDecision[] }>(preview?.memory ?? { notes: [], decisions: [] });
  const [versions, setVersions] = useState<{ current: string | null; items: AssignmentVersionSummary[] }>(preview?.versions ?? { current: null, items: [] });
  const [restoringVersion, setRestoringVersion] = useState<string | null>(null);
  const [restoreCandidate, setRestoreCandidate] = useState<string | null>(preview?.restoreCandidate ?? null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (preview) return () => clearTimeout(saveTimer.current);
    getRunConfig()
      .then(setCfg)
      .catch(() => {});
    getProjectMemory().then(setMemory).catch(() => {});
    getVersions().then((r) => setVersions({ current: r.current_version_id, items: r.versions })).catch(() => {});
    return () => clearTimeout(saveTimer.current);
  }, [refreshKey, preview]);

  useEffect(() => {
    if (preview) return;
    if (studentCount == null) return;
    getStudents()
      .then((r) => {
        const c: Record<string, number> = {};
        for (const f of CATEGORY_TALLY) c[f.cls] = 0;
        for (const s of r.rows) {
          for (const f of CATEGORY_TALLY) {
            if (s[f.key]) c[f.cls] += 1;
          }
        }
        setTallies(c);
      })
      .catch(() => {});
  }, [studentCount, preview]);

  // Optimistic + debounced, matching RosterWorkbench: the stepper has to
  // feel like a stepper, so the number moves immediately and the PUT
  // catches up. The timeline note is only written once the save lands --
  // narrating a change that failed would be worse than saying nothing.
  function patch(next: RunConfig, note?: string) {
    setCfg(next);
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        await setRunConfig(next);
        onConstraintsChanged?.();
        if (note) onRunConfigChange?.(note);
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "לא הצלחתי לשמור את ההגדרות");
      }
    }, 500);
  }

  function setClasses(n: number) {
    if (!runConfig) return;
    const clamped = Math.min(MAX_CLASSES, Math.max(MIN_CLASSES, n));
    if (clamped === runConfig.num_classes) return;
    patch({ ...runConfig, num_classes: clamped }, `מספר הכיתות עודכן ל-${clamped}`);
  }

  async function restore(id: string) {
    const selected = versions.items.find((version) => version.id === id);
    setRestoringVersion(id);
    try {
      const restored = await restoreVersion(id);
      setVersions((current) => ({ ...current, current: restored.version_id }));
      if (selected) onVersionRestored?.(restored.number, selected.reason);
      toast.success(`גרסה ${restored.number} שוחזרה`);
      onConstraintsChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "לא הצלחנו לשחזר את הגרסה");
    } finally {
      setRestoringVersion(null);
      setRestoreCandidate(null);
    }
  }

  const dash = "—";

  return (
    <>
      <div className="ws-insp-title" style={{ padding: "0 2px" }}>
        תמונת מצב
      </div>

      {hasDataset && (
      <InspectorCard icon="file" title="נתונים" onOpen={onOpenRoster}>
        <div className="ws-insp-figure">
          <span className="n">{studentCount ?? dash}</span>
          <span className="u">תלמידות</span>
        </div>
        {tallies && (
          <div className="ws-insp-tally-row">
            {CATEGORY_TALLY.map((f) => (
              <span key={f.cls} className="ws-insp-tally">
                <span className="d" style={{ background: `var(--cw-${f.cls})` }} aria-hidden />
                {f.label} {tallies[f.cls]}
              </span>
            ))}
          </div>
        )}
      </InspectorCard>
      )}

      <RequirementsCard refreshKey={refreshKey} />

      {(memory.notes.length > 0 || memory.decisions.length > 0) && (
        <InspectorCard icon="sparkle" title="מה סיכמנו">
          {memory.notes.length > 0 && (
            <ul className="ws-memory-list">
              {memory.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          )}
          {memory.decisions.length > 0 && (
            <div className="ws-memory-decisions">
              {memory.decisions.slice(-3).reverse().map((decision, index) => (
                <span key={`${decision.at}-${index}`}>
                  <span className={`d ${decision.decision}`} aria-hidden />
                  {decision.decision === "approved" ? "אושר" : decision.decision === "rejected" ? "נדחה" : "בוצע"}: {decision.summary}
                </span>
              ))}
            </div>
          )}
        </InspectorCard>
      )}

      <InspectorCard icon="list" title="כללים" onOpen={onOpenConstraints}>
        <dl className="ws-insp-kvs">
          <div className="ws-insp-kv">
            <dt>
              <span className="d hard" aria-hidden />
              חובה
            </dt>
            <dd>{constraintsSummary ? constraintsSummary.hard : dash}</dd>
          </div>
          <div className="ws-insp-kv">
            <dt>
              <span className="d soft" aria-hidden />
              מועדף
            </dt>
            <dd>{constraintsSummary ? constraintsSummary.soft : dash}</dd>
          </div>
        </dl>
      </InspectorCard>

      {versions.items.length > 0 && (
        <InspectorCard icon="grid" title="גרסאות שיבוץ">
          <div className="ws-version-list">
            {versions.items.slice(0, 6).map((version) => {
              const current = version.id === versions.current;
              return (
                <div key={version.id} className={`ws-version-row${current ? " current" : ""}${restoreCandidate === version.id ? " confirming" : ""}`}>
                  <div className="ws-version-main">
                    <span className="ws-version-title">
                      גרסה {version.number}
                      {current && <small>נוכחית</small>}
                      {version.approved && <small className="approved">מאושרת</small>}
                    </span>
                    <span className="ws-version-reason">{version.reason}</span>
                    <span className="ws-version-metrics">
                      {version.metrics.class_size_min}–{version.metrics.class_size_max} בכיתה
                      {version.metrics.students_with_requests > 0 && ` · ${Math.round(version.metrics.mutual_satisfied_pct)}% חברות`}
                      {version.moved_students_from_previous != null && ` · ${version.moved_students_from_previous} עברו`}
                      {version.metrics.violations_count > 0 && ` · ${version.metrics.violations_count} חריגות חובה`}
                      {version.locked_count > 0 && ` · ${version.locked_count} מקובעות`}
                    </span>
                  </div>
                  {!current && (
                    <button
                      type="button"
                      className="ws-link"
                      disabled={restoringVersion !== null}
                      onClick={() => setRestoreCandidate((candidate) => candidate === version.id ? null : version.id)}
                      aria-expanded={restoreCandidate === version.id}
                      aria-label={`שחזור גרסה ${version.number}: ${version.reason}`}
                    >
                      שחזור
                    </button>
                  )}
                  {restoreCandidate === version.id && (
                    <div className="ws-version-restore-confirm" role="group" aria-label={`אישור שחזור גרסה ${version.number}`}>
                      <span>גרסה {version.number} תחליף את השיבוץ הפעיל. הגרסאות האחרות יישמרו.</span>
                      <div>
                        <Button size="sm" onClick={() => void restore(version.id)} disabled={restoringVersion !== null}>
                          {restoringVersion === version.id ? "משחזרת…" : "אישור שחזור"}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setRestoreCandidate(null)} disabled={restoringVersion !== null}>
                          ביטול
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </InspectorCard>
      )}

      <InspectorCard icon="grid" title="שיבוץ" onOpen={versions.items.length > 0 ? onOpenResults : undefined}>
        <div className="ws-insp-stepper">
          <span className="val">
            <span className="n" aria-live="polite">
              {runConfig ? runConfig.num_classes : dash}
            </span>
            <span className="u">כיתות</span>
          </span>
          <span className="ws-insp-stepper-btns">
            <button
              type="button"
              className="ws-step-btn"
              onClick={() => setClasses((runConfig?.num_classes ?? MIN_CLASSES) - 1)}
              disabled={!runConfig || runConfig.num_classes <= MIN_CLASSES}
              aria-label="כיתה אחת פחות"
            >
              <Icon name="minus" size={16} />
            </button>
            <button
              type="button"
              className="ws-step-btn"
              onClick={() => setClasses((runConfig?.num_classes ?? MIN_CLASSES) + 1)}
              disabled={!runConfig || runConfig.num_classes >= MAX_CLASSES}
              aria-label="כיתה אחת יותר"
            >
              <Icon name="plus" size={16} />
            </button>
          </span>
        </div>

        <div className="ws-insp-kv">
          <label htmlFor="ws-time-limit">משך חיפוש מרבי</label>
          <span className="ws-insp-num">
            <input
              id="ws-time-limit"
              type="number"
              min={10}
              max={600}
              step={10}
              value={runConfig ? runConfig.time_limit_seconds : ""}
              disabled={!runConfig}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (runConfig && Number.isFinite(v)) patch({ ...runConfig, time_limit_seconds: v });
              }}
            />
            שניות
          </span>
        </div>
      </InspectorCard>
    </>
  );
}

function InspectorCard({
  icon,
  title,
  onOpen,
  children,
}: {
  icon: IconName;
  title: string;
  onOpen?: () => void;
  children: React.ReactNode;
}) {
  // Without an `onOpen` this is a plain heading, not a disabled button --
  // a card you can Tab to but never activate is noise in the tab order.
  const head = (
    <>
      <span className="ws-insp-icon-lg">
        <Icon name={icon} size={16} />
      </span>
      <span className="ws-insp-card-title">{title}</span>
      {onOpen && <Icon name="chevron" size={14} className="ws-chev" style={{ transform: "rotate(-90deg)" }} />}
    </>
  );

  return (
    <div className="ws-insp-card">
      {onOpen ? (
        <button className="ws-insp-card-head" onClick={() => onOpen()}>
          {head}
        </button>
      ) : (
        <div className="ws-insp-card-head as-heading">{head}</div>
      )}
      {children}
    </div>
  );
}
