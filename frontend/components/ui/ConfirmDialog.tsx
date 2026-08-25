"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/primitives";

/**
 * A small centred confirm, for the handful of actions that throw work away.
 *
 * Separate from the workspace `Dialog`, which is a near-full-screen surface
 * for the roster and results boards -- opening that to ask a yes/no question
 * would be a whole screen for one sentence.
 */
export default function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  cancelLabel = "ביטול",
  danger = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="ws-dialog-overlay" />
        <RadixDialog.Content className="ws-confirm" aria-describedby="ws-confirm-body">
          <RadixDialog.Title className="ws-confirm-title">{title}</RadixDialog.Title>
          <p id="ws-confirm-body" className="ws-confirm-body">
            {body}
          </p>
          <div className="ws-confirm-actions">
            <RadixDialog.Close asChild>
              <Button variant="secondary" size="sm">
                {cancelLabel}
              </Button>
            </RadixDialog.Close>
            <Button variant={danger ? "danger" : "primary"} size="sm" onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
