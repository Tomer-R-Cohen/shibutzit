"use client";

import { useEffect, useId, useRef, useState } from "react";
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
  onAskAI,
  busy = false,
  initialPendingClass,
}: {
  student: StudentRow;
  students: StudentRow[];
  numClasses: number;
  onClose: () => void;
  onMove: (newClass: number) => Promise<void> | void;
  onLockToggle: () => Promise<void> | void;
  onAskAI?: (message: string) => void;
  busy?: boolean;
  /** Development-only initial state for deterministic rendered audits. */
  initialPendingClass?: number;
}) {
  const [pendingClass, setPendingClass] = useState<number | null>(initialPendingClass ?? null);
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const currentClass = Number(student["כיתה משובצת"]);
  const locked = Boolean(student["נעולה"]);
  const sizeOf = (cls: number) => students.filter((s) => s["כיתה משובצת"] === cls).length;

  const requested = Number(student["בקשות חברות"] ?? 0);
  const satisfiedInClass = Number(student["חברות מבוקשות באותה כיתה"] ?? 0);
  const mutualInClass = Number(student["חברות הדדיות באותה כיתה"] ?? 0);
  const elsewhere = Math.max(0, requested - satisfiedInClass);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      previousFocus?.focus();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={busy}>
      <div className="absolute inset-0 bg-slate-900/35" aria-hidden="true" onClick={onClose} />
      <div ref={panelRef} className="student-drawer relative flex h-full w-full max-w-sm flex-col overflow-y-auto border-s border-[var(--cw-line)] bg-[var(--cw-card)] p-5 shadow-xl">
        <div className="student-drawer-head flex items-start justify-between gap-3 pb-4">
          <div>
            <span className="student-drawer-kicker">תיק תלמידה</span>
            <h3 id={titleId}>{fullName(student)}</h3>
            <div className="student-drawer-meta">
              <span>כיתה {currentClass}</span>
              {student['ביה"ס נוכחי'] && <span>{String(student['ביה"ס נוכחי'])}</span>}
              {student["הישגים לימודיים"] && <span>{String(student["הישגים לימודיים"])}</span>}
            </div>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            aria-label="סגירה"
            className="-me-1.5 shrink-0 rounded-md p-1.5 text-[var(--cw-ink-3)] hover:bg-[var(--cw-line-2)] hover:text-[var(--cw-ink)]"
          >
            <Icon name="x" size={18} />
          </button>
        </div>

        <div className="student-drawer-status py-4">
          {student["אזהרות"] ? (
            <StatusIndicator status="warning" text={String(student["אזהרות"])} />
          ) : (
            <StatusIndicator status="valid" text="לא זוהתה נקודה שדורשת בדיקה" />
          )}
        </div>

        {/* Social placement summary */}
        <div className="student-drawer-section">
          <div className="student-drawer-section-head">
            <h4>מענה חברתי</h4>
            {requested > 0 && <span>{Math.round((satisfiedInClass / requested) * 100)}%</span>}
          </div>
          <div className="student-social-metrics">
            <div><strong>{requested}</strong><span>בקשות</span></div>
            <div><strong>{satisfiedInClass}</strong><span>בכיתה</span></div>
            <div><strong>{mutualInClass}</strong><span>הדדיות</span></div>
          </div>
          <ul className="student-drawer-notes">
            {mutualInClass > 0 && (
              <li className="text-[var(--cw-accent-strong)]">לפחות בקשה הדדית אחת קיבלה מענה</li>
            )}
            {elsewhere > 0 && (
              <li className="text-[var(--cw-warn)]">
                {elsewhere === 1 ? "בקשה אחת לא קיבלה מענה" : `${elsewhere} בקשות לא קיבלו מענה`}
              </li>
            )}
            {requested === 0 && <li className="text-[var(--cw-ink-3)]">לא הוזנו בקשות חברות לתלמידה הזאת</li>}
          </ul>
        </div>

        {/* Move workflow */}
        <div className="student-drawer-section">
          <div className="student-drawer-section-head">
            <h4>העברה ידנית</h4>
            <span>בחירה שלכם</span>
          </div>
          {locked ? (
            <div className="flex items-start gap-2 rounded-md bg-[var(--cw-panel)] p-2.5 text-xs text-[var(--cw-ink-2)]">
              <Icon name="lock" size={14} className="mt-0.5 shrink-0" />
              כדי להעביר את התלמידה לכיתה אחרת, יש לבטל תחילה את הקיבוע הנוכחי.
            </div>
          ) : pendingClass == null ? (
            <div className="flex flex-wrap gap-1.5">
              {Array.from({ length: numClasses }, (_, i) => i + 1).map((c) => (
                <button
                  key={c}
                  disabled={c === currentClass || busy}
                  onClick={() => setPendingClass(c)}
                  className="rounded-md border border-[var(--cw-line)] px-2.5 py-1 text-xs font-medium text-[var(--cw-ink)] hover:bg-[var(--cw-accent-tint)] hover:text-[var(--cw-accent-strong)] disabled:opacity-40"
                >
                  כיתה {c} ({sizeOf(c)})
                </button>
              ))}
            </div>
          ) : (
            <div className="student-move-preview">
              <span className="student-move-draft">הצעה — טרם בוצעה</span>
              <div className={clsx("font-medium", "text-[var(--cw-ink)]")}>העברה מכיתה {currentClass} לכיתה {pendingClass}</div>
              <div className="student-move-sizes">
                <div><span>כיתה {pendingClass}</span><strong>{sizeOf(pendingClass)} → {sizeOf(pendingClass) + 1}</strong></div>
                <div><span>כיתה {currentClass}</span><strong>{sizeOf(currentClass)} → {sizeOf(currentClass) - 1}</strong></div>
              </div>
              <p>לאחר ההעברה נחשב מחדש את הכללים והאזהרות. אם תיווצר חריגה, לא ניתן יהיה לאשר את הגרסה עד לתיקונה.</p>
              {onAskAI && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => onAskAI(`מה יקרה אם אעביר את ${fullName(student)} מכיתה ${currentClass} לכיתה ${pendingClass}? בדקי כללי חובה, חברות ואיזון לפני שאחליט.`)}
                >
                  <Icon name="sparkle" size={14} /> בדיקה עם העוזרת
                </Button>
              )}
              <div className="mt-1 flex gap-2">
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={async () => {
                    await onMove(pendingClass);
                    setPendingClass(null);
                  }}
                >
                  העברה לכיתה {pendingClass}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setPendingClass(null)}>
                  ביטול
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="student-drawer-actions pt-4">
          <div className="flex flex-wrap gap-2">
            {onAskAI && (
              <Button size="sm" variant="secondary" onClick={() => onAskAI(`למה ${fullName(student)} שובצה בכיתה ${currentClass}?`)}>
                <Icon name="sparkle" size={14} /> למה היא כאן?
              </Button>
            )}
            <Button size="sm" variant={student["נעולה"] ? "danger" : "secondary"} onClick={onLockToggle} disabled={busy}>
              {student["נעולה"] ? "ביטול הקיבוע" : "קיבוע בכיתה הנוכחית"}
            </Button>
          </div>
          <p>{locked ? "הקיבוע יישמר גם בהרצות הבאות, עד שתבטלו אותו." : "קיבוע ישמור על הכיתה הנוכחית גם בהרצה הבאה."}</p>
        </div>
      </div>
    </div>
  );
}
