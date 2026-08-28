import { CSSProperties } from "react";

// Small, consistent stroke-icon set (Lucide-style, 24px grid, 1.75 stroke) to
// replace emoji — emoji render inconsistently across platforms and read as
// unpolished in a professional tool.
const PATHS: Record<string, { d: string; fill?: boolean }> = {
  search: { d: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM21 21l-4.35-4.35" },
  edit: { d: "M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" },
  file: { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6" },
  upload: { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 9l5-5 5 5M12 4v12" },
  download: { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" },
  lock: { d: "M5 11a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2ZM8 9V7a4 4 0 0 1 8 0v2" },
  warning: { d: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0ZM12 9v4M12 17h.01" },
  heart: { d: "M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1-1.1a5.5 5.5 0 1 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z", fill: true },
  check: { d: "M20 6 9 17l-5-5" },
  x: { d: "M18 6 6 18M6 6l12 12" },
  chevron: { d: "M6 9l6 6 6-6" },
  send: { d: "M4.5 12 20 4l-6.5 16-2.5-7-6.5-1Z" },
  "arrow-up-right": { d: "M7 17 17 7M8 7h9v9" },
  sparkle: { d: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18" },
  list: { d: "M4 6h16M4 12h16M4 18h16" },
  grid: { d: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" },
  users: { d: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" },
  plus: { d: "M12 5v14M5 12h14" },
  minus: { d: "M5 12h14" },
  sliders: { d: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h10M18 18h2M14 4v4M8 10v4M14 16v4" },
};

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  size = 16,
  className,
  style,
  strokeWidth = 1.75,
}: {
  name: IconName;
  size?: number;
  className?: string;
  style?: CSSProperties;
  strokeWidth?: number;
}) {
  const p = PATHS[name];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={p.fill ? "currentColor" : "none"}
      stroke={p.fill ? "none" : "currentColor"}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={style}
      aria-hidden
      focusable={false}
    >
      <path d={p.d} />
    </svg>
  );
}
