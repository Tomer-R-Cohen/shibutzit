"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Hand-rolled count-up (no framer-motion for one effect). Animates *from
 * whatever was last shown* to the new value, so a re-solve reads as
 * "91 → 89" rather than snapping back to 0 and recounting -- that
 * continuity is what makes a changed number feel like a state change
 * instead of a refresh. Respects prefers-reduced-motion.
 */
export function CountUp({ value, durationMs = 700 }: { value: number; durationMs?: number }) {
  const [display, setDisplay] = useState(() =>
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches ? value : 0
  );
  const [changed, setChanged] = useState(false);
  // The value we're animating away from -- a ref so starting a new
  // animation doesn't itself retrigger the effect.
  const fromRef = useRef(display);
  const firstRef = useRef(true);

  useEffect(() => {
    const from = fromRef.current;
    if (from === value) return;

    // Reduced motion collapses the duration to zero rather than taking a
    // separate synchronous path, so there is exactly one setState site
    // (inside rAF) regardless of preference.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const duration = reduced ? 0 : durationMs;

    // Flag a *change* (not the initial mount count-up) so the number can
    // briefly mark itself as updated.
    const isUpdate = !firstRef.current && !reduced;
    firstRef.current = false;

    const start = performance.now();
    let raf: number;
    function tick(now: number) {
      const t = duration === 0 ? 1 : Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const next = Math.round(from + (value - from) * eased);
      setDisplay(next);
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        fromRef.current = value;
        if (isUpdate) {
          setChanged(true);
          window.setTimeout(() => setChanged(false), 900);
        }
      }
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, durationMs]);

  return <span className={changed ? "ws-metric-changed" : undefined}>{display}</span>;
}
