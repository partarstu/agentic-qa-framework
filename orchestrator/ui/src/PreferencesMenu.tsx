// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Monitor, Moon, Settings2, Sun } from 'lucide-react';
import { setThemeChoice, useThemeChoice, type ThemeChoice } from './colorScheme';
import { Popover } from './kit/Popover';

const THEMES: { id: ThemeChoice; label: string; Icon: typeof Sun }[] = [
  { id: 'system', label: 'Same as the system', Icon: Monitor },
  { id: 'light', label: 'Light', Icon: Sun },
  { id: 'dark', label: 'Dark', Icon: Moon },
];

/** The user's own settings for this browser. */
export function PreferencesMenu() {
  const theme = useThemeChoice();
  return (
    <Popover label={<><Settings2 size={18} /><span className="appbar-label">Preferences</span></>}>
      <div className="preferences">
        <fieldset>
          <legend>Theme</legend>
          {THEMES.map(({ id, label, Icon }) => (
            <label key={id} className="check">
              <input type="radio" name="dashboard-theme" checked={theme === id} onChange={() => setThemeChoice(id)} />
              <Icon size={16} />
              {label}
            </label>
          ))}
        </fieldset>
      </div>
    </Popover>
  );
}
