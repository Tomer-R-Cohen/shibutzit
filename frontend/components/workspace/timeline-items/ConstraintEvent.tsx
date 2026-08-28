import { Icon, IconName } from "@/components/Icon";
import { formatTime } from "./shared";

const ICONS: Record<"applied" | "modified" | "removed", IconName> = { applied: "check", modified: "edit", removed: "x" };

export function ConstraintEvent({ action, label, at }: { action: "applied" | "modified" | "removed"; label: string; at: number }) {
  return (
    <div className="ws-event ws-event-boxed">
      <Icon name={ICONS[action]} size={12} />
      <span>{label}</span>
      <span className="ws-event-time cw-num">{formatTime(at)}</span>
    </div>
  );
}
