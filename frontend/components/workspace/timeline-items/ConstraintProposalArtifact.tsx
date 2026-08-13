"use client";

import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/primitives";
import { PendingProposal } from "@/lib/api";
import { TYPE_LABELS } from "../constraintVisuals";

const KIND_TITLES: Record<PendingProposal["kind"], string> = {
  propose: "הצעה לכלל חדש",
  modify: "הצעה לשינוי כלל",
  remove: "הצעה להסרת כלל",
};

const DONE_LABELS: Record<PendingProposal["kind"], string> = {
  propose: "הכלל נוסף",
  modify: "הכלל עודכן",
  remove: "הכלל הוסר",
};

/**
 * A proposal is a structured action, not a chat bubble: what's being
 * proposed, its type/severity, and an explicit confirm/reject -- then it
 * transitions in place to a completed state rather than being replaced by
 * a new item, so the history stays legible ("what did I approve, and when").
 */
export function ConstraintProposalArtifact({
  proposal,
  status,
  onConfirm,
  onReject,
  deciding,
}: {
  proposal: PendingProposal;
  status: "pending" | "confirmed" | "rejected";
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
  const severity = proposal.constraint ? (proposal.constraint.hard ? "דרישה קשיחה" : "העדפה") : null;

  return (
    <div className="ws-proposal">
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
      <p className="ws-proposal-text">{proposal.summary_hebrew}</p>
      <div className="ws-proposal-actions">
        <Button size="sm" variant="secondary" onClick={onReject} disabled={deciding}>
          דחייה
        </Button>
        <Button size="sm" onClick={onConfirm} disabled={deciding}>
          {deciding ? "מבצע…" : "אישור והוספה"}
        </Button>
      </div>
    </div>
  );
}
