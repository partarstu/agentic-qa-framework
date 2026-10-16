// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { LucideIcon } from 'lucide-react';
import type { ComponentProps } from 'react';
import { useTooltip, type TooltipTriggerProps } from './Tooltip';

type Props = Omit<ComponentProps<'button'>, 'children' | 'aria-label' | 'title' | 'type' | keyof TooltipTriggerProps> & {
  icon: LucideIcon;
  /** The button's accessible name, also shown as its tooltip; required, since the icon alone names nothing. */
  label: string;
  tone?: 'quiet' | 'primary' | 'plain';
  small?: boolean;
  submit?: boolean;
};

export function IconButton({ icon: Icon, label, tone = 'quiet', small = false, submit = false, className, ...rest }: Props) {
  const { trigger, tooltip } = useTooltip(label, false);
  const classes = ['icon-only', tone === 'plain' ? null : tone, small ? 'small' : null, className].filter(Boolean).join(' ');
  return (
    <>
      <button type={submit ? 'submit' : 'button'} className={classes} aria-label={label} {...rest} {...trigger}>
        <Icon size={small ? 16 : 18} aria-hidden="true" />
      </button>
      {tooltip}
    </>
  );
}
