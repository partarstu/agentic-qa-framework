// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useId, useRef, useState, type CSSProperties, type ReactElement } from 'react';
import './Tooltip.css';

const SHOW_DELAY_MILLIS = 400;
const HIDE_DELAY_MILLIS = 120;

/** What the trigger spreads onto its element. */
export interface TooltipTriggerProps {
  style: CSSProperties;
  'aria-describedby'?: string;
  onPointerEnter: () => void;
  onPointerLeave: () => void;
  onPointerDown: () => void;
  onFocus: () => void;
  onBlur: () => void;
}

/**
 * A tooltip keyboard users see too (WCAG 1.4.13), shown on hover and focus after a delay, hoverable, and hidden on Escape, blur and pointer leave; the caller renders `tooltip` next to the trigger.
 * @param describes false when the text only repeats the trigger's accessible name
 */
export function useTooltip(text: string, describes = true): { trigger: TooltipTriggerProps; tooltip: ReactElement } {
  const id = useId();
  const tip = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // A click focuses its button too, and a tooltip popping up under the pointer that just clicked is noise
  const pressed = useRef(false);
  const [open, setOpen] = useState(false);
  const anchor = `--tooltip-${id.replace(/[^\w-]/g, '')}`;

  const after = (delay: number, next: boolean) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(next), delay);
  };

  useEffect(() => {
    if (open) {
      tip.current?.showPopover();
    } else {
      tip.current?.hidePopover();
    }
  }, [open]);

  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    if (!open) {
      return;
    }
    // In the capture phase, so the Escape that hides the tooltip does not also cancel a dialog or reach a shortcut
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        clearTimeout(timer.current);
        setOpen(false);
      }
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [open]);

  const trigger: TooltipTriggerProps = {
    style: { anchorName: anchor },
    'aria-describedby': describes ? id : undefined,
    onPointerEnter: () => after(SHOW_DELAY_MILLIS, true),
    onPointerLeave: () => after(HIDE_DELAY_MILLIS, false),
    onPointerDown: () => {
      pressed.current = true;
      after(0, false);
    },
    onFocus: () => {
      if (!pressed.current) {
        after(SHOW_DELAY_MILLIS, true);
      }
    },
    onBlur: () => {
      pressed.current = false;
      after(0, false);
    },
  };

  // popover="hint" would bring the light dismiss of a tooltip, but Safari lacks it
  const tooltip = (
    <span ref={tip} id={id} role="tooltip" popover="manual" className="tooltip" style={{ positionAnchor: anchor }}
      onPointerEnter={() => clearTimeout(timer.current)} onPointerLeave={() => after(HIDE_DELAY_MILLIS, false)}>
      {text}
    </span>
  );
  return { trigger, tooltip };
}
