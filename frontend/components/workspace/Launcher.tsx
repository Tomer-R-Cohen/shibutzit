"use client";

import { Icon, IconName } from "@/components/Icon";

/**
 * The first-run surface, shown while the timeline is empty.
 *
 * What was here before was an avatar and one italic example sentence on an
 * otherwise blank canvas. That is a dead end: the roster is already loaded
 * at this point, the composer accepts free text, and nothing on screen tells
 * a teacher what kinds of things this thing actually understands. The four
 * openings below are one per rule family the backend can model, so reading
 * them is also how you learn the product's range.
 *
 * They fill the composer rather than sending, which keeps the same
 * confirm-before-anything-happens contract the rest of the workspace uses:
 * every rule still passes through the user's own hands before it lands.
 */
const OPENINGS: { icon: IconName; text: string }[] = [
  { icon: "users", text: "שרה כהן ומיכל לוי לא ישובצו יחד" },
  { icon: "heart", text: "חשוב שלכל תלמידה תהיה לפחות חברה אחת בכיתה" },
  { icon: "sliders", text: "לאזן את רמות הלימוד בין הכיתות" },
  { icon: "grid", text: "לחלק את התלמידות לשש כיתות" },
];

// Planning has no roster, so the openings are about deciding rather than
// about specific students -- and every one of them is a question this agent
// can now actually act on (set_class_count, note_required_data, propose_*).
const PLANNING_OPENINGS: { icon: IconName; text: string }[] = [
  { icon: "grid", text: "לכמה כיתות כדאי לחלק שכבה של 220 תלמידות?" },
  { icon: "sparkle", text: "מה כדאי לקחת בחשבון כשמחלקים שכבה לכיתות?" },
  { icon: "users", text: "חשוב לי שתאומות לא יהיו באותה כיתה" },
  { icon: "file", text: "אילו עמודות אני צריכה להכין באקסל?" },
];

export default function Launcher({
  studentCount,
  hasDataset = true,
  onPick,
}: {
  studentCount: number | null;
  hasDataset?: boolean;
  onPick: (text: string) => void;
}) {
  const openings = hasDataset ? OPENINGS : PLANNING_OPENINGS;
  return (
    <div className="ws-launcher">
      <div className="ws-launcher-head">
        <h1 className="ws-launcher-title">{hasDataset ? "מה חשוב לכם בשיבוץ?" : "בואו נתכנן את השיבוץ"}</h1>
        <p className="ws-launcher-sub">
          {hasDataset
            ? `${studentCount != null ? `${studentCount} תלמידות נקלטו. ` : ""}כתבו לי מה חשוב לכם בשפה חופשית. אנסח כל כלל כהצעה ואחכה לאישורכם לפני שאחיל אותו.`
            : "אין צורך בקובץ עדיין. נגדיר יחד את מספר הכיתות ועקרונות השיבוץ, ובהמשך אכין רשימת נתונים להשלמה."}
        </p>
      </div>

      <div>
        <div className="ws-launcher-label">נסו למשל</div>
        <div className="ws-launcher-list">
          {openings.map((o) => (
            <button key={o.text} type="button" className="ws-launcher-row" onClick={() => onPick(o.text)}>
              <span className="ico" aria-hidden>
                <Icon name={o.icon} size={15} />
              </span>
              <span className="txt">{o.text}</span>
              <Icon name="chevron" size={14} className="ws-chev" />
            </button>
          ))}
        </div>
      </div>

      <p className="ws-launcher-hint">
        <kbd>Enter</kbd> לשליחה · <kbd>Shift</kbd>+<kbd>Enter</kbd> לשורה חדשה
      </p>
    </div>
  );
}
