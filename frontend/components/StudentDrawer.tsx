"use client";

import { useState } from "react";
import clsx from "clsx";
import { Button, StatusIndicator } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import { StudentRow, fullName } from "@/components/ClassBoard";

// A focused side panel for one student: relationship summary + explicit
// move workflow. Replaces a bottom action bar so it reads as a deliberate
// "open a record" interaction rather than a floating toolbar.
export function StudentDrawer({
  student,
  students,
  numClasses,
  onClose,
  onMove,
  onLockToggle,
}: {
  student: StudentRow;
  students: StudentRow[];
  numClasses: number;
  onClose: () => void;
  onMove: (newClass: number) => Promise<void> | void;
  onLockToggle: () => Promise<void> | void;
}) {
  const [pendingClass, setPendingClass] = useState<number | null>(null);
  const currentClass = Number(student["כיתה משובצת"]);
  const sizeOf = (cls: number) => students.filter((s) => s["כיתה משובצת"] === cls).length;

  const requested = Number(student["בקשות חברות"] ?? 0);
  const satisfiedInClass = Number(student["חברות מבוקשות באותה כיתה"] ?? 0);
  const mutualInClass = Number(student["חברות הדדיות באותה כיתה"] ?? 0);
  const elsewhere = Math.max(0, requested - satisfiedInClass);

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={`פרטי ${fullName(student)}`}>
      <button className="absolute inset-0 bg-slate-900/35" aria-label="סגור" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-sm flex-col divide-y divide-[var(--cw-line-2)] overflow-y-auto border-s border-[var(--cw-line)] bg-[var(--cw-card)] p-5 shadow-xl">
        <div className="flex items-start justify-between gap-3 pb-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--cw-ink)]">{fullName(student)}</h3>
            <p className="text-xs text-[var(--cw-ink-3)]">
              כיתה נוכחית: {currentClass}
              {student["נעולה"] ? " · נעולה" : ""}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="סגירה"
            className="-me-1.5 shrink-0 rounded-md p-1.5 text-[var(--cw-ink-3)] hover:bg-[var(--cw-line-2)] hover:text-[var(--cw-ink)]"
          >
            <Icon name="x" size={18} />
          </button>
        </div>

        <div className="py-4">
          {student["אזהרות"] ? (
            <StatusIndicator status="warning" text={String(student["אזהרות"])} />
          ) : (
            <StatusIndicator status="valid" text="ללא חריגות" />
          )}
        </div>

        {/* Social placement summary */}
        <div className="flex flex-col gap-2 py-4">
          <h4 className="text-xs font-semibold text-[var(--cw-ink-2)]">מיקום חברתי</h4>
          <ul className="flex flex-col gap-1.5 text-xs text-[var(--cw-ink-2)]">
            <li>
              בקשות חברות שהוגשו: <span className="font-medium text-[var(--cw-ink)]">{requested}</span>
            </li>
            <li>
              מומשו באותה כיתה: <span className="font-medium text-[var(--cw-ink)]">{satisfiedInClass}</span>
            </li>
            {mutualInClass > 0 && (
              <li className="text-[var(--cw-accent-strong)]">בקשה הדדית אחת לפחות מומשה בכיתה זו</li>
            )}
            {elsewhere > 0 && <li className="text-[var(--cw-warn)]">{elsewhere} בקשה/ות שובצו בכיתה אחרת</li>}
            {requested === 0 && <li className="text-[var(--cw-ink-3)]">לא נמצאו בקשות חברות עבור תלמידה זו</li>}
          </ul>
        </div>

        {/* Move workflow */}
        <div className="flex flex-col gap-2 py-4">
          <h4 className="text-xs font-semibold text-[var(--cw-ink-2)]">העברת תלמידה</h4>
          {pendingClass == null ? (
            <div className="flex flex-wrap gap-1.5">
              {Array.from({ length: numClasses }, (_, i) => i + 1).map((c) => (
                <button
                  key={c}
                  disabled={c === currentClass}
                  onClick={() => setPendingClass(c)}
                  className="rounded-md border border-[var(--cw-line)] px-2.5 py-1 text-xs font-medium text-[var(--cw-ink)] hover:bg-[var(--cw-accent-tint)] hover:text-[var(--cw-accent-strong)] disabled:opacity-40"
                >
                  כיתה {c} ({sizeOf(c)})
                </button>
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-2 border-s-2 border-[var(--cw-accent)] ps-3 text-xs">
              <div className={clsx("font-medium", "text-[var(--cw-ink)]")}>תצוגה מקדימה של השפעה</div>
              <div>
                כיתה {pendingClass}: {sizeOf(pendingClass)} → {sizeOf(pendingClass) + 1} תלמידות
              </div>
              <div>
                כיתה {currentClass}: {sizeOf(currentClass)} → {sizeOf(currentClass) - 1} תלמידות
              </div>
              <div className="mt-1 flex gap-2">
                <Button
                  size="sm"
                  onClick={async () => {
                    await onMove(pendingClass);
                    setPendingClass(null);
                  }}
                >
                  אשר מעבר
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setPendingClass(null)}>
                  ביטול
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="pt-4">
          <Button size="sm" variant={student["נעולה"] ? "danger" : "secondary"} onClick={onLockToggle}>
            {student["נעולה"] ? "בטל נעילה" : "נעל תלמידה לכיתה הנוכחית"}
          </Button>
        </div>
      </div>
    </div>
  );
}
