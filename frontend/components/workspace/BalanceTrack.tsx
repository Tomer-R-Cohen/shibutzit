// The product's signature motif: a value sitting at a position on a track
// (━━━━●━━). Used anywhere a "how balanced is this" figure appears, so the
// same shape means the same thing everywhere -- rather than inventing a new
// chart per surface. RangeBar (a min..max *span*) is the sibling shape and
// shares the same track geometry/tokens; the two are deliberately distinct
// because one shows a point and the other a bound.
export function BalanceTrack({ value, max = 100, emphasised = false }: { value: number; max?: number; emphasised?: boolean }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <span className={`ws-track${emphasised ? " emphasised" : ""}`} aria-hidden>
      <span className="ws-track-fill" style={{ width: `${pct}%` }} />
      <span className="ws-track-dot" style={{ insetInlineStart: `${pct}%` }} />
    </span>
  );
}
