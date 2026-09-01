"use client";

import { ReactNode } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import { Icon } from "@/components/Icon";

/**
 * Generic full-height workspace dialog (Radix primitive, styled to the
 * `--cw-*` visual system) -- used for surfaces that need real screen space
 * (roster, results) without leaving the workspace behind entirely. The
 * caller owns everything inside `children`, including its own visible
 * header; `title` only feeds the accessible name.
 */
export default function Dialog({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="ws-dialog-overlay" />
        <RadixDialog.Content
          className="ws-dialog-content"
          aria-describedby={undefined}
          // The board contains reversible async actions whose Sonner toast
          // is portalled outside Radix's modal subtree. Treat that toast as
          // an action surface, not as a request to dismiss the workspace.
          // The visible close button and Escape remain available.
          onPointerDownOutside={(event) => event.preventDefault()}
        >
          <RadixDialog.Title className="sr-only">{title}</RadixDialog.Title>
          <RadixDialog.Close asChild>
            <button className="ws-dialog-close" aria-label="סגירה">
              <Icon name="x" size={16} />
            </button>
          </RadixDialog.Close>
          {children}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
