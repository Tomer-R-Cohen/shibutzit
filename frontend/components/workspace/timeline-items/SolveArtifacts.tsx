"use client";

import { CSSProperties, useEffect, useState } from "react";
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
  { title: "קוראת את כללי החובה", detail: "מקבעת את הגבולות שאסור לשיבוץ להפר" },
  { title: "ממפה את תמונת השכבה", detail: "מחברת בין נתוני התמיכה, האיזון והקשרים החברתיים" },
  { title: "מרכיבה חלוקות אפשריות", detail: "בוחנת אלפי שילובים בלי לשנות את הנתונים המקוריים" },
  { title: "בודקת כל כיתה", detail: "מוודאת שכל תלמידה משובצת ושכל כללי החובה נשמרים" },
  { title: "משווה בין החלופות", detail: "מחפשת את השילוב הטוב ביותר בין חברות לאיזון" },
  { title: "ממשיכה לחפש שיפור", detail: "שיבוץ מלא יכול להימשך עד דקה — אפשר להמשיך לעבוד כשהוא מוכן" },
];

const CLASS_NUMBERS = [1, 2, 3, 4, 5, 6];
const ROUTE_BENDS = [
  [-92, -62], [-52, -42], [92, -62],
  [-92, 62], [52, 42], [92, 62],
];
const LANE_OFFSETS = [
  [-9, -5], [-3, 7], [4, -8], [10, 4],
];
const PARTICLES = Array.from({ length: 24 }, (_, index) => ({
  target: index % CLASS_NUMBERS.length,
  delay: -((index * 0.47) % 6.4),
  size: 4 + (index % 3),
  bendX: ROUTE_BENDS[index % CLASS_NUMBERS.length][0] + ((index % 4) - 1.5) * 7,
  bendY: ROUTE_BENDS[index % CLASS_NUMBERS.length][1] + ((index % 3) - 1) * 6,
  endX: LANE_OFFSETS[Math.floor(index / CLASS_NUMBERS.length)][0],
  endY: LANE_OFFSETS[Math.floor(index / CLASS_NUMBERS.length)][1],
}));

export function SolveStartedArtifact() {
  const [phase, setPhase] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const phaseId = window.setInterval(() => {
      setPhase((p) => (p < SOLVE_PHASES.length - 1 ? p + 1 : p));
    }, 5200);
    const clockId = window.setInterval(() => setElapsed((seconds) => seconds + 1), 1000);
    return () => {
      window.clearInterval(phaseId);
      window.clearInterval(clockId);
    };
  }, []);

  return (
    <div className={`ws-artifact ws-solve-live phase-${phase + 1}${paused ? " is-paused" : ""}`}>
      <div className="ws-solve-live-header">
        <div className="ws-solve-live-copy">
          <span className="ws-solve-live-kicker">
            <span className="ws-solve-live-dot" aria-hidden />
            מנוע השיבוץ עובד עכשיו
          </span>
          <div key={phase} className="ws-solve-live-phase">
            <strong>{SOLVE_PHASES[phase].title}</strong>
            <span>{SOLVE_PHASES[phase].detail}</span>
          </div>
        </div>
        <div className="ws-solve-live-controls">
          <button
            type="button"
            className="ws-solve-motion-toggle"
            onClick={() => setPaused((value) => !value)}
            aria-label={paused ? "הפעל את אנימציית השיבוץ" : "השהה את אנימציית השיבוץ"}
            title={paused ? "הפעל אנימציה" : "השהה אנימציה"}
          >
            <span className={paused ? "play" : "pause"} aria-hidden />
          </button>
          <span className="ws-solve-live-time" aria-hidden>
            {elapsed < 60 ? `${elapsed} שנ׳` : `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`}
          </span>
        </div>
      </div>

      <div className="ws-solver-viz" aria-hidden>
        <div className="ws-solver-grid" />
        <div className="ws-solver-scan" />
        <svg className="ws-solver-routes" viewBox="0 0 760 230" preserveAspectRatio="none">
          <path d="M380 115 C300 78 190 58 106 62" />
          <path d="M380 115 C350 70 356 45 380 37" />
          <path d="M380 115 C460 78 570 58 654 62" />
          <path d="M380 115 C300 152 190 172 106 168" />
          <path d="M380 115 C350 160 356 185 380 193" />
          <path d="M380 115 C460 152 570 172 654 168" />
        </svg>

        {CLASS_NUMBERS.map((classNumber, index) => (
          <div key={classNumber} className={`ws-solver-class class-${index + 1}`}>
            <span className="ws-solver-class-name">ז׳{classNumber}</span>
            <span className="ws-solver-class-dots">
              <i /><i /><i /><i />
            </span>
          </div>
        ))}

        <div className="ws-solver-core">
          <span className="ws-solver-orbit orbit-a" />
          <span className="ws-solver-orbit orbit-b" />
          <span className="ws-solver-core-glow" />
          <span className="ws-solver-core-icon"><Icon name="sparkle" size={22} /></span>
        </div>

        <div className="ws-solver-particles">
          {PARTICLES.map((particle, index) => (
            <i
              key={index}
              className={`ws-solver-particle target-${particle.target}`}
              style={{
                "--particle-delay": `${particle.delay}s`,
                "--particle-size": `${particle.size}px`,
                "--bend-x": `${particle.bendX}px`,
                "--bend-y": `${particle.bendY}px`,
                "--end-x": `${particle.endX}px`,
                "--end-y": `${particle.endY}px`,
              } as CSSProperties}
            />
          ))}
        </div>
      </div>

      <div className="ws-solve-live-steps" aria-hidden>
        {SOLVE_PHASES.map((item, index) => (
          <span key={item.title} className={index < phase ? "done" : index === phase ? "active" : ""} />
        ))}
      </div>
      <span className="sr-only" role="status" aria-live="polite">{SOLVE_PHASES[phase].title}. {SOLVE_PHASES[phase].detail}</span>
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
      items.push({ text: `בכיתה ז׳${cls} האיזון מעט חלש יותר`, target: { kind: "class", id: cls } });
    }
  }

  if (metrics.unsatisfied_requests > 0) {
    items.push({ text: `${metrics.unsatisfied_requests} בקשות חברות לא קיבלו מענה`, target: { kind: "constraints" } });
  }

  if (metrics.class_size_spread > 1) {
    const maxIdx = metrics.class_sizes.indexOf(metrics.class_size_max);
    items.push({
      text: `בכיתה ז׳${maxIdx + 1} יש ${metrics.class_size_max} תלמידות, לעומת ${metrics.class_size_min} בכיתה הקטנה ביותר`,
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
 *
 * The bars deliberately visualize class SIZE, not the "ציון איכות" quality
 * score -- that score is driven almost entirely by constraint violations
 * and friendship satisfaction, so on a typical run (0 violations, no
 * friendship data yet entered) every class scores an identical 100 and the
 * chart shows nothing. Size genuinely varies run to run and is exactly
 * what the size-spread attention item below is about, so the bar now
 * supports that callout instead of contradicting it.
 */
export function SolveResultArtifact({
  metrics,
  version,
  latest,
  highlight,
  onHighlight,
  onOpenResults,
  onOpenConstraints,
  onAttentionTarget,
}: {
  metrics: GlobalMetrics;
  version?: number;
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
  const hasFriendshipData = metrics.students_with_requests > 0;
  const attention = rows ? computeAttention(metrics, rows) : [];
  const highlightedClass = highlight?.kind === "class" ? highlight.id : null;

  const sizes = rows?.map((r) => r["גודל"]) ?? [];
  const sizeMin = sizes.length ? Math.min(...sizes) : 0;
  const sizeSpan = sizes.length ? Math.max(1, Math.max(...sizes) - sizeMin) : 1;

  const body = (
    <>
      <div className="ws-metrics-row">
        <div className="ws-metric">
          <span className={`ws-metric-value ${ok ? "tone-good" : "tone-crit"}`}>
            <CountUp value={metrics.violations_count} />
          </span>
          <span className="ws-metric-label">חריגות</span>
        </div>
        <div className="ws-metric">
          <span className="ws-metric-value">
            <CountUp value={metrics.class_size_spread} />
          </span>
          <span className="ws-metric-label">פער בין הכיתות</span>
        </div>
        <div className="ws-metric">
          <span className="ws-metric-value">{hasFriendshipData ? <><CountUp value={Math.round(metrics.mutual_satisfied_pct)} />%</> : "—"}</span>
          <span className="ws-metric-label">חברות הדדית</span>
        </div>
      </div>

      {!hasFriendshipData && (
        <p className="ws-artifact-note ws-artifact-note-muted">לא הוזנו בקשות חברות, ולכן עדיין אין מה למדוד.</p>
      )}

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
                <BalanceTrack value={r["גודל"] - sizeMin} max={sizeSpan} emphasised={isHi} />
              </button>
            );
          })}
        </div>
      )}

      {attention.length > 0 && (
        <div className="ws-attention">
          <div className="ws-attention-title">כדאי לבדוק</div>
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
          צפייה בכיתות
        </Button>
        <Button size="sm" variant="ghost" onClick={onOpenConstraints}>
          סקירת הכללים
        </Button>
      </div>
    </>
  );

  return (
    <div className={`ws-artifact ws-breakout ${ok ? "ws-artifact-ok" : "ws-artifact-warn"}`}>
      <div className="ws-result-hero">
        <div className="ws-result-intro">
          <span className="ws-result-icon" aria-hidden>
            <Icon name={ok ? "check" : "warning"} size={18} />
          </span>
          <div>
            <div className="ws-result-kicker">{version ? `גרסה ${version} · ` : ""}השיבוץ מוכן</div>
            <div className="ws-result-title">{ok ? "נמצא שיבוץ מאוזן" : "השיבוץ מוכן, ויש כמה נקודות לבדיקה"}</div>
            <p className="ws-artifact-note">
              {metrics.total_students} תלמידות שובצו ל-{metrics.num_classes} כיתות
              {!latest ? ` · פער גדלים ${metrics.class_size_spread}` : ""}
            </p>
          </div>
        </div>
        <div className="ws-result-range" aria-label={`טווח גודל הכיתות: ${metrics.class_size_min} עד ${metrics.class_size_max}`}>
          <span className="cw-num">
            {metrics.class_size_min === metrics.class_size_max
              ? metrics.class_size_min
              : `${metrics.class_size_min}–${metrics.class_size_max}`}
          </span>
          <small>תלמידות בכיתה</small>
        </div>
      </div>

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
  const conflictSummary =
    conflictingIds.length === 1
      ? "כלל חובה אחד אינו ניתן לקיום"
      : `${conflictingIds.length} כללי חובה מתנגשים זה בזה`;

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
        <span>
          עדיין לא נמצא שיבוץ אפשרי — {conflictingIds.length > 0 ? conflictSummary : `${notes.length} בעיות דורשות בדיקה`}
        </span>
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
      {conflictingIds.length > 0 && <p className="ws-artifact-note">{conflictSummary}</p>}
      {explanation && <p className="ws-artifact-note">{explanation}</p>}

      {rowsAvailable && (
        // the newest failure shows its breakdown open; older ones start
        // collapsed so a streak of retries doesn't stack identical walls.
        <ExpandableArtifact
          defaultExpanded={latest}
          collapsedLabel="הצג את כללי החובה המתנגשים"
          expandedLabel="הסתר את כללי החובה המתנגשים"
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

      <div className="ws-failure-safety" role="status">
        <Icon name="lock" size={13} />
        <span>לא שינינו אף כלל. כל ריכוך של כלל חובה יחכה לאישור מפורש שלכם.</span>
      </div>

      <div className="ws-artifact-actions">
        <Button size="sm" variant="secondary" onClick={onOpenConstraints}>
          סקירת הכללים
        </Button>
        {rowsAvailable && (
          <Button size="sm" variant="ghost" onClick={() => onOpenConstraint(conflicting![0].id)}>
            עריכת כלל
          </Button>
        )}
      </div>
    </div>
  );
}
