"use client";

import { Icon, IconName } from "@/components/Icon";

/**
 * The first screen, and the one that decides what kind of product this is.
 *
 * What was here before was a dropzone: no file, no app. That put the work in
 * the wrong order, because the decisions -- how many classes, what has to be
 * kept apart, what merely matters -- are what determine which columns the
 * spreadsheet needs in the first place. A counselor who builds the file
 * first has already guessed at all of them.
 *
 * So there are two doors, and the left one is deliberately the larger:
 * plan first and let the file follow, or upload a file you already have.
 * Both land in the same workspace.
 */
const STEPS: { icon: IconName; title: string; body: string }[] = [
  {
    icon: "sparkle",
    title: "מחליטים מה חשוב",
    body: "נחליט לכמה כיתות לחלק, מה חייב להישמר ומה בגדר העדפה. אני אציע — ואתם תחליטו.",
  },
  {
    icon: "file",
    title: "מכינים את הקובץ",
    body: "לפי ההחלטות שלנו אכין רשימה ברורה של העמודות שצריך למלא באקסל.",
  },
  {
    icon: "grid",
    title: "מפיקים ובודקים",
    body: "אפיק את השיבוץ, אציג את התוצאות ואעזור לבדוק חלופות ולשנות כללים לפי הצורך.",
  },
];

export default function Welcome({ onPlan, onUpload }: { onPlan: () => void; onUpload: () => void }) {
  return (
    <div className="ws-welcome">
      <div className="ws-welcome-inner">
        <div className="ws-welcome-head">
          <h1>שיבוץ תלמידות לכיתות</h1>
          <p>
            אפשר להעלות קובץ קיים ולהתחיל מיד, או לתכנן איתי קודם את הכללים ואת המידע שנצטרך.
            בכל דרך שתבחרו, נתקדם יחד עד לשיבוץ שאפשר להבין ולבדוק.
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

        <div className="ws-welcome-doors">
          <button type="button" className="ws-door primary" onClick={onPlan}>
            <span className="ico" aria-hidden>
              <Icon name="sparkle" size={18} />
            </span>
            <span className="t">בואו נתכנן יחד</span>
            <span className="b">מתחילים בשיחה. אין צורך בקובץ בשלב הזה.</span>
          </button>

          <button type="button" className="ws-door" onClick={onUpload}>
            <span className="ico" aria-hidden>
              <Icon name="upload" size={18} />
            </span>
            <span className="t">יש לי כבר קובץ</span>
            <span className="b">מעלים אקסל עם רשימת התלמידות וממשיכים משם.</span>
          </button>
        </div>

        <p className="ws-welcome-foot">אפשר להעלות קובץ גם בהמשך, אחרי שנסיים לתכנן.</p>
      </div>
    </div>
  );
}
