"use client";

import { Fragment, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { Icon } from "@/components/Icon";
import { STEPS, getFlagsSnapshot, getServerFlagsSnapshot, subscribeToFlags } from "@/lib/steps";

// A single top stepper for the three-step workflow: upload → configure →
// results. Each step shows where the user is (current) and whether that stage's
// output already exists (done ✓), so "what step am I in / what's left" is always
// answered at a glance.
export default function StepperShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const currentSlug = pathname?.split("/").filter(Boolean).pop() ?? "data";
  const flags = useSyncExternalStore(subscribeToFlags, getFlagsSnapshot, getServerFlagsSnapshot);

  return (
    <div className="cw-shell">
      <header className="cw-topbar">
        <div className="cw-brand">
          <div className="cw-brand-mark">ז</div>
          <div className="cw-brand-title">שיבוץ כיתות ז&apos;</div>
        </div>
        <nav className="cw-steps" aria-label="שלבי העבודה">
          {STEPS.map((s, i) => {
            const current = s.slug === currentSlug;
            const done = !!s.doneFlag && flags[s.doneFlag];
            // Step 1 is "done" once mapped, but flag it amber if the data still
            // has validation errors — the readiness signal must be honest.
            const warn = s.slug === "data" && done && !flags.validated;
            return (
              <Fragment key={s.slug}>
                {i > 0 && <span className="cw-step-sep" aria-hidden />}
                <Link
                  href={`/steps/${s.slug}`}
                  className={clsx("cw-step", current && "current", done && !current && "done", warn && !current && "warn")}
                  aria-current={current ? "step" : undefined}
                >
                  <span className="cw-step-badge" aria-hidden>
                    {done && !warn && !current ? <Icon name="check" size={13} /> : s.index}
                  </span>
                  <span className="cw-step-label">{s.title}</span>
                </Link>
              </Fragment>
            );
          })}
        </nav>
      </header>
      <main className="cw-main">{children}</main>
    </div>
  );
}
