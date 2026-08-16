import { Icon } from "@/components/Icon";
import { formatTime } from "./shared";

export function ManualMoveEvent({ studentName, from, to, at }: { studentName: string; from: number; to: number; at: number }) {
  return (
    <div className="ws-event">
      <Icon name="edit" size={12} />
      <span>
        {studentName} הועברה מכיתה {from} לכיתה {to}
      </span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}

export function ReoptimizationEvent({ before, after, at }: { before?: number; after?: number; at: number }) {
  return (
    <div className="ws-event">
      <Icon name="check" size={12} />
      <span>
        בוצעה אופטימיזציה מחדש
        {before != null && after != null ? ` · ציון: ${Math.round(before)} → ${Math.round(after)}` : ""}
      </span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}
