"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { StudentRow, CategoryKey, fullName } from "@/components/ClassBoard";
import { Icon } from "@/components/Icon";
import type { ReviewGroup } from "@/lib/api";

export type { StudentRow, CategoryKey };
export { fullName };

// Column stat min/max per category (from the solver config).
export interface Thresholds {
  incl: { min: number; max: number };
  hamar: { min: number; max: number };
  eth: { min: number; max: number };
  diff: { min: number; max: number };
}

export type ClassFocus = "all" | "warnings" | "locked";

const CATS: { key: CategoryKey; field: keyof StudentRow; cls: "incl" | "hamar" | "eth" | "diff"; label: string }[] = [
  { key: "שילוב", field: "שילוב", cls: "incl", label: "שילוב" },
  { key: 'ח"מ', field: 'ח"מ', cls: "hamar", label: 'ח"מ' },
  { key: "מוצא אתיופי", field: "מוצא אתיופי", cls: "eth", label: "אתיופי" },
  { key: "דיפרנציאלית", field: "דיפרנציאלית", cls: "diff", label: "דיפרנציאלית" },
];

const LEVEL_LETTER: Record<string, string> = { "מצטיינת": "מ", "בינונית": "ב", "חלשה": "ח" };

// A full spoken description so categories/lock/warning aren't conveyed by color
// or emoji alone (WCAG 1.4.1 / 4.1.2).
function describe(s: StudentRow): string {
  const level = String(s["הישגים לימודיים"] ?? "");
  const cats = CATS.filter((c) => s[c.field]).map((c) => c.label);
  const hearts = Number(s["חברות הדדיות באותה כיתה"] ?? 0);
  return [
    fullName(s),
    s["כיתה משובצת"] != null ? `כיתה ${s["כיתה משובצת"]}` : null,
    s["ביה\"ס נוכחי"] || null,
    level || null,
    cats.length ? `קטגוריות: ${cats.join(", ")}` : null,
    hearts > 0 ? `${hearts} חברות הדדיות` : null,
    s["נעולה"] ? "נעולה" : null,
    s["אזהרות"] ? "אזהרה" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function CardInner({ s, dim, overlay }: { s: StudentRow; dim?: boolean; overlay?: boolean }) {
  const level = String(s["הישגים לימודיים"] ?? "");
  const letter = LEVEL_LETTER[level] ?? "·";
  const dots = CATS.filter((c) => s[c.field]).map((c) => <span key={c.cls} className={`cw-cdot ${c.cls}`} />);
  const hearts = Number(s["חברות הדדיות באותה כיתה"] ?? 0);
  const locked = Boolean(s["נעולה"]);
  const warn = Boolean(s["אזהרות"]);
  return (
    <div
      aria-hidden
      className={clsx("cw-card", warn && "warn", locked && "locked", dim && "dim", overlay && "ghost")}
      title={`${fullName(s)} · ${s["ביה\"ס נוכחי"] ?? ""} · ${level}`}
    >
      <span className="cw-lvl" title={level}>{letter}</span>
      <span className="cw-card-copy">
        <span className="name">{fullName(s)}</span>
        <span className="school">{String(s['ביה"ס נוכחי'] ?? "ללא בית ספר מקור")}</span>
      </span>
      <span className="cw-cdots">{dots}</span>
      <span className="cw-tail">
        {hearts > 0 && (
          <span className="hearts">
            <Icon name="heart" size={11} /> {hearts}
          </span>
        )}
        {warn && <Icon name="warning" size={12} style={{ color: "var(--cw-warn)" }} />}
        {locked && <Icon name="lock" size={11} />}
      </span>
    </div>
  );
}

function DraggableCard({ s, dim, interactionDisabled, onOpen }: { s: StudentRow; dim: boolean; interactionDisabled: boolean; onOpen: (s: StudentRow) => void }) {
  const locked = Boolean(s["נעולה"]);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: s["מזהה"], disabled: locked || interactionDisabled });
  // A pointer that moved past the drag threshold still fires a click on
  // release; remember that a drag happened so it doesn't also open the drawer.
  const wasDragged = useRef(false);
  useEffect(() => {
    if (isDragging) wasDragged.current = true;
  }, [isDragging]);
  return (
    <button
      ref={setNodeRef}
      type="button"
      className="cw-cardwrap"
      aria-label={describe(s)}
      onClick={() => {
        if (wasDragged.current) {
          wasDragged.current = false;
          return;
        }
        onOpen(s);
      }}
      {...listeners}
      {...attributes}
      tabIndex={dim ? -1 : 0}
    >
      <CardInner s={s} dim={dim} overlay={isDragging} />
    </button>
  );
}

function Column({
  c,
  members,
  avg,
  thresholds,
  categoryFilter,
  query,
  focus,
  reviewGroups,
  onAskClass,
  interactionDisabled,
  onOpen,
}: {
  c: number;
  members: StudentRow[];
  avg: number;
  thresholds: Thresholds;
  categoryFilter: CategoryKey | null;
  query: string;
  focus: ClassFocus;
  reviewGroups: ReviewGroup[];
  onAskClass?: (classNumber: number) => void;
  interactionDisabled: boolean;
  onOpen: (s: StudentRow) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `class-${c}` });
  const sizeFlag = avg > 0 && Math.abs(members.length - avg) > 1;
  const levels = ["מצטיינת", "בינונית", "חלשה"].map((level) => ({
    level,
    letter: LEVEL_LETTER[level],
    count: members.filter((member) => String(member["הישגים לימודיים"] ?? "") === level).length,
  }));
  const warningCount = members.filter((member) => Boolean(member["אזהרות"])).length;

  const fixedStats = CATS.map((cat) => {
    const n = members.filter((m) => m[cat.field]).length;
    const t = thresholds[cat.cls];
    const bad = n > t.max || (t.min > 0 && n < t.min);
    const target = t.min === t.max ? `${t.min}` : `${t.min}–${t.max}`;
    return (
      <span key={cat.cls} className={clsx("cw-stat", bad && "flag")} title={`טווח רצוי: ${target}`}>
        <span className="s-dot" style={{ background: `var(--cw-${cat.cls})` }} />
        <span>{cat.label}</span> <strong>{n}</strong>
      </span>
    );
  });
  const stats = reviewGroups.length > 0 ? reviewGroups.map((group, index) => {
    const memberIds = new Set(group.member_ids);
    const count = members.filter((member) => memberIds.has(Number(member["מזהה"]))).length;
    const outside = (group.min != null && count < group.min) || (group.max != null && count > group.max);
    const target = group.min === group.max && group.min != null
      ? `${group.min}`
      : `${group.min ?? 0}–${group.max ?? "∞"}`;
    return (
      <span
        key={group.id}
        className={clsx("cw-stat", group.hard && outside && "flag")}
        title={`${group.hard ? "חובה" : "יעד"}: ${target}`}
      >
        <span className="s-dot" style={{ background: `hsl(${(index * 67 + 202) % 360} 58% 52%)` }} />
        <span>{group.label}</span> <strong>{count}</strong>
        <em>{group.hard ? "חובה" : "יעד"}</em>
      </span>
    );
  }) : fixedStats;

  return (
    <section ref={setNodeRef} className={clsx("cw-col", isOver && "over")}>
      <header className="cw-col-head">
        <div className="cw-col-title">
          {onAskClass ? (
            <button type="button" className="name cw-ask-class" onClick={() => onAskClass(c)} title={`שאלו את העוזרת על כיתה ${c}`} aria-label={`שאלו את העוזרת על כיתה ${c}`}>
              <span>כיתה {c}</span>
              <span className="cw-ask-class-action"><Icon name="sparkle" size={11} /> ניתוח</span>
            </button>
          ) : (
            <span className="name">כיתה {c}</span>
          )}
          <span className={clsx("size cw-num", sizeFlag && "flag")}>{members.length}</span>
        </div>
        <div className="cw-col-stats">{stats}</div>
        <div className="cw-col-balance">
          <span className="cw-balance-label">הישגים</span>
          {levels.map((item) => (
            <span key={item.level} title={`${item.level}: ${item.count}`}>
              {item.letter} <strong>{item.count}</strong>
            </span>
          ))}
          {warningCount > 0 && <span className="cw-class-warning"><Icon name="warning" size={11} /> {warningCount}</span>}
        </div>
      </header>
      <div className="cw-col-body">
        {members.length === 0 ? (
          <p className="cw-col-empty">גררו לכאן תלמידה</p>
        ) : (
          members.map((s) => {
            const haystack = `${fullName(s)} ${String(s['ביה"ס נוכחי'] ?? "")}`.toLocaleLowerCase("he");
            const matchesQuery = !query || haystack.includes(query);
            const matchesFocus = focus === "all" || (focus === "warnings" ? Boolean(s["אזהרות"]) : Boolean(s["נעולה"]));
            return (
            <DraggableCard
              key={s["מזהה"]}
              s={s}
              dim={(Boolean(categoryFilter) && !s[categoryFilter as string]) || !matchesQuery || !matchesFocus}
              interactionDisabled={interactionDisabled}
              onOpen={onOpen}
            />
            );
          })
        )}
      </div>
    </section>
  );
}

export function ClassWall({
  students,
  numClasses,
  thresholds,
  categoryFilter,
  query = "",
  focus = "all",
  reviewGroups = [],
  onAskClass,
  interactionDisabled = false,
  onMove,
  onOpen,
}: {
  students: StudentRow[];
  numClasses: number;
  thresholds: Thresholds;
  categoryFilter: CategoryKey | null;
  query?: string;
  focus?: ClassFocus;
  reviewGroups?: ReviewGroup[];
  onAskClass?: (classNumber: number) => void;
  interactionDisabled?: boolean;
  onMove: (studentId: number, toClass: number) => void;
  onOpen: (s: StudentRow) => void;
}) {
  const [activeId, setActiveId] = useState<number | null>(null);
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    // Keep normal one-finger column scrolling available. A deliberate
    // short hold activates touch dragging; tolerance prevents small finger
    // movement during the hold from turning an intended scroll into a move.
    useSensor(TouchSensor, { activationConstraint: { delay: 220, tolerance: 8 } }),
    useSensor(KeyboardSensor)
  );

  const byClass = useMemo(() => {
    const map = new Map<number, StudentRow[]>();
    for (let c = 1; c <= numClasses; c++) map.set(c, []);
    for (const s of students) {
      const cls = s["כיתה משובצת"];
      if (cls == null) continue;
      if (!map.has(cls)) map.set(cls, []);
      map.get(cls)!.push(s);
    }
    return map;
  }, [students, numClasses]);

  const sizes = Array.from(byClass.values()).map((v) => v.length);
  const avg = sizes.length ? sizes.reduce((a, b) => a + b, 0) / sizes.length : 0;
  const activeStudent = activeId != null ? students.find((s) => s["מזהה"] === activeId) ?? null : null;
  const normalizedQuery = query.trim().toLocaleLowerCase("he");
  const dragAccessibility = useMemo(() => {
    const studentName = (id: string | number) => {
      const student = students.find((item) => String(item["מזהה"]) === String(id));
      return student ? fullName(student) : "התלמידה";
    };
    const targetClass = (overId: string | number | undefined) => {
      const value = String(overId ?? "");
      return value.startsWith("class-") ? Number(value.slice("class-".length)) : null;
    };
    return {
      screenReaderInstructions: {
        draggable: "כדי להתחיל העברה לחצו על מקש הרווח. עברו בין הכיתות בעזרת מקשי החצים. לחצו שוב על רווח כדי לאשר, או על Escape כדי לבטל.",
      },
      announcements: {
        onDragStart: ({ active }: DragStartEvent) => `${studentName(active.id)} נבחרה להעברה.`,
        onDragOver: ({ active, over }: DragEndEvent) => {
          const cls = targetClass(over?.id);
          return cls ? `${studentName(active.id)} מעל כיתה ${cls}.` : `${studentName(active.id)} אינה מעל כיתה.`;
        },
        onDragEnd: ({ active, over }: DragEndEvent) => {
          const cls = targetClass(over?.id);
          return cls ? `נבחרה כיתה ${cls} עבור ${studentName(active.id)}. מעדכנת את השיבוץ.` : `העברת ${studentName(active.id)} בוטלה.`;
        },
        onDragCancel: ({ active }: DragEndEvent) => `העברת ${studentName(active.id)} בוטלה.`,
      },
    };
  }, [students]);

  function handleStart(e: DragStartEvent) {
    setActiveId(Number(e.active.id));
  }
  function handleEnd(e: DragEndEvent) {
    setActiveId(null);
    const overId = e.over?.id;
    if (typeof overId !== "string" || !overId.startsWith("class-")) return;
    const target = Number(overId.slice("class-".length));
    const student = students.find((s) => s["מזהה"] === Number(e.active.id));
    if (!student || student["כיתה משובצת"] === target) return;
    onMove(Number(e.active.id), target);
  }

  return (
    <DndContext accessibility={dragAccessibility} sensors={sensors} onDragStart={handleStart} onDragEnd={handleEnd} onDragCancel={() => setActiveId(null)}>
      <div className="cw-wall-scroll" tabIndex={0} role="region" aria-label="לוח הכיתות — ניתן לגלול לרוחב">
        <div className="cw-wall">
          {Array.from(byClass.entries()).map(([c, members]) => (
            <Column
              key={c}
              c={c}
              members={members}
              avg={avg}
              thresholds={thresholds}
              categoryFilter={categoryFilter}
              query={normalizedQuery}
              focus={focus}
              reviewGroups={reviewGroups}
              onAskClass={onAskClass}
              interactionDisabled={interactionDisabled}
              onOpen={onOpen}
            />
          ))}
        </div>
      </div>
      <DragOverlay dropAnimation={null}>
        {activeStudent ? (
          <div style={{ width: 192 }}>
            <CardInner s={activeStudent} />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

export function ClassWallLegend() {
  return (
    <div className="cw-legend">
      <span><span className="lg" style={{ background: "var(--cw-incl)" }} />שילוב</span>
      <span><span className="lg" style={{ background: "var(--cw-hamar)" }} />ח&quot;מ</span>
      <span><span className="lg" style={{ background: "var(--cw-eth)" }} />מוצא אתיופי</span>
      <span><span className="lg" style={{ background: "var(--cw-diff)" }} />דיפרנציאלית</span>
      <span>מ / ב / ח = רמת הישגים</span>
      <span><Icon name="heart" size={11} /> = חברות הדדיות</span>
      <span><Icon name="lock" size={11} /> = נעולה</span>
    </div>
  );
}
