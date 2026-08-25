"use client";

import clsx from "clsx";
import { ConstraintsSummary, Highlight, InspectorState, Workspace } from "@/lib/workspace";
import OverviewInspector from "./inspector/OverviewInspector";
import ConstraintBrowser from "./inspector/ConstraintBrowser";
import ConstraintInspector from "./inspector/ConstraintInspector";

// Only these fields are needed here -- narrower than the full Workspace
// hook so fixture previews can pass a lightweight local stand-in without
// wiring up the rest of useWorkspace()'s real-API surface.
export type ContextInspectorWorkspace = Pick<
  Workspace,
  "inspector" | "setInspector" | "refreshConstraintsSummary" | "appendRunConfigChange" | "dataVersion" | "bumpDataVersion"
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
  highlight,
  onHighlight,
  sheetOpen,
}: {
  workspace: ContextInspectorWorkspace;
  studentCount: number | null;
  onOpenRoster?: () => void;
  highlight?: Highlight;
  onHighlight?: (h: Highlight) => void;
  /** Only meaningful below 900px, where the pane is a sheet rather than a column. */
  sheetOpen?: boolean;
}) {
  const { inspector, setInspector, constraintsSummary, refreshConstraintsSummary, appendRunConfigChange, dataVersion, bumpDataVersion } =
    workspace;

  function open(state: InspectorState) {
    setInspector(state);
  }

  const modeKey = inspector.type === "constraint" ? `constraint:${inspector.id}` : inspector.type;

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
            }}
            onRemoved={() => open({ type: "constraints" })}
          />
        );
      default:
        return (
          <OverviewInspector
            studentCount={studentCount}
            constraintsSummary={constraintsSummary}
            onOpenConstraints={() => open({ type: "constraints" })}
            onOpenRoster={onOpenRoster}
            onConstraintsChanged={() => {
              bumpDataVersion();
              void refreshConstraintsSummary();
            }}
            onRunConfigChange={appendRunConfigChange}
            refreshKey={dataVersion}
            hasDataset={studentCount != null}
          />
        );
    }
  }

  return (
    <aside id="ws-inspector" className={clsx("ws-inspector", sheetOpen && "open")}>
      <div key={modeKey} className="ws-insp-mode">
        {content()}
      </div>
    </aside>
  );
}
