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
    primary: "bg-[var(--cw-accent)] text-white shadow-[0_2px_6px_color-mix(in_srgb,var(--cw-accent)_12%,transparent)] hover:bg-[var(--cw-accent-strong)] disabled:bg-[var(--cw-line)] disabled:text-[var(--cw-ink-3)] disabled:shadow-none",
    secondary: "bg-[var(--cw-card)] text-[var(--cw-ink)] border border-[var(--cw-line)] shadow-[0_1px_2px_rgba(22,32,51,0.04)] hover:bg-[var(--cw-panel)] hover:border-[color-mix(in_srgb,var(--cw-accent)_18%,var(--cw-line))]",
    ghost: "bg-transparent text-[var(--cw-ink-2)] hover:bg-[var(--cw-line-2)] hover:text-[var(--cw-ink)]",
    danger: "bg-[var(--cw-crit)] text-white hover:opacity-90",
  };
  const sizes: Record<string, string> = { sm: "px-2.5 py-1 text-sm", md: "px-4 py-2 text-sm" };
  return (
    <button
      className={clsx(
        "rounded-xl font-medium transition-[background-color,border-color,color,box-shadow,transform] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60 disabled:active:scale-100",
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
      <h3 className="text-sm font-semibold text-[var(--cw-ink)]">{title}</h3>
      {description && <p className="max-w-md text-sm text-[var(--cw-ink-3)]">{description}</p>}
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
  return <div className="border-e-2 border-[var(--cw-crit)] py-1 ps-3 text-sm text-[var(--cw-crit)]">{message}</div>;
}

export function InfoBanner({ message, tone = "info" }: { message: string; tone?: "info" | "success" | "warning" }) {
  const tones: Record<string, string> = {
    info: "border-[var(--cw-line)] text-[var(--cw-ink-2)]",
    success: "border-[var(--cw-good)] text-[var(--cw-good)]",
    warning: "border-[var(--cw-warn)] text-[var(--cw-warn)]",
  };
  if (!message) return null;
  return <div className={clsx("border-e-2 py-1 ps-3 text-sm", tones[tone])}>{message}</div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("cw-skel", className)} />;
}

const STATUS_STYLES: Record<"blocking" | "warning" | "valid" | "info", { label: string; dot: string; text: string }> = {
  blocking: { label: "חוסם", dot: "bg-[var(--cw-crit)]", text: "text-[var(--cw-crit)]" },
  warning: { label: "דורש בדיקה", dot: "bg-[var(--cw-warn)]", text: "text-[var(--cw-warn)]" },
  valid: { label: "תקין", dot: "bg-[var(--cw-good)]", text: "text-[var(--cw-good)]" },
  info: { label: "מידע", dot: "bg-[var(--cw-ink-3)]", text: "text-[var(--cw-ink-2)]" },
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
    neutral: "bg-[var(--cw-accent)]",
    success: "bg-[var(--cw-good)]",
    warning: "bg-[var(--cw-warn)]",
    danger: "bg-[var(--cw-crit)]",
  };
  return (
    <div title={hint} className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="truncate text-[var(--cw-ink-2)]">{label}</span>
        <span className="shrink-0 font-semibold text-[var(--cw-ink)]">{displayValue ?? `${Math.round(pct)}%`}</span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-[var(--cw-line-2)]">
        <div className={clsx("h-full rounded-full motion-safe:transition-all motion-safe:duration-500", barTone[tone])} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function StatTile({ label, value, tone = "neutral" }: { label: string; value: ReactNode; tone?: "neutral" | "success" | "warning" }) {
  const textTones: Record<string, string> = {
    neutral: "text-[var(--cw-ink)]",
    success: "text-[var(--cw-good)]",
    warning: "text-[var(--cw-warn)]",
  };
  return (
    <div className="flex items-baseline gap-2 border-e border-[var(--cw-line)] pe-4 last:border-e-0 lg:flex-col lg:gap-0">
      <div className="text-xs whitespace-nowrap text-[var(--cw-ink-2)]">{label}</div>
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
        <thead className="sticky top-0 bg-[var(--cw-card)]">
          <tr>
            {columns.map((c) => (
              <th key={c} className="whitespace-nowrap border-b border-[var(--cw-line)] px-3 py-2 font-medium text-[var(--cw-ink-3)]">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="cw-divide">
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className="whitespace-nowrap px-3 py-1.5 text-[var(--cw-ink-2)]">
                  {formatCell(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <div className="p-6 text-center text-sm text-[var(--cw-ink-3)]">אין נתונים להצגה</div>}
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "כן" : "לא";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
