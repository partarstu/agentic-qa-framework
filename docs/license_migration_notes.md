# License Migration Plan: Apache 2.0 → AGPL v3

## agentic_qa_framework

| # | File | Change |
|---|------|--------|
| 1 | `LICENSE` | Replace full Apache 2.0 text with AGPL v3 text + fill in copyright: `Copyright (C) 2025-2026 Taras Paruta` |
| 2 | `README.md` (line 650) | Update `Apache License 2.0` → `GNU Affero General Public License v3.0 (AGPL-3.0)` |

All Python source files have `# SPDX-License-Identifier: Apache-2.0` headers — update to `AGPL-3.0-only` in all `.py`, `.toml`, `.yaml`, and `Dockerfile` files. Also add `LICENSES/AGPL-3.0-only.txt` to satisfy REUSE compliance.

---

## test-execution-agents

| # | File | Change |
|---|------|--------|
| 3 | `LICENSE` | Replace full Apache 2.0 text with AGPL v3 text + fill in copyright: `Copyright (C) 2025-2026 Taras Paruta` |
| 4 | `CONTRIBUTING.md` (lines 19–20) | Update Apache 2.0 reference to AGPL v3 |
| 5 | `NOTICE` | Update year range: `Copyright 2025` → `Copyright 2025-2026` |
| 6 | `pom.xml` (line 323) | Change license-maven-plugin header template from `APACHE-2.txt` → `AGPL-3.txt` |
| 7 | All Java source files | Run `mvn license:format` — the plugin will automatically replace Apache 2.0 headers with AGPL v3 headers in all `.java` files |

---

## Notes

- Past versions already distributed under Apache 2.0 remain Apache 2.0 for those recipients — this change applies to all future versions only.
- Once outside contributions are accepted, a CLA (Contributor License Agreement) must be in place before merging any PR.
- Never add GPL or AGPL dependencies — current dependencies (MIT/BSD/Apache 2.0) are all commercially safe.
- If a commercial buyer appears, issue them a separate commercial license — no need to change this license again.
