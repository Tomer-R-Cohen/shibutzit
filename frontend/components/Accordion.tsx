"use client";

import { ReactNode } from "react";
import clsx from "clsx";

export function AccordionSection({
  index,
  title,
  summary,
  done,
  disabled,
  open,
  onToggle,
  children,
}: {
  index: number;
  title: string;
  summary?: string;
  done: boolean;
  disabled?: boolean;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="py-3 first:pt-0">
      <button
        type="button"
        disabled={disabled}
        onClick={onToggle}
        className={clsx(
          "flex w-full items-center gap-3 py-1 text-right",
          disabled ? "cursor-not-allowed opacity-40" : "hover:text-slate-900"
        )}
      >
        <span className={clsx("text-xs font-semibold tabular-nums", done ? "text-emerald-600" : open ? "text-teal-600" : "text-slate-400")}>
          {done ? "✓" : index}
        </span>
        <span className="flex-1 text-sm font-semibold text-slate-800">{title}</span>
        {!open && summary && <span className="max-w-[45%] truncate text-xs text-slate-400">{summary}</span>}
        <span className={clsx("text-slate-300 motion-safe:transition-transform", open && "rotate-180")} aria-hidden>
          ⌄
        </span>
      </button>
      {open && <div className="pt-3 ps-6">{children}</div>}
    </div>
  );
}
