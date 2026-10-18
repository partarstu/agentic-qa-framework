// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from 'vitest';
import css from './tokens.css?raw';

function tokens(selector: string, sheet = css): Record<string, string> {
  const start = sheet.indexOf(`${selector} {`);
  const block = sheet.slice(start, sheet.indexOf('}', start));
  return Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6});/g)].map(([, name, value]) => [name, value]));
}

function luminance(hex: string): number {
  const [red, green, blue] = [1, 3, 5].map((at) => Number.parseInt(hex.slice(at, at + 2), 16) / 255)
    .map((channel) => (channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrast(first: string, second: string): number {
  const [lighter, darker] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

const light = tokens(':root');
const dark = { ...light, ...tokens(':root[data-theme="dark"]') };
const moreContrastSheet = css.slice(css.indexOf('@media (prefers-contrast: more)'));
const themes = {
  light,
  dark,
  'light more-contrast': { ...light, ...tokens(':root', moreContrastSheet) },
  'dark more-contrast': { ...dark, ...tokens(':root[data-theme="dark"]', moreContrastSheet) },
};

const TEXT_PAIRS: [string, string][] = [
  ...['ink', 'muted', 'accent', 'passed', 'failed', 'warning', 'error'].flatMap((text): [string, string][] =>
    ['panel', 'surface', 'raised'].map((surface) => [text, surface])),
  ['on-accent', 'accent'],
  ['on-accent', 'accent-strong'],
  ['ink', 'accent-soft'],
  ['muted', 'accent-soft'],
  ['accent', 'accent-soft'],
  ['passed', 'passed-soft'],
  ['failed', 'failed-soft'],
  ['warning', 'warning-soft'],
  ['error', 'error-soft'],
  ['ink', 'failed-soft'],
  ['ink', 'warning-soft'],
  ['muted', 'warning-soft'],
  ['ink', 'passed-soft'],
  ['passed', 'accent-soft'],
  ['failed', 'accent-soft'],
  ['warning', 'accent-soft'],
];

const BOUNDARY_PAIRS: [string, string][] = [
  ['field-border', 'panel'],
  ['field-border', 'field'],
  ['field-border', 'surface'],
  ['accent', 'surface'],
  ['accent', 'panel'],
];

// Machado, Oliveira and Fernandes (2009) dichromacy at full severity, applied to linear RGB
const DICHROMACIES: Record<string, number[][]> = {
  protanopia: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deuteranopia: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
};
const IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
// OKLab distance ×100: 8 keeps simulated colours apart, 15 keeps them apart for every other eye
const MIN_DICHROMAT_DISTANCE = 8;
const MIN_NORMAL_DISTANCE = 15;
const SERIES = ['series-1', 'series-2', 'series-3', 'series-4'];
const SERIES_PAIRS = SERIES.flatMap((first, index) => SERIES.slice(index + 1).map((second): [string, string] => [first, second]));

function linearRgb(hex: string): number[] {
  return [1, 3, 5].map((at) => Number.parseInt(hex.slice(at, at + 2), 16) / 255)
    .map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));
}

function oklab(hex: string, vision: number[][]): number[] {
  const rgb = linearRgb(hex);
  const [red, green, blue] = vision.map((row) => Math.min(1, Math.max(0, row[0] * rgb[0] + row[1] * rgb[1] + row[2] * rgb[2])));
  const l = Math.cbrt(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue);
  const m = Math.cbrt(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue);
  const s = Math.cbrt(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

function distance(first: string, second: string, vision = IDENTITY): number {
  const [a, b] = [oklab(first, vision), oklab(second, vision)];
  return 100 * Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

describe.each([['light', light], ['dark', dark]])('the %s chart series', (_name, theme) => {
  it.each(SERIES_PAIRS)('keep %s and %s apart', (first, second) => {
    expect(distance(theme[first], theme[second])).toBeGreaterThanOrEqual(MIN_NORMAL_DISTANCE);
    for (const vision of Object.values(DICHROMACIES)) {
      expect(distance(theme[first], theme[second], vision)).toBeGreaterThanOrEqual(MIN_DICHROMAT_DISTANCE);
    }
  });

  it.each(SERIES)('keep %s at 3:1 or more on the panel', (series) => {
    expect(contrast(theme[series], theme.panel)).toBeGreaterThanOrEqual(3);
  });
});

describe.each(Object.entries(themes))('the %s theme', (_name, theme) => {
  it.each(TEXT_PAIRS)('keeps %s text on %s at 4.5:1 or more', (text, background) => {
    expect(contrast(theme[text], theme[background])).toBeGreaterThanOrEqual(4.5);
  });

  it.each(BOUNDARY_PAIRS)('keeps the %s boundary against %s at 3:1 or more', (boundary, background) => {
    expect(contrast(theme[boundary], theme[background])).toBeGreaterThanOrEqual(3);
  });
});
