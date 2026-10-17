// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Search } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { matchCommands, type Command } from './commands';
import './CommandPalette.css';

interface Props {
  open: boolean;
  commands: Command[];
  onClose: () => void;
}

/** Every command of the panel behind one field: a modal combobox where typing filters, the arrows pick and Enter runs. */
export function CommandPalette({ open, commands, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const element = dialog.current;
    if (open && element && !element.open) {
      element.showModal();
    } else if (!open && element?.open) {
      element.close();
    }
  }, [open]);

  // Safari has no closedby yet; a click on the backdrop reaches the dialog itself, outside its box, so it closes there too
  useEffect(() => {
    const element = dialog.current;
    const onClick = (event: MouseEvent) => {
      if (element && event.target === element && isOutside(element.getBoundingClientRect(), event)) {
        element.close();
      }
    };
    element?.addEventListener('click', onClick);
    return () => element?.removeEventListener('click', onClick);
  }, []);

  // Closing first hands the focus back to where it was, so a command that moves the focus keeps the last word
  const run = (command: Command) => {
    dialog.current?.close();
    command.run();
  };

  return (
    <dialog ref={dialog} className="palette" aria-label="Search and jump" closedby="any" onClose={onClose}>
      {open && <PaletteSearch commands={commands} onRun={run} />}
    </dialog>
  );
}

export function isOutside(box: Pick<DOMRect, 'left' | 'right' | 'top' | 'bottom'>, { clientX, clientY }: Pick<MouseEvent, 'clientX' | 'clientY'>) {
  return clientX < box.left || clientX > box.right || clientY < box.top || clientY > box.bottom;
}

function PaletteSearch({ commands, onRun }: { commands: Command[]; onRun: (command: Command) => void }) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listId = useId();
  const matches = matchCommands(commands, query);
  const activeIndex = Math.min(active, matches.length - 1);
  const optionId = (index: number) => `${listId}-option-${index}`;

  useEffect(() => {
    document.getElementById(`${listId}-option-${activeIndex}`)?.scrollIntoView({ block: 'nearest' });
  }, [listId, activeIndex]);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (matches.length === 0) {
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      setActive((activeIndex + step + matches.length) % matches.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      onRun(matches[activeIndex]);
    }
  };

  return (
    <>
      <div className="palette-field">
        <Search size={20} aria-hidden="true" />
        <input
          type="text"
          role="combobox"
          aria-label="Search and jump"
          aria-expanded="true"
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={matches.length > 0 ? optionId(activeIndex) : undefined}
          placeholder="Go to a view, an agent or a task, change the theme…"
          autoComplete="off"
          spellCheck={false}
          autoFocus
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
        <kbd className="kbd" aria-hidden="true">Esc</kbd>
      </div>
      <ul id={listId} role="listbox" aria-label="Commands" className="palette-list">
        {matches.map((command, index) => (
          // The focus stays in the field (aria-activedescendant), so a press picks the option without taking the focus away
          <li
            key={command.id}
            id={optionId(index)}
            role="option"
            tabIndex={-1}
            aria-selected={index === activeIndex}
            className="palette-option"
            onMouseDown={(event) => {
              event.preventDefault();
              onRun(command);
            }}
            onMouseMove={() => setActive(index)}
          >
            <command.Icon size={18} aria-hidden="true" />
            <span className="palette-label">{command.label}</span>
            <span className="palette-group">{command.group}</span>
          </li>
        ))}
      </ul>
      {matches.length === 0 && <p className="palette-empty" role="status">No command matches “{query.trim()}”.</p>}
    </>
  );
}
