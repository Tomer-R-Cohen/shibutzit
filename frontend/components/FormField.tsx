"use client";

export function NumberField({
  label,
  value,
  onChange,
  min = 0,
  step = 1,
  compact = false,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  step?: number;
  /** Inline label + narrow input, for packing several onto one row. */
  compact?: boolean;
}) {
  if (compact) {
    return (
      <label className="flex items-center gap-1.5 text-xs text-slate-500">
        {label && <span>{label}</span>}
        <input
          type="number"
          min={min}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-14 rounded border border-slate-300 px-1.5 py-1 text-sm text-slate-800 tabular-nums"
        />
      </label>
    );
  }
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-600">{label}</span>
      <input
        type="number"
        min={min}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded-md border border-slate-300 px-2 py-1.5"
      />
    </label>
  );
}

export function CheckboxField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function SliderField({
  label,
  value,
  onChange,
  min = 0,
  max = 10,
  step = 0.5,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="flex justify-between text-slate-600 dark:text-slate-300">
        <span>{label}</span>
        <span className="font-mono text-xs">{value}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="accent-teal-600"
      />
    </label>
  );
}
