"use client";

import { useState } from "react";
import clsx from "clsx";
import { Button, StatusIndicator } from "@/components/ui/primitives";
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
      <button className="absolute inset-0 bg-slate-900/20" aria-label="סגור" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-sm flex-col divide-y divide-slate-100 overflow-y-auto border-s border-slate-200 bg-white p-5">
        <div className="flex items-start justify-between pb-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">{fullName(student)}</h3>
            <p className="text-xs text-slate-400">
              כיתה נוכחית: {currentClass}
              {student["נעולה"] ? " · נעולה" : ""}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}>
            סגירה
          </Button>
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
          <h4 className="text-xs font-semibold text-slate-600">מיקום חברתי</h4>
          <ul className="flex flex-col gap-1.5 text-xs text-slate-600">
            <li>
              בקשות חברות שהוגשו: <span className="font-medium text-slate-800">{requested}</span>
            </li>
            <li>
              מומשו באותה כיתה: <span className="font-medium text-slate-800">{satisfiedInClass}</span>
            </li>
            {mutualInClass > 0 && (
              <li className="text-teal-700">בקשה הדדית אחת לפחות מומשה בכיתה זו</li>
            )}
            {elsewhere > 0 && <li className="text-amber-700">{elsewhere} בקשה/ות שובצו בכיתה אחרת</li>}
            {requested === 0 && <li className="text-slate-400">לא נמצאו בקשות חברות עבור תלמידה זו</li>}
          </ul>
        </div>

        {/* Move workflow */}
        <div className="flex flex-col gap-2 py-4">
          <h4 className="text-xs font-semibold text-slate-600">העברת תלמידה</h4>
          {pendingClass == null ? (
            <div className="flex flex-wrap gap-1.5">
              {Array.from({ length: numClasses }, (_, i) => i + 1).map((c) => (
                <button
                  key={c}
                  disabled={c === currentClass}
                  onClick={() => setPendingClass(c)}
                  className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-teal-50 hover:text-teal-700 disabled:opacity-40"
                >
                  כיתה {c} ({sizeOf(c)})
                </button>
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-2 border-s-2 border-teal-600 ps-3 text-xs">
              <div className={clsx("font-medium", "text-slate-700")}>תצוגה מקדימה של השפעה</div>
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
