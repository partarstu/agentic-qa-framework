// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { X } from 'lucide-react';
import { useId, type ReactNode } from 'react';
import { IconButton } from '../kit/IconButton';
import { Modal } from '../kit/Modal';
import './Sheet.css';

/** The details of an agent or a task in a side sheet, closed by its button or Escape. */
export function Sheet({ open, title, onClose, children }: { open: boolean; title: ReactNode; onClose: () => void; children: ReactNode }) {
  const headingId = useId();
  return (
    <Modal open={open} labelledBy={headingId} onCancel={onClose} sheet>
      <div className="sheet-head">
        <h2 id={headingId}>{title}</h2>
        <IconButton icon={X} label="Close" onClick={onClose} />
      </div>
      {children}
    </Modal>
  );
}
