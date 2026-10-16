// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useId, useRef, type ReactNode } from 'react';
import './Modal.css';

/** A dialog shows its `title` as its heading, or is named by a heading of its content (`labelledBy`) that it does not repeat. */
type Props = {
  open: boolean;
  /** The safe answer Escape gives; without one, Escape does nothing. */
  onCancel?: () => void;
  wide?: boolean;
  children: ReactNode;
} & ({ title: string; labelledBy?: never } | { labelledBy: string; title?: never });

/** A blocking dialog on the native `<dialog>`, which provides the top layer, the inert background, the focus trap and the focus return. */
export function Modal({ open, title, labelledBy, onCancel, wide = false, children }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const answeredBeforeClose = useRef(false);
  const titleId = useId();

  useEffect(() => {
    const element = dialog.current;
    if (!element) {
      return;
    }
    if (open && !element.open) {
      element.showModal();
      // showModal moves the focus after React's autoFocus has run, so the control to focus is marked instead
      element.querySelector<HTMLElement>('[data-autofocus]')?.focus();
    } else if (!open && element.open) {
      element.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className={wide ? 'modal modal-wide' : 'modal'}
      aria-labelledby={labelledBy ?? titleId}
      onCancel={(event) => {
        event.preventDefault();
        answeredBeforeClose.current = !event.cancelable;
        onCancel?.();
      }}
      onClose={() => {
        // Without user activation since the last close request, Chrome closes the dialog on Escape after a non-cancelable cancel
        // event or without any, so a dialog closed while still open is shown again and gets the answer Escape gives, once
        const element = dialog.current;
        const answered = answeredBeforeClose.current;
        answeredBeforeClose.current = false;
        if (open && element?.isConnected && !element.open) {
          element.showModal();
          if (!answered) {
            onCancel?.();
          }
        }
      }}
    >
      {title !== undefined && <h2 id={titleId} className="modal-title">{title}</h2>}
      {children}
    </dialog>
  );
}
