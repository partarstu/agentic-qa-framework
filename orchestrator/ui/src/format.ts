// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

const relativeTime = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
const subMinute = new Intl.DurationFormat(undefined, { style: 'short', milliseconds: 'numeric', fractionalDigits: 1 });
const subSecond = new Intl.DurationFormat(undefined, { style: 'short', millisecondsDisplay: 'always' });
const wholeUnits = new Intl.DurationFormat(undefined, { style: 'short' });

export function localTime(iso: string): string {
  return clockTime(new Date(iso));
}

export function clockTime(date: Date): string {
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

export function age(iso: string, nowMillis: number): string {
  const minutes = Math.round((new Date(iso).getTime() - nowMillis) / 60_000);
  if (Math.abs(minutes) < 60) {
    return relativeTime.format(minutes, 'minute');
  }
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) {
    return relativeTime.format(hours, 'hour');
  }
  return relativeTime.format(Math.round(hours / 24), 'day');
}

/** A duration in the units a person reads it in: milliseconds below a second, one decimal below a minute, whole units above. */
export function duration(millis: number): string {
  const rounded = Math.max(0, Math.round(millis));
  if (rounded < 1_000) {
    return subSecond.format({ milliseconds: rounded });
  }
  if (rounded < 60_000) {
    return subMinute.format({ seconds: Math.floor(rounded / 1_000), milliseconds: rounded % 1_000 });
  }
  const seconds = Math.round(rounded / 1_000);
  return wholeUnits.format({ hours: Math.floor(seconds / 3_600), minutes: Math.floor(seconds / 60) % 60, seconds: seconds % 60 });
}

export function localDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function localDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' });
}
