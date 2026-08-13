// A bounded-range constraint drawn as a labeled bar (min ─────── max)
// rather than a sentence -- used anywhere a capacity/balance rule's shape
// needs to be scannable at a glance (solve-failure rows, rule detail).
export function RangeBar({ min, max }: { min?: number | null; max?: number | null }) {
  if (min == null && max == null) return null;
  return (
    <div className="ws-rangebar">
      <span className="ws-rangebar-num">{min ?? 0}</span>
      <span className="ws-rangebar-track" aria-hidden />
      <span className="ws-rangebar-num">{max ?? "∞"}</span>
    </div>
  );
}
