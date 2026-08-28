import { ConstraintType } from "@/lib/api";

// Shared across ConstraintProposalArtifact, SolveFailureArtifact, and
// ConstraintInspector so the same constraint reads the same way everywhere
// in the workspace.
export const TYPE_LABELS: Record<ConstraintType, string> = {
  capacity: "טווח או מגבלה",
  separate: "הפרדה",
  together: "צירוף",
  at_least_one_of: "לפחות אחת מקבוצה",
  balance: "איזון",
  locked: "נעילה",
  friendship_objective: "בקשות חברות",
};

// Constraint types whose args carry a numeric {min, max} range worth
// drawing as a bar (capacity/balance); others (separate/together/...) are
// relationship-shaped, not range-shaped.
export const RANGE_TYPES: ConstraintType[] = ["capacity", "balance"];
