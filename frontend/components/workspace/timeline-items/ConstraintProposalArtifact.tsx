"use client";

import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/primitives";
import { PendingProposal } from "@/lib/api";
import { TYPE_LABELS } from "../constraintVisuals";

const KIND_TITLES: Record<PendingProposal["kind"], string> = {
  propose: "הצעה לכלל חדש",
  modify: "הצעה לשינוי כלל",
  remove: "הצעה להסרת כלל",
  assignment_action: "שינוי מוצע בשיבוץ",
  data_action: "תיקון מוצע בנתוני התלמידה",
};

const DONE_LABELS: Record<PendingProposal["kind"], string> = {
  propose: "הכלל נוסף",
  modify: "הכלל עודכן",
  remove: "הכלל הוסר",
  assignment_action: "השיבוץ עודכן",
  data_action: "נתוני התלמידה עודכנו",
};

type BatchChange = {
  constraint_id: string;
  changes?: { label_hebrew?: string };
  from?: { min?: number | null; max?: number | null };
  to?: { min?: number | null; max?: number | null };
  students_in_group?: number;
};

function proposalBatch(proposal: PendingProposal): BatchChange[] {
  const batch = proposal.changes?.batch;
  if (!Array.isArray(batch)) return [];
  return batch.filter((item): item is BatchChange => Boolean(item && typeof item === "object" && "constraint_id" in item));
}

function rangeLabel(range?: BatchChange["from"]) {
  if (!range) return "—";
  const min = range.min ?? 0;
  const max = range.max ?? "ללא הגבלה";
  return `${min}–${max}`;
}

/**
 * A proposal is a structured action, not a chat bubble: what's being
 * proposed, its type/severity, and an explicit confirm/reject -- then it
 * transitions in place to a completed state rather than being replaced by
 * a new item, so the history stays legible ("what did I approve, and when").
 */
export function ConstraintProposalArtifact({
  proposal,
  status,
  error,
  onConfirm,
  onReject,
  deciding,
}: {
  proposal: PendingProposal;
  status: "pending" | "confirmed" | "rejected";
  error?: string;
  onConfirm: () => void;
  onReject: () => void;
  deciding: boolean;
}) {
  if (status === "confirmed") {
    return (
      <div className="ws-artifact ws-artifact-done">
        <Icon name="check" size={14} />
        <span>{DONE_LABELS[proposal.kind]}</span>
      </div>
    );
  }
  if (status === "rejected") {
    return (
      <div className="ws-artifact ws-artifact-muted">
        <Icon name="x" size={14} />
        <span>ההצעה נדחתה</span>
      </div>
    );
  }

  const typeLabel = proposal.constraint ? (TYPE_LABELS[proposal.constraint.type] ?? proposal.constraint.type) : null;
  const severity = proposal.constraint ? (proposal.constraint.hard ? "כלל חובה" : "כלל מועדף") : null;

  const changesHardRule = Boolean(proposal.evidence?.changes_hard_rule || proposal.constraint?.hard);
  const batch = proposalBatch(proposal);

  return (
    <section className={`ws-proposal${changesHardRule ? " hard-change" : ""}`} aria-label={KIND_TITLES[proposal.kind]} aria-busy={deciding}>
      <div className="ws-proposal-head">
        <Icon name="sparkle" size={13} />
        <span>{KIND_TITLES[proposal.kind]}</span>
      </div>
      {(typeLabel || severity) && (
        <div className="ws-proposal-meta">
          {typeLabel && <span className="ws-proposal-chip">{typeLabel}</span>}
          {severity && <span className="ws-proposal-chip">{severity}</span>}
        </div>
      )}
      {proposal.evidence && (
        <div className="ws-proposal-meta">
          {proposal.evidence.basis === "measured_trial" && proposal.evidence.trial_feasible && (
            <span className="ws-proposal-chip">נבדק בהרצת ניסיון</span>
          )}
          {proposal.evidence.basis === "arithmetic_feasibility_package" && proposal.evidence.item_count && (
            <span className="ws-proposal-chip">{proposal.evidence.item_count} שינויים בחבילה אחת</span>
          )}
          {proposal.evidence.changes_hard_rule && <span className="ws-proposal-chip">דורש אישור לשינוי כלל חובה</span>}
        </div>
      )}
      <p className="ws-proposal-text">{proposal.summary_hebrew}</p>
      {batch.length > 0 && (
        <div className="ws-proposal-batch" aria-label="השינויים המוצעים בחבילה">
          {batch.map((item, index) => (
            <div className="ws-proposal-batch-row" key={item.constraint_id}>
              <span className="ws-proposal-batch-number">{index + 1}</span>
              <span className="ws-proposal-batch-label">
                {item.changes?.label_hebrew ?? "עדכון כלל חובה"}
                {typeof item.students_in_group === "number" && (
                  <small>{item.students_in_group} תלמידות בנתונים</small>
                )}
              </span>
              <span className="ws-proposal-batch-range" dir="ltr">
                {rangeLabel(item.from)} <span aria-hidden="true">→</span> {rangeLabel(item.to)}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="ws-proposal-state" role="status">
        <Icon name="lock" size={13} />
        <span><strong>השינוי עדיין לא הוחל.</strong> הוא ייכנס לפרויקט רק לאחר אישור שלך.</span>
      </div>
      {error && (
        <div className="ws-proposal-error" role="alert">
          <Icon name="warning" size={14} />
          <span><strong>ההצעה לא עודכנה.</strong> {error} אפשר לנסות שוב; לא בוצע שינוי בכלל.</span>
        </div>
      )}
      <div className="ws-proposal-actions">
        <Button size="sm" onClick={onConfirm} disabled={deciding}>
          {deciding ? "מעדכנת…" : batch.length > 1 ? `אישור כל ${batch.length} השינויים` : "אישור ההצעה"}
        </Button>
        <Button size="sm" variant="secondary" onClick={onReject} disabled={deciding}>
          לא הפעם
        </Button>
      </div>
    </section>
  );
}
