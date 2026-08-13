"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/primitives";
import { ClassOverviewRow, ConstraintModel, GlobalMetrics, getConstraints, getResultsOverview } from "@/lib/api";
import { AttentionItem, AttentionTarget, Highlight } from "@/lib/workspace";
import { BalanceTrack } from "../BalanceTrack";
import { CountUp } from "../CountUp";
import { RANGE_TYPES, TYPE_LABELS } from "../constraintVisuals";
import { RangeBar } from "../RangeBar";
import { ExpandableArtifact } from "./ExpandableArtifact";
import { formatTime } from "./shared";

// A solve runs ~30s. Rather than one frozen line for the whole wait, walk
// through the phases the solver actually goes through.
//
// Every line has to stay true whether the run ends in a solution *or* in a
// proven infeasibility -- so these describe the search itself, never
// improvement of a result that may not exist ("משפר את השיבוץ…" would be a
// lie on a run that's about to come back infeasible). The last line sets
// expectation for a long run instead of pretending to be nearly done.
const SOLVE_PHASES = [
  "קורא את הכללים…",
  "בונה את מודל השיבוץ…",
  "סורק חלוקות אפשריות…",
  "בודק התאמה לכללים הקשיחים…",
  "מחפש את החלוקה המאוזנת ביותר…",
  "עדיין מחפש — הרצה מלאה יכולה לקחת עד דקה…",
];

export function SolveStartedArtifact() {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => {
      setPhase((p) => (p < SOLVE_PHASES.length - 1 ? p + 1 : p));
    }, 3200);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="ws-artifact ws-artifact-progress" role="status" aria-live="polite">
      <span className="ws-spinner" aria-hidden />
      {/* key remounts the span so the entrance animation replays per phase */}
      <span key={phase} className="ws-phase-text">
        {SOLVE_PHASES[phase]}
      </span>
    </div>
  );
}

// A handful of plain-language observations pulled from real per-class data
// (not invented) -- weakest class by quality score, unmet friendship
// requests, a class-size outlier. Each carries a target so clicking it
// lands somewhere specific rather than dumping the user in a generic list.
// Capped at 4 so this stays a short list, not a report.
function computeAttention(metrics: GlobalMetrics, rows: ClassOverviewRow[]): AttentionItem[] {
  const items: AttentionItem[] = [];

  if (rows.length > 1) {
    const scores = rows.map((r) => r["ציון איכות"]);
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    let worstIdx = -1;
    let worstGap = 0;
    rows.forEach((r, i) => {
      const gap = avg - r["ציון איכות"];
      if (gap > worstGap) {
        worstGap = gap;
        worstIdx = i;
      }
    });
    if (worstIdx >= 0 && worstGap >= 5) {
      const cls = rows[worstIdx]["כיתה"];
      items.push({ text: `ז'${cls} מעט חלשה יותר באיזון הכיתה`, target: { kind: "class", id: cls } });
    }
  }

  if (metrics.unsatisfied_requests > 0) {
    items.push({ text: `${metrics.unsatisfied_requests} בקשות חברות לא מולאו`, target: { kind: "constraints" } });
  }

  if (metrics.class_size_spread > 1) {
    const maxIdx = metrics.class_sizes.indexOf(metrics.class_size_max);
    items.push({
      text: `ז'${maxIdx + 1} מכילה ${metrics.class_size_max} תלמידות לעומת ${metrics.class_size_min} בכיתה הקטנה ביותר`,
      target: { kind: "class", id: maxIdx + 1 },
    });
  }

  return items.slice(0, 4);
}

/**
 * The first question after a solve is "is this good?", not "where is every
 * student" -- so this is a quality summary + per-class balance bars +
 * plain-language attention items, not the 217-card board. "פתיחת הכיתות" is
 * where the board (ClassWall, Milestone 2) lives. Per-class figures come
 * from /api/results/overview (class_overview_table), fetched once the
 * result exists.
 */
export function SolveResultArtifact({
  metrics,
  latest,
  highlight,
  onHighlight,
  onOpenResults,
  onOpenConstraints,
  onAttentionTarget,
}: {
  metrics: GlobalMetrics;
  latest: boolean;
  highlight: Highlight;
  onHighlight: (h: Highlight) => void;
  onOpenResults: () => void;
  onOpenConstraints: () => void;
  onAttentionTarget: (t: AttentionTarget) => void;
}) {
  const [rows, setRows] = useState<ClassOverviewRow[] | null>(null);

  useEffect(() => {
    getResultsOverview()
      .then((r) => setRows(r.rows))
      .catch(() => setRows([]));
  }, []);

  const ok = metrics.violations_count === 0;
  const avgQuality = rows && rows.length > 0 ? Math.round(rows.reduce((a, r) => a + r["ציון איכות"], 0) / rows.length) : null;
  const attention = rows ? computeAttention(metrics, rows) : [];
  const highlightedClass = highlight?.kind === "class" ? highlight.id : null;

  const body = (
    <>
      <div className="ws-metrics-row">
        <div className="ws-metric">
          <span className={`ws-metric-value ${ok ? "tone-good" : "tone-crit"}`}>
            <CountUp value={metrics.violations_count} />
          </span>
          <span className="ws-metric-label">הפרות</span>
        </div>
        {avgQuality != null && (
          <div className="ws-metric">
            <span className="ws-metric-value">
              <CountUp value={avgQuality} />
            </span>
            <span className="ws-metric-label">איזון</span>
          </div>
        )}
        <div className="ws-metric">
          <span className="ws-metric-value">
            <CountUp value={Math.round(metrics.mutual_satisfied_pct)} />%
          </span>
          <span className="ws-metric-label">חברות</span>
        </div>
      </div>

      {rows && rows.length > 0 && (
        <div className="ws-class-bars">
          {rows.map((r, i) => {
            const cls = r["כיתה"];
            const isHi = highlightedClass === cls;
            const dimmed = highlightedClass != null && !isHi;
            return (
              <button
                key={cls}
                type="button"
                className={`ws-class-bar-row${isHi ? " is-highlighted" : ""}${dimmed ? " is-dimmed" : ""}`}
                style={{ animationDelay: `${i * 40}ms` }}
                onMouseEnter={() => onHighlight({ kind: "class", id: cls })}
                onMouseLeave={() => onHighlight(null)}
                onFocus={() => onHighlight({ kind: "class", id: cls })}
                onBlur={() => onHighlight(null)}
                onClick={onOpenResults}
              >
                <span className="ws-class-bar-name">{`ז'${cls}`}</span>
                <span className="ws-class-bar-size cw-num">{r["גודל"]}</span>
                <BalanceTrack value={r["ציון איכות"]} emphasised={isHi} />
                <span className="ws-class-bar-value cw-num">{Math.round(r["ציון איכות"])}</span>
              </button>
            );
          })}
        </div>
      )}

      {attention.length > 0 && (
        <div className="ws-attention">
          <div className="ws-attention-title">דורש תשומת לב</div>
          {attention.map((item, i) => (
            <button
              key={i}
              type="button"
              className="ws-attention-item"
              onMouseEnter={() => onHighlight(item.target.kind === "class" ? { kind: "class", id: item.target.id } : null)}
              onMouseLeave={() => onHighlight(null)}
              onClick={() => onAttentionTarget(item.target)}
            >
              <Icon name="arrow-up-right" size={12} className="ws-attention-item-arrow" />
              <span className="ws-attention-item-text">{item.text}</span>
            </button>
          ))}
        </div>
      )}

      <div className="ws-artifact-actions">
        <Button size="sm" variant="secondary" onClick={onOpenResults}>
          פתיחת הכיתות
        </Button>
        <Button size="sm" variant="ghost" onClick={onOpenConstraints}>
          בדיקת הכללים
        </Button>
      </div>
    </>
  );

  return (
    <div className={`ws-artifact ws-breakout ${ok ? "ws-artifact-ok" : "ws-artifact-warn"}`}>
      <div className="ws-artifact-head">
        <Icon name={ok ? "check" : "warning"} size={15} />
        <span>שיבוץ הושלם</span>
      </div>
      <p className="ws-artifact-note">
        {metrics.total_students} תלמידות שובצו ל-{metrics.num_classes} כיתות
        {!latest && avgQuality != null ? ` · איזון ${avgQuality}` : ""}
      </p>

      {/* only the newest result stays open -- older ones collapse so the
          timeline reads as history rather than a stack of dashboards. */}
      {latest ? body : <ExpandableArtifact collapsedLabel="הצג תוצאות" expandedLabel="הסתר תוצאות">{body}</ExpandableArtifact>}
    </div>
  );
}

function ConflictRow({
  c,
  highlighted,
  onOpen,
  onHighlight,
}: {
  c: ConstraintModel;
  highlighted: boolean;
  onOpen: () => void;
  onHighlight: (h: Highlight) => void;
}) {
  const showRange = RANGE_TYPES.includes(c.type) && (c.args.min != null || c.args.max != null);
  return (
    <button
      type="button"
      className={`ws-conflict-row${highlighted ? " is-highlighted" : ""}`}
      onClick={onOpen}
      onMouseEnter={() => onHighlight({ kind: "constraint", id: c.id })}
      onMouseLeave={() => onHighlight(null)}
      onFocus={() => onHighlight({ kind: "constraint", id: c.id })}
      onBlur={() => onHighlight(null)}
    >
      <div className="ws-conflict-row-head">
        <span className="ws-conflict-row-type">{TYPE_LABELS[c.type] ?? c.type}</span>
        <Icon name="chevron" size={12} className="ws-conflict-row-chevron" />
      </div>
      {showRange && <RangeBar min={c.args.min as number | null} max={c.args.max as number | null} />}
      <span className="ws-conflict-row-label">{c.label_hebrew}</span>
    </button>
  );
}

/**
 * Every hard-rule conflict CP-SAT actually found (via assumption-literal
 * extraction, not a guess) becomes a clickable row -- clicking one opens
 * that exact constraint's inspector, which is the real "what would change
 * this" action, rather than a generic details button. A repeat failure in
 * the same streak collapses to a compact activity line instead of
 * re-rendering the full breakdown every time.
 */
export function SolveFailureArtifact({
  notes,
  explanation,
  conflictingIds,
  repeat,
  at,
  latest,
  highlight,
  onHighlight,
  onOpenConstraints,
  onOpenConstraint,
}: {
  notes: string[];
  explanation?: string | null;
  conflictingIds: string[];
  repeat: boolean;
  at: number;
  latest: boolean;
  highlight: Highlight;
  onHighlight: (h: Highlight) => void;
  onOpenConstraints: () => void;
  onOpenConstraint: (id: string) => void;
}) {
  const [conflicting, setConflicting] = useState<ConstraintModel[] | null>(null);

  useEffect(() => {
    if (repeat || conflictingIds.length === 0) return;
    getConstraints()
      .then((r) => setConflicting(r.constraints.filter((c) => conflictingIds.includes(c.id))))
      .catch(() => setConflicting([]));
  }, [repeat, conflictingIds]);

  if (repeat) {
    return (
      <div className="ws-event">
        <Icon name="warning" size={12} />
        <span>ניסיון שיבוץ נכשל — {conflictingIds.length || notes.length} כללים קשיחים עדיין מתנגשים</span>
        <button type="button" className="ws-link" onClick={onOpenConstraints}>
          הצג פרטים
        </button>
        <span className="ws-event-time cw-num">{formatTime(at)}</span>
      </div>
    );
  }

  const rowsAvailable = conflicting && conflicting.length > 0;
  const highlightedConstraint = highlight?.kind === "constraint" ? highlight.id : null;

  return (
    <div className="ws-artifact ws-artifact-crit">
      <div className="ws-artifact-head">
        <Icon name="warning" size={15} />
        <span>לא נמצא שיבוץ אפשרי</span>
      </div>
      {conflictingIds.length > 0 && <p className="ws-artifact-note">{conflictingIds.length} כללים קשיחים דורשים בדיקה</p>}
      {explanation && <p className="ws-artifact-note">{explanation}</p>}

      {rowsAvailable && (
        // the newest failure shows its breakdown open; older ones start
        // collapsed so a streak of retries doesn't stack identical walls.
        <ExpandableArtifact
          defaultExpanded={latest}
          collapsedLabel="הצגת הכללים המתנגשים"
          expandedLabel="הסתרת הכללים המתנגשים"
        >
          {conflicting!.map((c) => (
            <ConflictRow
              key={c.id}
              c={c}
              highlighted={highlightedConstraint === c.id}
              onOpen={() => onOpenConstraint(c.id)}
              onHighlight={onHighlight}
            />
          ))}
        </ExpandableArtifact>
      )}

      {!rowsAvailable && notes.length > 0 && (
        <ul className="ws-artifact-list">
          {notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}

      <div className="ws-artifact-actions">
        <Button size="sm" variant="secondary" onClick={onOpenConstraints}>
          בדיקת הכללים
        </Button>
        {rowsAvailable && (
          <Button size="sm" variant="ghost" onClick={() => onOpenConstraint(conflicting![0].id)}>
            שינוי כלל
          </Button>
        )}
      </div>
    </div>
  );
}
