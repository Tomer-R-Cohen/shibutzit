import { ReactNode } from "react";

/**
 * Pure structure: TopBar + a two-pane grid. In RTL, the first grid child
 * lands at the inline-start edge (the right side), so `conversation` is
 * placed first to make it the dominant ~60% surface on the right, with
 * `inspector` at ~40% on the left -- matching the product spec. All actual
 * content/state composition happens in app/page.tsx.
 */
export default function WorkspaceShell({ topBar, conversation, inspector }: { topBar: ReactNode; conversation: ReactNode; inspector: ReactNode }) {
  return (
    <div className="ws-shell">
      {topBar}
      <div className="ws-main">
        {conversation}
        {inspector}
      </div>
    </div>
  );
}
