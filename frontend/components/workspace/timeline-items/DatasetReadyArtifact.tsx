import { Icon } from "@/components/Icon";
import type { DataProblem, RosterFocus } from "@/lib/workspace";

// Fixed dot budget per row so a 217-student class doesn't render 217 dots --
// each row is scaled proportionally to its share of the total, not a
// literal count.
const MAX_DOTS = 12;

function LevelDistribution({ levelCounts, total }: { levelCounts: Record<string, number>; total: number }) {
  const entries = Object.entries(levelCounts).filter(([, n]) => n > 0);
  if (entries.length === 0 || total === 0) return null;
  return (
    <div className="ws-dataset-levels">
      {entries.map(([level, count]) => {
        const dots = Math.max(1, Math.round((count / total) * MAX_DOTS));
        return (
          <div key={level} className="ws-dataset-level-row">
            <span className="ws-dataset-level-label">{level}</span>
            <span className="ws-dataset-level-dots" aria-hidden>
              {Array.from({ length: dots }).map((_, i) => (
                <span key={i} className="d" />
              ))}
            </span>
            <span className="ws-dataset-level-count cw-num">{count}</span>
          </div>
        );
      })}
    </div>
  );
}

export function DatasetReadyArtifact({
  studentCount,
  schoolCount,
  levelCount,
  warningCount,
  levelCounts,
  detectedFields,
  missingFields,
  friendshipCount,
  onOpenRoster,
}: {
  studentCount: number;
  schoolCount: number;
  levelCount: number;
  warningCount: number;
  levelCounts: Record<string, number>;
  detectedFields: string[];
  missingFields: string[];
  friendshipCount: number;
  onOpenRoster: () => void;
}) {
  return (
    <div className="ws-artifact ws-artifact-ok">
      <div className="ws-artifact-head">
        <Icon name="check" size={14} />
        <span>הנתונים מוכנים</span>
      </div>
      <div className="ws-artifact-stats">
        <span className="cw-num">{studentCount} תלמידות</span>
        <span className="cw-num">{schoolCount} בתי ספר</span>
        <span className="cw-num">{levelCount} רמות לימודיות</span>
      </div>
      <div className="ws-dataset-understood">
        <span className="ws-dataset-understood-label">זיהיתי בקובץ</span>
        <div className="ws-dataset-chips">
          {detectedFields.map((field) => <span key={field}>{field}</span>)}
        </div>
      </div>
      {friendshipCount > 0 && <div className="ws-artifact-note">{friendshipCount} בקשות חברות זוהו והותאמו</div>}
      <LevelDistribution levelCounts={levelCounts} total={studentCount} />
      {warningCount > 0 && <div className="ws-artifact-note">{warningCount} בקשות חברות לא זוהו בוודאות</div>}
      {missingFields.length > 0 && (
        <div className="ws-artifact-note ws-artifact-note-muted">לא נמצאו נתונים עבור: {missingFields.join(" · ")}. אפשר להמשיך בלעדיהם או להשלים בהמשך.</div>
      )}
      <div className="ws-artifact-actions">
        <button type="button" className="ws-link" onClick={onOpenRoster}>
          צפייה ברשימת התלמידות
        </button>
      </div>
    </div>
  );
}

export function DataWarningArtifact({ problems, onOpenRoster }: { problems: DataProblem[]; onOpenRoster: (focus?: RosterFocus) => void }) {
  const correctable = problems.filter((problem) => problem.field && (problem.studentIds?.length ?? 0) > 0);
  const focus: RosterFocus | undefined = correctable.length > 0
    ? {
        studentIds: [...new Set(correctable.flatMap((problem) => problem.studentIds ?? []))],
        fields: [...new Set(correctable.flatMap((problem) => problem.field ? [problem.field] : []))],
      }
    : undefined;
  return (
    <div className="ws-artifact ws-artifact-warn">
      <div className="ws-artifact-head">
        <Icon name="warning" size={14} />
        <span>נמצאו פרטים שצריך לבדוק</span>
      </div>
      <ul className="ws-artifact-list">
        {problems.map((p, i) => (
          <li key={i}>{p.message}</li>
        ))}
      </ul>
      <p className="ws-artifact-guidance">
        {focus
          ? "נפתח את התלמידות הרלוונטיות בלבד. אפשר לבחור ערך תקין או להשלים את בית הספר, והשינוי יישמר בעותק העבודה בלי לשנות את קובץ המקור."
          : "אפשר לפתוח את רשימת התלמידות כדי לבדוק ולתקן את הפרטים."}
      </p>
      <div className="ws-artifact-actions">
        <button type="button" className="ws-warning-action" onClick={() => onOpenRoster(focus)}>
          <Icon name="edit" size={14} />
          {focus ? `פתיחת ${focus.studentIds.length} התלמידות לתיקון` : "פתיחת רשימת התלמידות"}
        </button>
      </div>
    </div>
  );
}
