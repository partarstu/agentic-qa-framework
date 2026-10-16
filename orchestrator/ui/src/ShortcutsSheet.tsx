// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Fragment } from 'react';
import { Modal } from './kit/Modal';
import { SHORTCUTS } from './shortcuts';

export function ShortcutsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} title="Keyboard shortcuts" onCancel={onClose}>
      <dl className="shortcuts">
        {SHORTCUTS.map(({ keys, join, description }) => (
          <Fragment key={description}>
            <dt>
              {keys.map((key, index) => (
                <Fragment key={key}>
                  {index > 0 && <span className="shortcut-join">{join}</span>}
                  <kbd className="kbd">{key}</kbd>
                </Fragment>
              ))}
            </dt>
            <dd>{description}</dd>
          </Fragment>
        ))}
      </dl>
      <div className="answers">
        <button type="button" className="primary" data-autofocus onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}
