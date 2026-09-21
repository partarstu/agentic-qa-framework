# Plan: <Feature or fix>

## Goal

<One sentence.>

## Open questions

- <Only questions the user must answer; omit the section if none.>

## Architecture

<"No architecture change." or: the nodes, relationships and controls added, removed or renamed under `calm/`, one line each, followed by the line `CALM updated, validated and approved by the user on <date>`. Implementation does not start without that line (*Architecture first* in `AGENTS.md`).>

## Design

- **Components**: <new or changed modules, one line each: responsibility and what it reuses>
- **Decision**: <only for a significant choice: chosen option and why, in one line>

## Workflows

**Logic flow:**

1. <Entry point> → <component> → <component> → <result>

**Data flow:** <only if relevant: what data is created, transformed, stored or returned, and where>

## Impact

<One line per affected area only: smoke suite, configuration, dependencies, security, and the version bump of every agent or orchestrator whose logic changes.>

## TODO

- [ ] <Step> → verify: <check>
