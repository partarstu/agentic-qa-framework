// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import './Tabs.css';

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
}

interface Props<T extends string> {
  label: string;
  idPrefix: string;
  tabs: TabItem<T>[];
  selected: T;
  onSelect: (id: T) => void;
  className?: string;
}

const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

/** The tab a key moves the focus to under the WAI-ARIA tabs pattern, or null for a key the pattern leaves alone. */
export function tabKeyTarget(key: string, index: number, count: number): number | null {
  switch (key) {
    case 'ArrowRight':
      return (index + 1) % count;
    case 'ArrowLeft':
      return (index - 1 + count) % count;
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    default:
      return null;
  }
}

/** ARIA tabs with manual activation: the arrows, Home and End move the focus, Enter or Space selects. */
export function TabList<T extends string>({ label, idPrefix, tabs, selected, onSelect, className }: Props<T>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  const moveFocus = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const target = tabKeyTarget(event.key, index, tabs.length);
    if (target !== null) {
      event.preventDefault();
      buttons.current[target]?.focus();
    }
  };

  return (
    <div className={className ? `tab-list ${className}` : 'tab-list'} role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          ref={(element) => {
            buttons.current[index] = element;
          }}
          type="button"
          role="tab"
          id={tabId(idPrefix, tab.id)}
          aria-selected={selected === tab.id}
          aria-controls={panelId(idPrefix, tab.id)}
          tabIndex={selected === tab.id ? 0 : -1}
          onClick={() => onSelect(tab.id)}
          onKeyDown={(event) => moveFocus(event, index)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function tabPanelProps(idPrefix: string, id: string) {
  return { role: 'tabpanel', id: panelId(idPrefix, id), 'aria-labelledby': tabId(idPrefix, id) } as const;
}
