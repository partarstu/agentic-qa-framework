// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { ChevronDown } from 'lucide-react';
import { useId, type ReactNode } from 'react';
import './Popover.css';

interface Props {
  label: ReactNode;
  children: ReactNode;
}

/** Transient UI such as a filter or a menu on the Popover API, which dismisses it on Escape and on a click outside. */
export function Popover({ label, children }: Props) {
  const id = useId();
  return (
    <>
      <button type="button" className="popover-toggle quiet" popoverTarget={id}>
        {label}
        <ChevronDown size={16} />
      </button>
      <div id={id} popover="auto" className="popover">
        {children}
      </div>
    </>
  );
}
