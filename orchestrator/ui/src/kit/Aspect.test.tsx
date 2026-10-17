// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AGENT_STATUS_LABELS, AGENT_STATUS_TONES, BROKEN_REASON_LABELS, BROKEN_REASON_TONES, TASK_STATUS_LABELS, TASK_STATUS_TONES } from '../labels';
import { axeViolations, installDom } from '../testing/dom';
import { Aspect, type Tone } from './Aspect';

installDom();

const STATUSES: [string, Tone][] = [
  ...Object.entries(AGENT_STATUS_LABELS).map(([status, label]): [string, Tone] => [label, AGENT_STATUS_TONES[status as keyof typeof AGENT_STATUS_TONES]]),
  ...Object.entries(BROKEN_REASON_LABELS).map(([reason, label]): [string, Tone] => [label, BROKEN_REASON_TONES[reason as keyof typeof BROKEN_REASON_TONES]]),
  ...Object.entries(TASK_STATUS_LABELS).map(([status, label]): [string, Tone] => [label, TASK_STATUS_TONES[status as keyof typeof TASK_STATUS_TONES]]),
];

describe('Aspect', () => {
  it.each(STATUSES)('shows %s as a word with a shape of its tone', async (label, tone) => {
    render(<Aspect tone={tone}>{label}</Aspect>);
    const aspect = screen.getByText(label);

    expect(aspect.classList.contains(`aspect-${tone}`)).toBe(true);
    expect(aspect.querySelector(tone === 'running' ? '.aspect-pulse' : 'svg')?.getAttribute('aria-hidden')).toBe('true');
    expect(await axeViolations()).toEqual([]);
  });
});
