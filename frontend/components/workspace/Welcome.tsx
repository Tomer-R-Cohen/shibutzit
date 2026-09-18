"use client";

import { Icon, IconName } from "@/components/Icon";

/**
 * The first screen, and the one that decides what kind of product this is.
 *
 * Upload is the primary path. Planning without a file remains available for
 * schools that are still preparing their roster, but it is intentionally a
 * quiet secondary action rather than a competing product mode.
 */
const STEPS: { icon: IconName; title: string; body: string }[] = [
  {
    icon: "upload",
    title: "מעלים את רשימת התלמידות",
    body: "אזהה את העמודות, בקשות החברות והמידע החסר ואציג מה הבנתי.",
  },
  {
    icon: "sparkle",
    title: "אומרים מה חשוב",
    body: "כותבים בשפה חופשית. כל שינוי בכלל חובה יוצג לאישור לפני שייכנס לתוקף.",
  },
  {
    icon: "grid",
    title: "בודקים ומאשרים שיבוץ",
    body: "מקבלים תמונת מצב ברורה, משווים חלופות ומייצאים רק כשמרוצים.",
  },
];

export default function Welcome({ onPlan, onUpload }: { onPlan: () => void; onUpload: () => void }) {
  return (
    <div className="ws-welcome">
      <div className="ws-welcome-inner">
        <div className="ws-welcome-head">
          <h1>שיבוץ תלמידות לכיתות</h1>
          <p>
            מעלים אקסל, מספרים מה חשוב, ומקבלים שיבוץ מאוזן שאפשר להבין, לבדוק ולשנות.
          </p>
        </div>

        <ol className="ws-welcome-steps">
          {STEPS.map((s, i) => (
            <li key={s.title} className="ws-welcome-step">
              <span className="num" aria-hidden>
                {i + 1}
              </span>
              <span className="ico" aria-hidden>
                <Icon name={s.icon} size={16} />
              </span>
              <span className="txt">
                <span className="t">{s.title}</span>
                <span className="b">{s.body}</span>
              </span>
            </li>
          ))}
        </ol>

        <div className="ws-welcome-primary">
          <button type="button" className="ws-door primary" onClick={onUpload}>
            <span className="ico" aria-hidden>
              <Icon name="upload" size={18} />
            </span>
            <span className="t">העלאת קובץ אקסל</span>
            <span className="b">המערכת תבדוק את הנתונים ותשאל רק מה שחסר.</span>
          </button>
        </div>

        <p className="ws-welcome-foot">
          עדיין אין קובץ מוכן?{" "}
          <button type="button" className="ws-link" onClick={onPlan}>אפשר לתכנן יחד קודם</button>
        </p>
      </div>
    </div>
  );
}
