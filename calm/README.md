<!--
SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)

SPDX-License-Identifier: AGPL-3.0-only
-->

# Architecture as Code (CALM)

This directory holds the QuAIA architecture described with the
[FINOS CALM](https://calm.finos.org/) (Common Architecture Language Model)
standard. It is validated in CI as a **blocking** gate, so the model cannot
drift away from the system without the build failing.

## Layout

| Path | Purpose |
|---|---|
| `architecture/quaia.arch.json` | The architecture instance: every service/actor (`nodes`), the integration edges between them (`relationships`), and the security `controls` attached to them. |
| `patterns/quaia.pattern.json` | The governance pattern. A JSON-Schema that asserts the required nodes, relationships and controls are present. This is what makes the gate fail on drift. |
| `controls/requirements/*.json` | Control requirement schemas describing the shape of each control's configuration (authentication, prompt-injection protection). |
| `url-mapping.json` | Maps the control `requirement-url` identifiers to their local schema files so validation runs fully offline. |

## Controls enforced by the pattern

| Control | Attached to | Source mechanism |
|---|---|---|
| `orchestrator-api-key` | `orchestrator` node | `X-API-Key` on control/webhook endpoints (`ORCHESTRATOR_API_KEY`) |
| `dashboard-jwt` | `orchestrator` node | JWT on dashboard endpoints (`DASHBOARD_JWT_SECRET`) |
| `jira-webhook-hmac` | `rel-jira-webhook-orchestrator` | `X-Hub-Signature` HMAC-SHA256 (`JIRA_WEBHOOK_SECRET`) |
| `prompt-injection-guard` | every agent node | Prompt-injection screening (`PROMPT_INJECTION_CHECK_ENABLED`) |
| `internal-service-api-key` | `embedding-service`, `prompt-guard-service` | Shared `X-API-Key` (`INTERNAL_SERVICE_API_KEY`) |

## Running validation locally

Requires [Node.js](https://nodejs.org/) 20+.

```bash
# from the repository root
cd calm

# one-off, no global install
npx -y @finos/calm-cli@1.46.0 validate \
  -p patterns/quaia.pattern.json \
  -a architecture/quaia.arch.json \
  -u url-mapping.json \
  --strict -f pretty
```

A clean run prints `No issues found.` and exits `0`. Removing a required node,
relationship or control makes validation exit non-zero — the same check the
`Architecture (CALM)` CI job runs.

## Changing the architecture

When you add or remove an agent, service or integration edge, update
`architecture/quaia.arch.json` and, if the change is part of the contract you
want enforced, `patterns/quaia.pattern.json`. Run the command above before
committing.
