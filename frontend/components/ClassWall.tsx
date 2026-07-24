"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { StudentRow, CategoryKey, fullName } from "@/components/ClassBoard";
import { Icon } from "@/components/Icon";

export type { StudentRow, CategoryKey };
export { fullName };

// Column stat min/max per category (from the solver config).
export interface Thresholds {
  incl: { min: number; max: number };
  hamar: { min: number; max: number };
  eth: { min: number; max: number };
  diff: { min: number; max: number };
}

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
      <span className="name">{fullName(s)}</span>
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

function DraggableCard({ s, dim, onOpen }: { s: StudentRow; dim: boolean; onOpen: (s: StudentRow) => void }) {
  const locked = Boolean(s["נעולה"]);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: s["מזהה"], disabled: locked });
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
  onOpen,
}: {
  c: number;
  members: StudentRow[];
  avg: number;
  thresholds: Thresholds;
  categoryFilter: CategoryKey | null;
  onOpen: (s: StudentRow) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `class-${c}` });
  const sizeFlag = avg > 0 && Math.abs(members.length - avg) > 1;

  const stats = CATS.map((cat) => {
    const n = members.filter((m) => m[cat.field]).length;
    const t = thresholds[cat.cls];
    const bad = n > t.max || (t.min > 0 && n < t.min);
    return (
      <span key={cat.cls} className={clsx("cw-stat", bad && "flag")}>
        <span className="s-dot" style={{ background: `var(--cw-${cat.cls})` }} />
        {cat.label} {n}
      </span>
    );
  });

  return (
    <section ref={setNodeRef} className={clsx("cw-col", isOver && "over")}>
      <header className="cw-col-head">
        <div className="cw-col-title">
          <span className="name">כיתה {c}</span>
          <span className={clsx("size cw-num", sizeFlag && "flag")}>{members.length}</span>
        </div>
        <div className="cw-col-stats">{stats}</div>
      </header>
      <div className="cw-col-body">
        {members.length === 0 ? (
          <p className="cw-col-empty">גררו לכאן תלמידה</p>
        ) : (
          members.map((s) => (
            <DraggableCard
              key={s["מזהה"]}
              s={s}
              dim={Boolean(categoryFilter) && !s[categoryFilter as string]}
              onOpen={onOpen}
            />
          ))
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
  onMove,
  onOpen,
}: {
  students: StudentRow[];
  numClasses: number;
  thresholds: Thresholds;
  categoryFilter: CategoryKey | null;
  onMove: (studentId: number, toClass: number) => void;
  onOpen: (s: StudentRow) => void;
}) {
  const [activeId, setActiveId] = useState<number | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
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
    <DndContext sensors={sensors} onDragStart={handleStart} onDragEnd={handleEnd} onDragCancel={() => setActiveId(null)}>
      <div className="cw-wall-scroll">
        <div className="cw-wall">
          {Array.from(byClass.entries()).map(([c, members]) => (
            <Column
              key={c}
              c={c}
              members={members}
              avg={avg}
              thresholds={thresholds}
              categoryFilter={categoryFilter}
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
