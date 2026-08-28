// Deterministic, hand-written states for visually verifying timeline
// artifacts that are hard to reach live -- mainly anything gated behind an
// LLM call, which has no API key in this environment. Reached via
// `?fixture=<name>` in dev only (see FixturePreview.tsx).

import { ConstraintModel } from "./api";
import { ConstraintsSummary, TimelineItem } from "./workspace";

export interface Fixture {
  timeline: TimelineItem[];
  studentCount: number | null;
  constraintsSummary: ConstraintsSummary | null;
}

let seq = 0;
function id(): string {
  seq += 1;
  return `fx-${seq}`;
}

const SEPARATE_CONSTRAINT: ConstraintModel = {
  id: "c-separate-1",
  type: "separate",
  hard: true,
  args: { members: ["שרה כהן", "מיכל לוי"] },
  label_hebrew: "שרה כהן ומיכל לוי לא יהיו באותה כיתה",
  source: "chat",
  active: true,
};

const BALANCE_CONSTRAINT: ConstraintModel = {
  id: "c-balance-1",
  type: "balance",
  hard: false,
  args: { field: "academic_level" },
  label_hebrew: "איזון רמת הישגים בין הכיתות",
  source: "chat",
  active: true,
};

const baseCounts: ConstraintsSummary = { total: 10, active: 10, hard: 5, soft: 5 };

function datasetReady(): TimelineItem {
  return {
    id: id(),
    kind: "dataset_ready",
    at: Date.now(),
    studentCount: 217,
    schoolCount: 12,
    levelCount: 3,
    warningCount: 0,
    levelCounts: { "מצטיינת": 74, "בינונית": 98, "חלשה": 45 },
  };
}

export const FIXTURES: Record<string, Fixture> = {
  empty: {
    timeline: [],
    studentCount: null,
    constraintsSummary: null,
  },

  "dataset-ready": {
    timeline: [datasetReady()],
    studentCount: 217,
    constraintsSummary: baseCounts,
  },

  "data-warning": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "data_warning", at: Date.now(), problems: ["שלוש בקשות חברות לא זוהו: \"רותם\", \"נויה כהן\" ו\"תמר\" — השם לא ברור או לא נמצא ברשימה"] },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
  },

  "constraint-proposal": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "שרה כהן ומיכל לוי לא יכולות להיות באותה כיתה" },
      { id: id(), kind: "assistant_message", at: Date.now(), text: "הבנתי. ניסחתי הצעה לכלל חדש, ואחכה לאישור שלכם לפני שאוסיף אותו." },
      {
        id: id(),
        kind: "constraint_proposal",
        at: Date.now(),
        status: "pending",
        proposal: { kind: "propose", summary_hebrew: "שרה כהן ומיכל לוי לא ישובצו לאותה כיתה.", constraint: SEPARATE_CONSTRAINT },
      },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
  },

  "constraint-modify": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "אפשר לעשות את איזון ההישגים לכלל חובה ולא רק העדפה?" },
      {
        id: id(),
        kind: "constraint_proposal",
        at: Date.now(),
        status: "pending",
        proposal: {
          kind: "modify",
          summary_hebrew: "שינוי \"איזון רמת הישגים בין הכיתות\" מהעדפה לכלל חובה.",
          constraint: { ...BALANCE_CONSTRAINT, hard: true },
          target_constraint_id: BALANCE_CONSTRAINT.id,
          changes: { hard: true },
        },
      },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
  },

  "constraint-confirmed": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "שרה כהן ומיכל לוי לא יכולות להיות באותה כיתה" },
      {
        id: id(),
        kind: "constraint_proposal",
        at: Date.now(),
        status: "confirmed",
        proposal: { kind: "propose", summary_hebrew: "שרה כהן ומיכל לוי לא ישובצו לאותה כיתה.", constraint: SEPARATE_CONSTRAINT },
      },
      { id: id(), kind: "constraint_event", at: Date.now(), action: "applied", label: SEPARATE_CONSTRAINT.label_hebrew },
    ],
    studentCount: 217,
    constraintsSummary: { ...baseCounts, total: 11, active: 11, hard: 6 },
  },

  solved: {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "הפיקי שיבוץ לפי הכללים שסיכמנו" },
      {
        id: id(),
        kind: "solve_result",
        at: Date.now(),
        metrics: {
          total_students: 217,
          num_classes: 6,
          class_sizes: [36, 36, 36, 36, 36, 37],
          class_size_min: 36,
          class_size_max: 37,
          class_size_spread: 1,
          mutual_satisfied_pct: 84,
          two_friends_satisfied_pct: 72,
          satisfied_requests: 91,
          partial_requests: 23,
          unsatisfied_requests: 7,
          violations_count: 0,
          students_with_requests: 121,
          solver_status: "FEASIBLE",
          solver_wall_time: 18.4,
          objective_value: 682,
        },
      },
      { id: id(), kind: "assistant_message", at: Date.now(), text: "הכיתות כמעט זהות בגודל, וכל כללי החובה נשמרו. כדאי לעבור על שבע בקשות החברות שלא קיבלו מענה לפני הייצוא." },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
  },

  // conflictingIds is deliberately empty here -- fixture mode has no real
  // constraint ids to point at, so this exercises the text-fallback path.
  // The clickable-row path (real conflictingIds joined against
  // getConstraints()) is verified against the live backend instead, see
  // task #59 in the plan.
  infeasible: {
    timeline: [
      datasetReady(),
      {
        id: id(),
        kind: "solve_failure",
        at: Date.now(),
        notes: [
          "גודל כיתה בין 35 ל-38: לא ניתן לחלק 217 תלמידות ל-6 כיתות בטווח הזה יחד עם שאר האילוצים.",
          "הפרדה בין שרה כהן למיכל לוי מתנגשת עם צירוף שרה כהן ודנה מזרחי לאותה כיתה.",
        ],
        explanation: "שני כללי החובה \"הפרדה בין שרה כהן למיכל לוי\" ו\"צירוף שרה כהן ודנה מזרחי\" לא יכולים להתקיים יחד עם מגבלת גודל הכיתה הנוכחית.",
        conflictingIds: [],
        repeat: false,
      },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
  },

  "infeasible-repeat": {
    timeline: [
      datasetReady(),
      {
        id: id(),
        kind: "solve_failure",
        at: Date.now(),
        notes: ["גודל כיתה בין 35 ל-38: לא ניתן לחלק 217 תלמידות ל-6 כיתות בטווח הזה יחד עם שאר האילוצים."],
        explanation: null,
        conflictingIds: [],
        repeat: false,
      },
      {
        id: id(),
        kind: "solve_failure",
        at: Date.now(),
        notes: ["גודל כיתה בין 35 ל-38: לא ניתן לחלק 217 תלמידות ל-6 כיתות בטווח הזה יחד עם שאר האילוצים."],
        explanation: null,
        conflictingIds: ["c-1", "c-2"],
        repeat: true,
      },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
  },
};

export type FixtureName = keyof typeof FIXTURES;
