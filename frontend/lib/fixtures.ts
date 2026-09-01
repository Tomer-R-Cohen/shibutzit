// Deterministic, hand-written states for visually verifying timeline
// artifacts that are hard to reach live -- mainly anything gated behind an
// LLM call, which has no API key in this environment. Reached via
// `?fixture=<name>` in dev only (see FixturePreview.tsx).

import { ConstraintModel, GlobalMetrics, ReviewGroup, StudentRecord } from "./api";
import { ConstraintsSummary, InspectorState, TimelineItem } from "./workspace";
import type { StudentRow } from "@/components/ClassWall";
import type { OverviewInspectorPreview } from "@/components/workspace/inspector/OverviewInspector";

export interface Fixture {
  timeline: TimelineItem[];
  studentCount: number | null;
  constraintsSummary: ConstraintsSummary | null;
  overviewPreview?: OverviewInspectorPreview;
  inspectorPreview?: {
    initial: InspectorState;
    constraints: ConstraintModel[];
    open?: boolean;
  };
  rosterReview?: StudentRecord[];
  rosterError?: string;
  rosterSaveError?: string;
  classReview?: {
    students: StudentRow[];
    constraints: ConstraintModel[];
    numClasses: number;
    metrics: GlobalMetrics;
    reviewGroups?: ReviewGroup[];
    violationRows?: Record<string, unknown>[];
    approved?: boolean;
    stale?: boolean;
    selectedStudentId?: number;
    pendingClass?: number;
    loadError?: string;
  };
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
    detectedFields: ["בית ספר נוכחי", "רמה לימודית", "בקשות חברות", "שילוב", 'ח״מ'],
    missingFields: ["דיפרנציאליות"],
    friendshipCount: 186,
  };
}

const REVIEW_FIRST_NAMES = ["נועה", "מאיה", "יעל", "דנה", "שירה", "רוני", "איילה", "תמר", "הילה", "נגה", "אביגיל", "ליה", "מיכל", "שרה", "רחל", "אלה", "עדי", "רותם", "נעמי", "אור"];
const REVIEW_LAST_NAMES = ["כהן", "לוי", "מזרחי", "פרץ", "אברהם", "דהן", "ביטון", "חדד", "מלכה"];

function classReviewStudents(): StudentRow[] {
  return Array.from({ length: 180 }, (_, index) => {
    const classNumber = (index % 6) + 1;
    const position = Math.floor(index / 6);
    const level = ["מצטיינת", "בינונית", "חלשה"][position % 3];
    return {
      "מזהה": index + 1,
      "שם פרטי": REVIEW_FIRST_NAMES[index % REVIEW_FIRST_NAMES.length],
      "שם משפחה": REVIEW_LAST_NAMES[Math.floor(index / REVIEW_FIRST_NAMES.length) % REVIEW_LAST_NAMES.length],
      "כיתה משובצת": classNumber,
      'ביה"ס נוכחי': `בית ספר ${(index % 8) + 1}`,
      "הישגים לימודיים": level,
      "שילוב": position < 2,
      'ח"מ': position === 2,
      "מוצא אתיופי": position >= 3 && position <= 5,
      "דיפרנציאלית": position === 6,
      "נעולה": position === 8 && classNumber % 2 === 0,
      "בקשות חברות": 3,
      "חברות מבוקשות באותה כיתה": position % 4 === 0 ? 1 : 2,
      "חברות הדדיות באותה כיתה": position % 5 === 0 ? 0 : 1,
      "לפחות חברה הדדית אחת": position % 5 !== 0,
      "אזהרות": position === 7 && (classNumber === 2 || classNumber === 5) ? "מענה חברתי נמוך" : "",
    };
  });
}

const CLASS_REVIEW_STUDENTS = classReviewStudents();
const CLASS_REVIEW_GROUPS: ReviewGroup[] = [
  { id: "review-inclusion", label: "שילוב", hard: true, min: 1, max: 2, member_ids: CLASS_REVIEW_STUDENTS.filter((student) => student["שילוב"]).map((student) => student["מזהה"]) },
  { id: "review-hamar", label: 'ח"מ', hard: true, min: 1, max: 1, member_ids: CLASS_REVIEW_STUDENTS.filter((student) => student['ח"מ']).map((student) => student["מזהה"]) },
  { id: "review-ethiopian", label: "מוצא אתיופי", hard: true, min: 3, max: 3, member_ids: CLASS_REVIEW_STUDENTS.filter((student) => student["מוצא אתיופי"]).map((student) => student["מזהה"]) },
  { id: "review-differential", label: "דיפרנציאליות", hard: true, min: 0, max: 1, member_ids: CLASS_REVIEW_STUDENTS.filter((student) => student["דיפרנציאלית"]).map((student) => student["מזהה"]) },
  { id: "review-twins", label: "תאומות", hard: false, min: 1, max: 2, member_ids: CLASS_REVIEW_STUDENTS.filter((student) => student["מזהה"] % 19 === 0).map((student) => student["מזהה"]) },
];

const CLASS_REVIEW_METRICS: GlobalMetrics = {
  total_students: 180,
  num_classes: 6,
  class_sizes: [30, 30, 30, 30, 30, 30],
  class_size_min: 30,
  class_size_max: 30,
  class_size_spread: 0,
  academic_level_spread: 0,
  mutual_satisfied_pct: 83.3,
  two_friends_satisfied_pct: 76.7,
  satisfied_requests: 138,
  partial_requests: 31,
  unsatisfied_requests: 11,
  violations_count: 0,
  students_with_requests: 180,
  solver_status: "FEASIBLE",
  solver_wall_time: 19.8,
  objective_value: 704,
};

const SIZE_CONSTRAINT: ConstraintModel = {
  id: "c-size-1",
  type: "capacity",
  hard: true,
  args: { min: 36, max: 37, group: { kind: "all" } },
  label_hebrew: "36–37 תלמידות בכל כיתה",
  source: "builtin_default",
  active: true,
};

const INCLUSION_CONSTRAINT: ConstraintModel = {
  id: "c-inclusion-1",
  type: "capacity",
  hard: true,
  args: { min: 1, max: 2, group: { kind: "field", field: "inclusion" } },
  label_hebrew: "1–2 תלמידות שילוב בכל כיתה",
  source: "chat",
  active: true,
};

const DIFFERENTIAL_CONSTRAINT: ConstraintModel = {
  id: "c-differential-1",
  type: "capacity",
  hard: true,
  args: { min: 0, max: 1, group: { kind: "field", field: "differential" } },
  label_hebrew: "עד תלמידה דיפרנציאלית אחת בכל כיתה",
  source: "chat",
  active: true,
};

const FRIENDSHIP_CONSTRAINT: ConstraintModel = {
  id: "c-friendship-1",
  type: "friendship_objective",
  hard: false,
  args: { target_pct: 80, mutual: true },
  label_hebrew: "לפחות 80% עם בקשת חברות הדדית",
  source: "chat",
  active: true,
};

const SCHOOL_BALANCE_CONSTRAINT: ConstraintModel = {
  id: "c-school-balance-1",
  type: "balance",
  hard: false,
  args: { field: "current_school" },
  label_hebrew: "איזון בתי ספר מקור בין הכיתות",
  source: "manual",
  active: false,
};

const RULE_PREVIEW_CONSTRAINTS = [
  SIZE_CONSTRAINT,
  INCLUSION_CONSTRAINT,
  DIFFERENTIAL_CONSTRAINT,
  SEPARATE_CONSTRAINT,
  BALANCE_CONSTRAINT,
  FRIENDSHIP_CONSTRAINT,
  SCHOOL_BALANCE_CONSTRAINT,
];

const SOLVED_METRICS: GlobalMetrics = {
  total_students: 217,
  num_classes: 6,
  class_sizes: [36, 36, 36, 36, 36, 37],
  class_size_min: 36,
  class_size_max: 37,
  class_size_spread: 1,
  academic_level_spread: 2,
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
};

const SOLVED_OVERVIEW: OverviewInspectorPreview = {
  runConfig: {
    num_classes: 6,
    denominator_all_students: false,
    mutual_target_pct: 80,
    two_friends_target_pct: 70,
    time_limit_seconds: 60,
    random_seed: 42,
  },
  tallies: { diff: 5, eth: 21, incl: 12, hamar: 8 },
  memory: {
    notes: ["כללי התמיכה נשארים חובה", "חברות חשובה יותר מאיזון בית ספר מקור"],
    decisions: [
      { at: new Date().toISOString(), decision: "approved", kind: "constraint", summary: "טווח שילוב של 1–2 בכל כיתה" },
    ],
  },
  versions: {
    current: "version-3",
    items: [
      { id: "version-3", number: 3, created_at: new Date().toISOString(), reason: "שיפור המענה לבקשות חברות", mode: "solver", approved: false, is_current: true, metrics: SOLVED_METRICS, locked_count: 1, moved_students_from_previous: 9 },
      { id: "version-2", number: 2, created_at: new Date().toISOString(), reason: "ריכוך כלל השילוב ל־1–2", mode: "solver", approved: false, is_current: false, metrics: { ...SOLVED_METRICS, mutual_satisfied_pct: 81, two_friends_satisfied_pct: 68 }, locked_count: 0, moved_students_from_previous: 14 },
      { id: "version-1", number: 1, created_at: new Date().toISOString(), reason: "שיבוץ ראשוני", mode: "solver", approved: false, is_current: false, metrics: { ...SOLVED_METRICS, mutual_satisfied_pct: 78, two_friends_satisfied_pct: 64 }, locked_count: 0, moved_students_from_previous: null },
    ],
  },
};

const ROSTER_STUDENTS: StudentRecord[] = Array.from({ length: 48 }, (_, index) => ({
  student_id: index + 1,
  first_name: ["נועה", "מאיה", "יעל", "שירה", "אביגיל", "תמר", "אלה", "רוני"][index % 8],
  last_name: ["כהן", "לוי", "מזרחי", "פרץ", "אברהם", "דהן"][Math.floor(index / 8) % 6],
  current_school: `בית ספר ${(index % 7) + 1}`,
  current_class: (index % 4) + 1,
  academic_level: ["מצטיינת", "בינונית", "חלשה"][index % 3],
  ethiopian_origin: index % 9 === 0,
  inclusion: index % 11 === 0,
  hamar: index % 17 === 0,
  differential: index % 13 === 0,
  friend_requests_raw: index % 5 === 0 ? "נועה כהן, מאיה לוי" : "",
  _project_edited_fields: index === 4 || index === 19 ? ["academic_level"] : [],
}));

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
      { id: id(), kind: "data_warning", at: Date.now(), problems: [{ message: "שלוש בקשות חברות לא זוהו: \"רותם\", \"נויה כהן\" ו\"תמר\" — השם לא ברור או לא נמצא ברשימה" }] },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
  },

  "chat-error-retry": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "למה יש כיתה עם 13 תלמידות וכיתה עם 11?" },
      { id: id(), kind: "agent_steps", at: Date.now(), tools: ["get_class_sizes", "analyze_assignment_quality"] },
      { id: id(), kind: "chat_error", at: Date.now(), message: "החיבור לעוזרת נקטע לפני שהתקבלה תשובה מלאה.", retryText: "למה יש כיתה עם 13 תלמידות וכיתה עם 11?", retryable: true },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
    overviewPreview: SOLVED_OVERVIEW,
  },

  "chat-error-review": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "תזכרי שאסור לרכך את כלל השילוב" },
      { id: id(), kind: "agent_steps", at: Date.now(), tools: ["remember_project_note"] },
      { id: id(), kind: "chat_error", at: Date.now(), message: "החיבור נותק לאחר שהעוזרת התחילה לעדכן את הפרויקט.", retryText: "תזכרי שאסור לרכך את כלל השילוב", retryable: false },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
    overviewPreview: SOLVED_OVERVIEW,
  },

  "solve-error-retry": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "צרי שיבוץ לפי הכללים שסיכמנו" },
      { id: id(), kind: "solve_error", at: Date.now(), message: "החיבור למנוע השיבוץ נקטע לפני שהתקבלה תשובה.", retryable: true, completedVersions: 0 },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
    overviewPreview: SOLVED_OVERVIEW,
  },

  "solve-error-review": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "תני לי שלוש חלופות לשיבוץ" },
      { id: id(), kind: "solve_error", at: Date.now(), message: "החיבור נקטע בזמן יצירת החלופות.", retryable: false, completedVersions: 1 },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
    overviewPreview: SOLVED_OVERVIEW,
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

  "constraint-proposal-error": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "שני את כלל השילוב ל־1–2 תלמידות בכיתה" },
      {
        id: id(),
        kind: "constraint_proposal",
        at: Date.now(),
        status: "pending",
        error: "החיבור למערכת נקטע בזמן האישור.",
        proposal: { kind: "modify", summary_hebrew: "שינוי כלל השילוב מבדיוק 2 לטווח של 1–2 תלמידות בכל כיתה.", constraint: INCLUSION_CONSTRAINT },
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

  "constraint-browser": {
    timeline: [datasetReady()],
    studentCount: 217,
    constraintsSummary: { total: 7, active: 6, hard: 4, soft: 2 },
    inspectorPreview: {
      initial: { type: "constraints" },
      constraints: RULE_PREVIEW_CONSTRAINTS,
      open: true,
    },
  },

  "constraint-detail": {
    timeline: [datasetReady()],
    studentCount: 217,
    constraintsSummary: { total: 7, active: 6, hard: 4, soft: 2 },
    inspectorPreview: {
      initial: { type: "constraint", id: INCLUSION_CONSTRAINT.id },
      constraints: RULE_PREVIEW_CONSTRAINTS,
      open: true,
    },
  },

  solved: {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "הפיקי שיבוץ לפי הכללים שסיכמנו" },
      {
        id: id(),
        kind: "solve_result",
        at: Date.now(),
        metrics: SOLVED_METRICS,
      },
      { id: id(), kind: "assistant_message", at: Date.now(), text: "הכיתות כמעט זהות בגודל, וכל כללי החובה נשמרו. כדאי לעבור על שבע בקשות החברות שלא קיבלו מענה לפני הייצוא." },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
    overviewPreview: SOLVED_OVERVIEW,
  },

  "final-approved": {
    timeline: [
      datasetReady(),
      { id: id(), kind: "solve_result", at: Date.now(), version: 3, metrics: SOLVED_METRICS },
      { id: id(), kind: "final_approval", at: Date.now(), exported: true },
      { id: id(), kind: "assistant_message", at: Date.now(), text: "השיבוץ אושר ונשמר כגרסה הסופית. אפשר להוריד שוב את קובץ ה־Excel מהיסטוריית הגרסאות בכל עת." },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
    overviewPreview: {
      ...SOLVED_OVERVIEW,
      versions: {
        ...SOLVED_OVERVIEW.versions,
        items: SOLVED_OVERVIEW.versions.items.map((version) => version.id === "version-3" ? { ...version, approved: true } : version),
      },
    },
  },

  "version-restore": {
    timeline: [datasetReady()],
    studentCount: 217,
    constraintsSummary: baseCounts,
    overviewPreview: { ...SOLVED_OVERVIEW, restoreCandidate: "version-2" },
    inspectorPreview: {
      initial: { type: "overview" },
      constraints: [],
      open: true,
    },
  },

  comparison: {
    timeline: [
      datasetReady(),
      { id: id(), kind: "user_message", at: Date.now(), text: "תני יותר חשיבות לחברות ונסי שוב" },
      {
        id: id(),
        kind: "solve_result",
        at: Date.now(),
        version: 4,
        metrics: {
          total_students: 217,
          num_classes: 6,
          class_sizes: [36, 36, 36, 36, 36, 37],
          class_size_min: 36,
          class_size_max: 37,
          class_size_spread: 1,
          academic_level_spread: 2,
          mutual_satisfied_pct: 88,
          two_friends_satisfied_pct: 79,
          satisfied_requests: 103,
          partial_requests: 16,
          unsatisfied_requests: 4,
          violations_count: 0,
          students_with_requests: 123,
          solver_status: "FEASIBLE",
          solver_wall_time: 21.2,
          objective_value: 731,
        },
      },
      {
        id: id(),
        kind: "solve_comparison",
        at: Date.now(),
        fromVersion: 3,
        toVersion: 4,
        movedStudents: 14,
        before: {
          total_students: 217,
          num_classes: 6,
          class_sizes: [36, 36, 36, 36, 36, 37],
          class_size_min: 36,
          class_size_max: 37,
          class_size_spread: 1,
          academic_level_spread: 1,
          mutual_satisfied_pct: 84,
          two_friends_satisfied_pct: 73,
          satisfied_requests: 96,
          partial_requests: 19,
          unsatisfied_requests: 8,
          violations_count: 0,
          students_with_requests: 123,
          solver_status: "FEASIBLE",
          solver_wall_time: 18.4,
          objective_value: 698,
        },
        after: {
          total_students: 217,
          num_classes: 6,
          class_sizes: [36, 36, 36, 36, 36, 37],
          class_size_min: 36,
          class_size_max: 37,
          class_size_spread: 1,
          academic_level_spread: 2,
          mutual_satisfied_pct: 88,
          two_friends_satisfied_pct: 79,
          satisfied_requests: 103,
          partial_requests: 16,
          unsatisfied_requests: 4,
          violations_count: 0,
          students_with_requests: 123,
          solver_status: "FEASIBLE",
          solver_wall_time: 21.2,
          objective_value: 731,
        },
      },
      { id: id(), kind: "assistant_message", at: Date.now(), text: "גרסה 4 שיפרה את המענה החברתי, אבל הפער בהרכב הלימודי גדל מעט. כל כללי החובה עדיין מתקיימים, ולכן הבחירה תלויה בעדיפות שלך בין חברות לאיזון לימודי." },
      { id: id(), kind: "version_restore", at: Date.now(), version: 3, reason: "לפני העלאת העדיפות לחברות" },
    ],
    studentCount: 217,
    constraintsSummary: baseCounts,
    overviewPreview: SOLVED_OVERVIEW,
  },

  "class-review": {
    timeline: [datasetReady()],
    studentCount: 180,
    constraintsSummary: baseCounts,
    classReview: {
      students: CLASS_REVIEW_STUDENTS,
      constraints: [],
      numClasses: 6,
      metrics: CLASS_REVIEW_METRICS,
      reviewGroups: CLASS_REVIEW_GROUPS,
    },
  },

  "student-detail": {
    timeline: [datasetReady()],
    studentCount: 180,
    constraintsSummary: baseCounts,
    classReview: {
      students: CLASS_REVIEW_STUDENTS,
      constraints: [INCLUSION_CONSTRAINT, DIFFERENTIAL_CONSTRAINT],
      numClasses: 6,
      metrics: CLASS_REVIEW_METRICS,
      reviewGroups: CLASS_REVIEW_GROUPS,
      selectedStudentId: 44,
    },
  },

  "student-move": {
    timeline: [datasetReady()],
    studentCount: 180,
    constraintsSummary: baseCounts,
    classReview: {
      students: CLASS_REVIEW_STUDENTS,
      constraints: [INCLUSION_CONSTRAINT, DIFFERENTIAL_CONSTRAINT],
      numClasses: 6,
      metrics: CLASS_REVIEW_METRICS,
      reviewGroups: CLASS_REVIEW_GROUPS,
      selectedStudentId: 44,
      pendingClass: 5,
    },
  },

  "class-review-stale": {
    timeline: [datasetReady()],
    studentCount: 180,
    constraintsSummary: baseCounts,
    classReview: {
      students: CLASS_REVIEW_STUDENTS,
      constraints: [INCLUSION_CONSTRAINT, DIFFERENTIAL_CONSTRAINT],
      numClasses: 6,
      metrics: CLASS_REVIEW_METRICS,
      reviewGroups: CLASS_REVIEW_GROUPS,
      stale: true,
    },
  },

  "class-review-violations": {
    timeline: [datasetReady()],
    studentCount: 180,
    constraintsSummary: baseCounts,
    classReview: {
      students: CLASS_REVIEW_STUDENTS,
      constraints: [INCLUSION_CONSTRAINT, DIFFERENTIAL_CONSTRAINT],
      numClasses: 6,
      metrics: { ...CLASS_REVIEW_METRICS, violations_count: 2 },
      reviewGroups: CLASS_REVIEW_GROUPS,
      violationRows: [
        { "כלל": "עד תלמידה דיפרנציאלית אחת", "כיתה": 2, "בפועל": 2, "צפוי": "0–1" },
        { "כלל": "1–2 תלמידות שילוב", "כיתה": 5, "בפועל": 3, "צפוי": "1–2" },
      ],
    },
  },

  "class-review-approved": {
    timeline: [datasetReady()],
    studentCount: 180,
    constraintsSummary: baseCounts,
    classReview: {
      students: CLASS_REVIEW_STUDENTS,
      constraints: [INCLUSION_CONSTRAINT, DIFFERENTIAL_CONSTRAINT],
      numClasses: 6,
      metrics: CLASS_REVIEW_METRICS,
      reviewGroups: CLASS_REVIEW_GROUPS,
      approved: true,
    },
  },

  "class-review-load-error": {
    timeline: [datasetReady()],
    studentCount: 180,
    constraintsSummary: baseCounts,
    classReview: {
      students: [],
      constraints: [],
      numClasses: 6,
      metrics: CLASS_REVIEW_METRICS,
      loadError: "לא הצלחנו להתחבר לנתוני השיבוץ. הנתונים הקיימים לא שונו.",
    },
  },

  "roster-review": {
    timeline: [datasetReady()],
    studentCount: ROSTER_STUDENTS.length,
    constraintsSummary: baseCounts,
    rosterReview: ROSTER_STUDENTS,
  },

  "roster-load-error": {
    timeline: [datasetReady()],
    studentCount: ROSTER_STUDENTS.length,
    constraintsSummary: baseCounts,
    rosterError: "לא הצלחנו להתחבר לרשימת התלמידות. הקובץ שהועלה נשמר ולא נדרש להעלות אותו מחדש.",
  },

  "roster-save-error": {
    timeline: [datasetReady()],
    studentCount: ROSTER_STUDENTS.length,
    constraintsSummary: baseCounts,
    rosterReview: ROSTER_STUDENTS,
    rosterSaveError: "החיבור נותק בזמן השמירה.",
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
