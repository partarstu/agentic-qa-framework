# Plan: Parallel focused reviews in Requirements Review

Status: approved by the user on 2026-09-26. Implement with the `implementing-changes` skill.

## Goal

The main agent selects up to N focus areas per story (N configurable, default 5); the review tool runs one reviewer sub-agent per focus area in parallel on the same prepared material, and a separate merge sub-agent merges their reviews into the single `RequirementsReviewFeedback` that is posted and returned.

## Architecture

No architecture change: the reviewer runs and the merge step are sub-agents inside the existing Requirements Review service, using the existing model edge and the existing prompt-injection screening in `CustomLlmWrapper`. No CALM update needed.

## Design

- **`config.py`**: new `RequirementsReviewAgentConfig.FOCUS_AREA_COUNT = _optional_positive_int("REQUIREMENTS_REVIEW_FOCUS_AREA_COUNT") or 5`; an invalid value fails at startup through the existing helper.
- **`agents/requirements_review/main.py`**:
    - Both review tools (`_review_with_attachments`, `_review_with_reference_documentation`) take `focus_areas: list[str]`, documented in their docstrings (the docstring is the tool specification the LLM reads).
    - Validation: 1..`FOCUS_AREA_COUNT` items and no blank item, otherwise `ModelRetry` (same pattern as the existing blank `retrieval_query` check); each item is truncated with the existing `_capped`.
    - Attachments are downloaded and documentation retrieved once, as today; `_run_review` then runs the existing `self.review_agent` once per focus area with `asyncio.gather(..., return_exceptions=True)` (the pattern in `common/services/document_retrieval.py:170`), prepending the focus area to that reviewer's copy of the prepared message parts. One agent instance is reused: Pydantic AI agents are stateless and safe for concurrent runs.
    - Every reviewer run and the merge run get their own `usage_limits=UsageLimits(total_tokens_limit=config.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK)`; the cap is per run, not shared. Pydantic AI's default `request_limit=50` per run stays in effect.
    - New `self.merge_agent` created with `CustomLlmWrapper.create_agent`, `output_type=RequirementsReviewFeedback`, `name="merge_reviews"` (its usage operation name), same model and thinking level as the reviewer. Its input is only the successful reviews' `suggested_improvements`, each labelled with its focus area; no attachments or documentation.
- **Partial failure**:
    - Each failed reviewer (including `UsageLimitExceeded`) is logged with `logger.error`, naming its focus area, with `exc_info` set to the exception; one summary log line states how many of the N reviews succeeded.
    - The review continues with the successful reviews; application code (not the LLM) appends a note to `suggested_improvements` naming the focus areas that were not reviewed because of an error.
    - Only when every reviewer fails does the tool fail, re-raising the first reviewer's exception so the existing provider-retry handling in `AgentBase._get_agent_execution_result` still applies.
    - Exactly one successful review skips the merge call and is returned directly (with the note when applicable).
    - A failed merge fails the tool.
- **Prompts** (`agents/requirements_review/prompt.py` and `system_prompts/`):
    - `main_prompt_template.md`: new `{focus_area_count}` placeholder, filled by `RequirementsReviewSystemPrompt.get_prompt()` with `self.template.format(...)` (as in `agents/test_case_classification/prompt.py`). New step after fetching the issue: based on the story's content, select up to `{focus_area_count}` of the most important review focus areas and pass them to the review tool. Keep posting the received feedback in its original form.
    - `review_with_attachments_prompt.md`: the reviewer gets one focus area; it reviews that focus in depth and still reports any serious issue it notices outside it.
    - New `merge_reviews_prompt.md` with its prompt class: merge findings about the same issue, keep every unique finding even when only one reviewer raised it, drop nothing for lack of agreement, order by importance, return a plain-text list.
- **Decision (merge location)**: merging runs inside the review tool, not in the main agent, so the main agent's context holds only the final feedback and the merge input stays small.
- **Decision (diversity)**: focused reviews chosen per story, not identical repeated reviews, because same-model same-prompt runs share blind spots; global `TEMPERATURE` stays unchanged.

## Workflows

**Logic flow:**

1. Orchestrator sends "Review the Jira user story X" → main agent fetches the issue (MCP) and selects up to N focus areas.
2. Main agent calls the review tool (issue key, issue content, focus areas, retrieval query when retrieval is enabled) → tool downloads attachments and retrieves documentation once.
3. Tool runs one reviewer per focus area in parallel → logs and skips failures → merges the successful reviews (merge skipped for a single success) → appends the unreviewed-focus note when needed.
4. Main agent posts the comment and returns the feedback.

**Data flow:** each reviewer returns `RequirementsReviewFeedback`; the merger receives their `suggested_improvements` labelled by focus area and returns one `RequirementsReviewFeedback`. The public output model and the A2A contract are unchanged.

## Impact

- **Smoke suite**:
    - `tests/smoke/overrides/agents/requirements_review/system_prompts/main_prompt_template.md` gets the same `{focus_area_count}` placeholder (overrides must match the bundled placeholders) and the new step, keeping the override marker.
    - `docker-compose.smoke.yml`: `REQUIREMENTS_REVIEW_FOCUS_AREA_COUNT: "2"` on the `requirements_review` service, to keep the smoke run cheap while exercising parallel reviews and the merge.
    - `tests/smoke/test_smoke.py`: new assertion, modelled on `test_usage_artifact_carries_per_operation_counters`, that the requirements review task's usage artifact has `main`, `review_with_attachments` with at least 1 request, and `merge_reviews` with at least 1 request when at least 2 reviews ran.
    - Review output changes intentionally: compare against `tests/smoke/baselines/default.json`, then refresh it with `SMOKE_WRITE_BASELINE=1 SMOKE_BASELINE_NAME=default uv run pytest tests/smoke -m smoke`.
- **Configuration**: `REQUIREMENTS_REVIEW_FOCUS_AREA_COUNT=5 # Default: 5.` documented in the README *Environment Variables* block.
- **Security**: focus areas come from the LLM and are validated for count, checked for blanks and length-capped; reviewer and merge inputs are screened by the existing wrapper.
- **Cost and latency**: about N times today's review tokens plus one small merge call; latency about the slowest reviewer plus the merge. Worst case per task is about (N + 1) × `TOTAL_TOKENS_LIMIT_PER_TASK` for the sub-agents; the cap is per run by the user's decision.
- **Version**: Requirements Review `1.1.2` → `1.2.0` (MINOR: new capability, changed prompts) in `config.py` and the README; orchestrator unchanged.

## TODO

- [ ] Config setting, tool argument, validation and parallel `_run_review` with per-run token cap → verify: unit tests in `tests/agents/test_requirements_review_tool.py` for count and blank validation, one reviewer run per focus area with the focus in its message, material prepared once, and `usage_limits` passed to every run.
- [ ] Partial-failure handling → verify: tests for a logged failure plus the unreviewed-focus note, a reviewer exceeding the token cap being skipped, all reviewers failing re-raising the first error, and a single success skipping the merge.
- [ ] Merge sub-agent and prompt, main and reviewer prompt changes → verify: the merger receives the labelled reviews, the main prompt renders with `focus_area_count`, and `tests/agents/test_requirements_review.py` still passes.
- [ ] Smoke override, compose setting, usage assertion and baseline refresh → verify: `uv run pytest tests/smoke -m smoke -v` green with the stack up; stack torn down with `docker compose -f docker-compose.smoke.yml down -v`.
- [ ] README and version bump → verify: `ruff check`, `ruff format --check`, the full unit suite and CALM validation pass.
