// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useId, useLayoutEffect, useRef, useState } from 'react';
import './ClampedError.css';

/** An error message cut to its first four lines, with a button to show the whole text when it is longer. */
export function ClampedError({ text }: { text: string }) {
  const body = useRef<HTMLParagraphElement>(null);
  const [clamped, setClamped] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const bodyId = useId();

  useLayoutEffect(() => {
    const element = body.current;
    if (!element || expanded) {
      return;
    }
    const measure = () => setClamped(element.scrollHeight > element.clientHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, expanded]);

  return (
    <div className="clamped-error">
      <p ref={body} id={bodyId} className={expanded ? 'clamped-error-text' : 'clamped-error-text clamped-error-collapsed'}>{text}</p>
      {clamped && (
        <button type="button" className="link clamped-error-toggle" aria-expanded={expanded} aria-controls={bodyId}
          onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : 'Show the whole error'}
        </button>
      )}
    </div>
  );
}
