"use client";

import { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

export function Button({
  className,
  variant = "primary",
  size = "md",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}) {
  const variants: Record<string, string> = {
    primary: "bg-teal-600 text-white hover:bg-teal-700 disabled:bg-slate-300",
    secondary: "bg-slate-100 text-slate-800 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100",
    ghost: "bg-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
    danger: "bg-rose-600 text-white hover:bg-rose-700",
  };
  const sizes: Record<string, string> = { sm: "px-2.5 py-1 text-sm", md: "px-4 py-2 text-sm" };
  return (
    <button
      className={clsx(
        "rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        variants[variant],
        sizes[size],
        className
      )}
      {...rest}
    />
  );
}

export function EmptyState({
  title,
  description,
  actionHref,
  actionLabel,
}: {
  title: string;
  description?: string;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-2 py-14 text-center">
      <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
      {description && <p className="max-w-md text-sm text-slate-400">{description}</p>}
      {actionHref && actionLabel && (
        <a href={actionHref}>
          <Button className="mt-2" size="sm">
            {actionLabel}
          </Button>
        </a>
      )}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  if (!message) return null;
  return <div className="border-e-2 border-rose-500 py-1 ps-3 text-sm text-rose-700">{message}</div>;
}

export function InfoBanner({ message, tone = "info" }: { message: string; tone?: "info" | "success" | "warning" }) {
  const tones: Record<string, string> = {
    info: "border-slate-300 text-slate-600",
    success: "border-emerald-500 text-emerald-700",
    warning: "border-amber-500 text-amber-700",
  };
  if (!message) return null;
  return <div className={clsx("border-e-2 py-1 ps-3 text-sm", tones[tone])}>{message}</div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("motion-safe:animate-pulse rounded-md bg-slate-200 dark:bg-slate-800", className)} />;
}

const STATUS_STYLES: Record<"blocking" | "warning" | "valid" | "info", { label: string; dot: string; text: string }> = {
  blocking: { label: "חוסם", dot: "bg-rose-500", text: "text-rose-700" },
  warning: { label: "דורש בדיקה", dot: "bg-amber-500", text: "text-amber-700" },
  valid: { label: "תקין", dot: "bg-emerald-500", text: "text-emerald-700" },
  info: { label: "מידע", dot: "bg-slate-400", text: "text-slate-600" },
};

// Plain text + a small dot — status is always readable without the dot,
// the dot is a secondary, non-color-only-dependent cue.
export function StatusIndicator({
  status,
  text,
}: {
  status: "blocking" | "warning" | "valid" | "info";
  text?: string;
}) {
  const s = STATUS_STYLES[status];
  return (
    <span className={clsx("inline-flex items-center gap-1.5 text-xs font-medium", s.text)}>
      <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", s.dot)} aria-hidden />
      {text ?? s.label}
    </span>
  );
}

export function ProgressTrack({
  label,
  value,
  max = 100,
  displayValue,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: number;
  max?: number;
  displayValue?: string;
  tone?: "neutral" | "success" | "warning" | "danger";
  hint?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const barTone: Record<string, string> = {
    neutral: "bg-teal-600",
    success: "bg-emerald-500",
    warning: "bg-amber-500",
    danger: "bg-rose-500",
  };
  return (
    <div title={hint} className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="truncate text-slate-500">{label}</span>
        <span className="shrink-0 font-semibold text-slate-800">{displayValue ?? `${Math.round(pct)}%`}</span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-slate-100">
        <div className={clsx("h-full rounded-full motion-safe:transition-all motion-safe:duration-500", barTone[tone])} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function StatTile({ label, value, tone = "neutral" }: { label: string; value: ReactNode; tone?: "neutral" | "success" | "warning" }) {
  const textTones: Record<string, string> = {
    neutral: "text-slate-800",
    success: "text-emerald-700",
    warning: "text-amber-700",
  };
  return (
    <div className="flex items-baseline gap-2 border-e border-slate-200 pe-4 last:border-e-0 lg:flex-col lg:gap-0">
      <div className="text-xs whitespace-nowrap text-slate-500">{label}</div>
      <div className={clsx("text-lg font-semibold tabular-nums", textTones[tone])}>{value}</div>
    </div>
  );
}

export function SimpleTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
}) {
  return (
    <div className="max-h-[520px] overflow-auto">
      <table className="w-full min-w-max text-right text-sm">
        <thead className="sticky top-0 bg-white">
          <tr>
            {columns.map((c) => (
              <th key={c} className="whitespace-nowrap border-b border-slate-200 px-3 py-2 font-medium text-slate-500">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className="whitespace-nowrap px-3 py-1.5 text-slate-700">
                  {formatCell(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <div className="p-6 text-center text-sm text-slate-400">אין נתונים להצגה</div>}
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "כן" : "לא";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
