"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import clsx from "clsx";
import { STEPS, isStepReachable, subscribeToFlags, getFlagsSnapshot, getServerFlagsSnapshot } from "@/lib/steps";

export default function StepperShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const currentSlug = (pathname?.split("/").filter(Boolean).pop() ?? "data") as string;
  const flags = useSyncExternalStore(subscribeToFlags, getFlagsSnapshot, getServerFlagsSnapshot);

  const current = STEPS.find((s) => s.slug === currentSlug);

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 border-l border-slate-200 bg-white md:flex md:flex-col">
        <div className="flex items-center gap-2.5 px-4 py-4">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-teal-600 text-sm font-bold text-white">ז</div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-800">שיבוץ תלמידות</div>
            <div className="truncate text-xs text-slate-400">כיתות ז&apos;</div>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5 px-2" aria-label="ניווט ראשי">
          {STEPS.map((step) => {
            const reachable = isStepReachable(step.slug, flags);
            const active = step.slug === currentSlug;
            const content = (
              <div
                className={clsx(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium motion-safe:transition-colors",
                  active && "bg-teal-50 text-teal-700",
                  !active && reachable && "text-slate-600 hover:bg-slate-50",
                  !reachable && "text-slate-300 cursor-not-allowed"
                )}
              >
                <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", active ? "bg-teal-600" : reachable ? "bg-slate-300" : "bg-slate-200")} />
                {step.title}
              </div>
            );
            return reachable ? (
              <Link key={step.slug} href={`/steps/${step.slug}`}>
                {content}
              </Link>
            ) : (
              <div key={step.slug}>{content}</div>
            );
          })}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur-sm md:px-8">
          <div>
            <h1 className="text-base font-semibold text-slate-800">{current?.title ?? "שיבוץ תלמידות"}</h1>
            <p className="text-xs text-slate-400">{current?.subtitle}</p>
          </div>
        </header>
        <main className="w-full flex-1 px-4 py-5 md:px-10">{children}</main>
      </div>
    </div>
  );
}
