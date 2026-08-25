import { ReactNode } from "react";

/**
 * Pure structure: TopBar + a two-pane grid. In RTL, the first grid child
 * lands at the inline-start edge (the right side), so `conversation` is
 * placed first to make it the dominant surface on the right, with
 * `inspector` beside it on the left -- matching the product spec. All actual
 * content/state composition happens in app/page.tsx.
 *
 * Below 900px the grid drops to one column and the inspector becomes a
 * sheet over the conversation (see `.ws-inspector` in globals.css). It used
 * to simply stack below a `flex: 1` conversation inside a 100dvh shell,
 * which pushed it past the bottom of the viewport with nothing to scroll --
 * the whole pane was unreachable on a phone. `inspectorOpen` drives that
 * sheet; on desktop it is inert, because the media query is what decides
 * whether the pane is positioned at all.
 */
export default function WorkspaceShell({
  topBar,
  conversation,
  inspector,
  inspectorOpen,
  onCloseInspector,
}: {
  topBar: ReactNode;
  conversation: ReactNode;
  inspector: ReactNode;
  inspectorOpen?: boolean;
  onCloseInspector?: () => void;
}) {
  return (
    <div className="ws-shell">
      {topBar}
      <div className="ws-main">
        {conversation}
        {inspector}
        {inspectorOpen && (
          <button type="button" className="ws-insp-scrim" aria-label="סגירת מצב נוכחי" onClick={onCloseInspector} />
        )}
      </div>
    </div>
  );
}
