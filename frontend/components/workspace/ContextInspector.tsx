"use client";

import clsx from "clsx";
import { useEffect, useRef } from "react";
import { Icon } from "@/components/Icon";
import { ConstraintModel } from "@/lib/api";
import { ConstraintsSummary, Highlight, InspectorState, Workspace } from "@/lib/workspace";
import OverviewInspector, { OverviewInspectorPreview } from "./inspector/OverviewInspector";
import ConstraintBrowser from "./inspector/ConstraintBrowser";
import ConstraintInspector from "./inspector/ConstraintInspector";

// Only these fields are needed here -- narrower than the full Workspace
// hook so fixture previews can pass a lightweight local stand-in without
// wiring up the rest of useWorkspace()'s real-API surface.
export type ContextInspectorWorkspace = Pick<
  Workspace,
  "inspector" | "setInspector" | "refreshConstraintsSummary" | "refreshResultState" | "appendRunConfigChange" | "appendVersionRestore" | "dataVersion" | "bumpDataVersion"
> & {
  constraintsSummary: ConstraintsSummary | null;
};

/**
 * Switches on InspectorState -- the one contextual pane, not a stack of
 * permanent panels. Whatever is currently relevant (dataset overview, a
 * single rule, the full rule list, ...) renders here and nothing else does.
 * The `key` on .ws-insp-mode re-runs the slide/fade entrance on every mode
 * change, so switching entity reads as a transition rather than a swap.
 */
export default function ContextInspector({
  workspace,
  studentCount,
  onOpenRoster,
  onOpenResults,
  highlight,
  onHighlight,
  sheetOpen,
  onCloseSheet,
  overviewPreview,
  constraintPreview,
}: {
  workspace: ContextInspectorWorkspace;
  studentCount: number | null;
  onOpenRoster?: () => void;
  onOpenResults?: () => void;
  highlight?: Highlight;
  onHighlight?: (h: Highlight) => void;
  /** Only meaningful below 900px, where the pane is a sheet rather than a column. */
  sheetOpen?: boolean;
  onCloseSheet?: () => void;
  /** Development-only deterministic overview data for screenshot fixtures. */
  overviewPreview?: OverviewInspectorPreview;
  /** Development-only deterministic rule data for screenshot fixtures. */
  constraintPreview?: ConstraintModel[];
}) {
  const { inspector, setInspector, constraintsSummary, refreshConstraintsSummary, refreshResultState, appendRunConfigChange, appendVersionRestore, dataVersion, bumpDataVersion } =
    workspace;

  function open(state: InspectorState) {
    setInspector(state);
  }

  const modeKey = inspector.type === "constraint" ? `constraint:${inspector.id}` : inspector.type;
  const closeRef = useRef<HTMLButtonElement>(null);
  const inspectorRef = useRef<HTMLElement>(null);

  useEffect(() => {
    inspectorRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [modeKey]);

  useEffect(() => {
    if (!sheetOpen) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseSheet?.();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        inspectorRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ) ?? []
      ).filter((element) => element.getClientRects().length > 0);
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
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, [sheetOpen, onCloseSheet]);

  function content() {
    switch (inspector.type) {
      case "constraints":
        return (
          <ConstraintBrowser
            onSelect={(id) => open({ type: "constraint", id })}
            onBack={() => open({ type: "overview" })}
            refreshKey={dataVersion}
            highlight={highlight ?? null}
            onHighlight={onHighlight}
            previewConstraints={constraintPreview}
          />
        );
      case "constraint":
        return (
          <ConstraintInspector
            id={inspector.id}
            onBack={() => open({ type: "constraints" })}
            onChanged={() => {
              bumpDataVersion();
              void refreshConstraintsSummary();
              void refreshResultState();
            }}
            onRemoved={() => open({ type: "constraints" })}
            previewConstraint={constraintPreview?.find((constraint) => constraint.id === inspector.id)}
          />
        );
      default:
        return (
          <OverviewInspector
            studentCount={studentCount}
            constraintsSummary={constraintsSummary}
            onOpenConstraints={() => open({ type: "constraints" })}
            onOpenRoster={onOpenRoster}
            onOpenResults={onOpenResults}
            onConstraintsChanged={() => {
              bumpDataVersion();
              void refreshConstraintsSummary();
              void refreshResultState();
            }}
            onRunConfigChange={appendRunConfigChange}
            onVersionRestored={appendVersionRestore}
            refreshKey={dataVersion}
            hasDataset={studentCount != null}
            preview={overviewPreview}
          />
        );
    }
  }

  return (
    <aside
      ref={inspectorRef}
      id="ws-inspector"
      className={clsx("ws-inspector", sheetOpen && "open")}
      aria-label="תמונת מצב של הפרויקט"
      role={sheetOpen ? "dialog" : undefined}
      aria-modal={sheetOpen ? true : undefined}
    >
      {sheetOpen && (
        <button ref={closeRef} type="button" className="ws-inspector-close" onClick={onCloseSheet} aria-label="סגירת תמונת המצב">
          <Icon name="x" size={16} />
        </button>
      )}
      <div key={modeKey} className={clsx("ws-insp-mode", inspector.type === "overview" && "overview")}>
        {content()}
      </div>
    </aside>
  );
}
