# Implementation Plan: <Feature>

## Goal

<One or two sentences. Note any deviation from the original request and why.>

## Assumptions and open questions

- <Assumption, or question the user must answer>

## Current state and reuse

- `<module.function>`: <what it does today and what the change reuses>

## Research

| Source (official docs) | Finding | Applied to |
|------------------------|---------|------------|
| <URL>                  |         |            |

## Design

<Components added or changed and how they interact. Optional Mermaid diagram.>

### Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
|        |      |      |

**Recommendation:** <option and reason>

### Architecture (CALM)

<Nodes, relationships and controls added or changed under `calm/`, or "No topology change.">

### Security

<Input validation, authentication, secrets, prompt-injection exposure.>

### Dependencies and configuration

<New packages with licence and `uv audit` result, new env vars and defaults, or "None.">

## Changes

| File | Change |
|------|--------|
|      |        |

## Steps

1. <Step> → verify: <command or check>
2. <Step> → verify: <command or check>

## Testing

- **Unit:** <tests to add or update>
- **Smoke:** <`tests/smoke/` change or baseline refresh, or "No end-to-end behaviour change.">

## Definition of done

- [ ] `uv run pytest` passes
- [ ] `uv run ruff check .` passes
- [ ] CALM validation passes (if `calm/` changed)
- [ ] Smoke suite updated (if end-to-end behaviour changed)
- [ ] README and affected skills updated
