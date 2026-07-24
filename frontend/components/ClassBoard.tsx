// Shared student row type + helpers, used by the Class Wall and the student
// drawer. (The original dot-strip board component was replaced by ClassWall;
// this file is kept as the canonical type source it exported.)

export interface StudentRow {
  "מזהה": number;
  "שם פרטי"?: string;
  "שם משפחה"?: string;
  "כיתה משובצת": number | null;
  "ביה\"ס נוכחי"?: string;
  "הישגים לימודיים"?: string;
  "מוצא אתיופי"?: boolean;
  "שילוב"?: boolean;
  'ח"מ'?: boolean;
  "דיפרנציאלית"?: boolean;
  "נעולה"?: boolean;
  "בקשות חברות"?: number;
  "חברות מבוקשות באותה כיתה"?: number;
  "חברות הדדיות באותה כיתה"?: number;
  "לפחות חברה הדדית אחת"?: boolean;
  "אזהרות"?: string;
  [key: string]: unknown;
}

export type CategoryKey = "מוצא אתיופי" | "שילוב" | 'ח"מ' | "דיפרנציאלית";

export function fullName(s: StudentRow) {
  const first = (s["שם פרטי"] ?? "").toString().trim();
  const last = (s["שם משפחה"] ?? "").toString().trim();
  return `${first} ${last}`.trim() || `תלמידה #${s["מזהה"]}`;
}
