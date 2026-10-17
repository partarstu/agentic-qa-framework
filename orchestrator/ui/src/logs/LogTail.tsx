// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { ArrowUpToLine, Check, CircleAlert, Copy, LoaderCircle, ScrollText, WrapText, type LucideIcon } from 'lucide-react';
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { COPY_BLOCKED, copyText } from '../clipboard';
import { IconButton } from '../kit/IconButton';
import type { LogEntry } from '../types/dashboard';
import type { TailItem } from './tailItems';
import type { useLogTail } from './useLogTail';
import './LogTail.css';

const STICK_TO_TOP_PX = 24;
const COPY_RESULT_MILLIS = 4_000;

type CopyResult = 'copied' | 'blocked';

const COPY_RESULT_ICONS: Record<CopyResult, LucideIcon> = { copied: Check, blocked: CircleAlert };

const MARKER_TEXTS = { skipped: 'Lines skipped here', missed: 'Events missed here' } as const;

export type LogTailState = ReturnType<typeof useLogTail>;

export type LogTone = 'error' | 'warn' | 'other';

export function levelTone(level: string): LogTone {
  if (level === 'ERROR' || level === 'CRITICAL') {
    return 'error';
  }
  return level === 'WARNING' ? 'warn' : 'other';
}

export function lineText({ timestamp, level, logger, message }: LogEntry): string {
  return [timestamp, level, logger, '-', message].filter(Boolean).join(' ');
}

/** The text with every case-insensitive occurrence of the query marked. */
export function highlighted(text: string, query: string): ReactNode {
  const needle = query.trim().toLowerCase();
  if (needle === '') {
    return text;
  }
  const parts: ReactNode[] = [];
  const lower = text.toLowerCase();
  let from = 0;
  for (let at = lower.indexOf(needle); at >= 0; at = lower.indexOf(needle, at + needle.length)) {
    parts.push(text.slice(from, at), <mark key={at}>{text.slice(at, at + needle.length)}</mark>);
    from = at + needle.length;
  }
  parts.push(text.slice(from));
  return parts;
}

interface Props {
  title: string;
  tail: LogTailState;
  headingLevel?: 2 | 3;
  /** Names a line's task, where the tail mixes the lines of several. */
  taskLabel?: (taskId: string) => string;
  /** The caller's own controls, shown in the toolbar. */
  tools?: ReactNode;
}

/**
 * The lines of a log tail, newest first, following the newest until the reader scrolls down, with a text filter over the loaded lines,
 * the markers where lines are missing and "Load older".
 */
export function LogTail({ title, tail, headingLevel = 3, taskLabel, tools }: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const [copyResult, setCopyResult] = useState<CopyResult | null>(null);
  const [query, setQuery] = useState('');
  const [wrap, setWrap] = useState(true);
  const headingId = useId();
  const Heading = headingLevel === 2 ? 'h2' : 'h3';

  const entries = tail.items.flatMap((item) => (item.kind === 'entry' ? [item.entry] : []));
  const needle = query.trim().toLowerCase();
  const filtered = needle !== '';
  const shown: TailItem[] = filtered
    ? tail.items.filter((item) => item.kind === 'entry' && `${item.entry.logger} ${item.entry.message}`.toLowerCase().includes(needle))
    : tail.items;
  const shownEntries = filtered ? shown.length : entries.length;

  useLayoutEffect(() => {
    const element = viewport.current;
    if (element && following) {
      element.scrollTop = 0;
    }
  }, [tail.items, following, query]);

  useEffect(() => {
    if (copyResult === null) {
      return;
    }
    const timer = setTimeout(() => setCopyResult(null), COPY_RESULT_MILLIS);
    return () => clearTimeout(timer);
  }, [copyResult]);

  // A reader who scrolled down is not pulled back up by new lines; the browser's scroll anchoring keeps their place
  const onScroll = () => {
    const element = viewport.current;
    if (element) {
      setFollowing(element.scrollTop < STICK_TO_TOP_PX);
    }
  };

  const copy = async () => {
    const lines = shown.flatMap((item) => (item.kind === 'entry' ? [lineText(item.entry)] : [])).toReversed();
    setCopyResult((await copyText(lines.join('\n'))) ? 'copied' : 'blocked');
  };

  return (
    <section className="log">
      <div className="section-head">
        <Heading id={headingId}><ScrollText size={18} />{title}</Heading>
        <span className="section-note">
          {filtered ? `${shownEntries} of ${entries.length} loaded lines` : entries.length === 1 ? '1 loaded line' : `${entries.length} loaded lines`}
        </span>
        <div className="section-tools">
          <span className={copyResult === 'blocked' ? 'log-copy-result log-copy-blocked' : 'log-copy-result'} role="status">
            {copyResult === 'copied' && 'Copied'}
            {copyResult === 'blocked' && COPY_BLOCKED}
          </span>
          <IconButton icon={copyResult ? COPY_RESULT_ICONS[copyResult] : Copy} label={filtered ? 'Copy the lines shown' : 'Copy the loaded lines'}
            small disabled={shownEntries === 0} onClick={() => void copy()} />
        </div>
      </div>
      <div className="log-toolbar">
        {tools}
        <input type="search" className="log-search" aria-label="Find in the loaded lines" placeholder="Find in the loaded lines" maxLength={200}
          value={query} onChange={(event) => setQuery(event.target.value)} />
        <IconButton icon={WrapText} label="Wrap long lines" small aria-pressed={wrap} onClick={() => setWrap(!wrap)} />
      </div>
      {tail.status === 'loading' && <p className="loading-note"><LoaderCircle size={18} className="spin" />Loading the log…</p>}
      {tail.status === 'error' && <p className="alert" role="alert">The log could not be loaded. It loads again when this source is opened again.</p>}
      {tail.status === 'ready' && (
        <div className="log-frame">
          {/* A focusable region rather than role="log", whose implied live announcements would read out every streamed line */}
          <div ref={viewport} className={wrap ? 'log-lines' : 'log-lines log-lines-nowrap'} role="region" aria-labelledby={headingId}
            tabIndex={0} onScroll={onScroll}>
            {shown.length === 0
              ? <p className="empty">{entries.length === 0 ? 'No log lines yet.' : 'No loaded line matches.'}</p>
              : shown.map((item) => (item.kind === 'entry'
                ? <LogLine key={item.entry.id} entry={item.entry} query={query} taskLabel={taskLabel} />
                : <div key={item.key} className="log-marker">{MARKER_TEXTS[item.kind]}</div>))}
          </div>
          {!following && (
            <button type="button" className="small primary log-jump" onClick={() => setFollowing(true)}>
              <ArrowUpToLine size={16} />
              Jump to the newest
            </button>
          )}
        </div>
      )}
      {tail.status === 'ready' && entries.length > 0 && (
        <div className="log-older">
          {tail.exhausted
            ? <span className="muted">The oldest line is loaded.</span>
            : (
              <button type="button" className="small" aria-busy={tail.loadingOlder} disabled={tail.loadingOlder} onClick={tail.loadOlder}>
                {tail.loadingOlder && <LoaderCircle size={16} className="spin" />}
                Load older lines
              </button>
            )}
          {tail.olderFailed && <span className="alert" role="alert">The older lines could not be loaded.</span>}
        </div>
      )}
    </section>
  );
}

function LogLine({ entry, query, taskLabel }: { entry: LogEntry; query: string; taskLabel?: (taskId: string) => string }) {
  return (
    <div className={`log-line log-${levelTone(entry.level)}`}>
      {entry.timestamp && <><span className="log-time">{entry.timestamp.replace('T', ' ')}</span>{' '}</>}
      <span className="log-level">{entry.level}</span>{' '}
      {taskLabel && entry.task_id && <><span className="log-task">[{taskLabel(entry.task_id)}]</span>{' '}</>}
      <span className="log-logger">{highlighted(entry.logger, query)}</span>{' - '}
      {highlighted(entry.message, query)}
    </div>
  );
}
