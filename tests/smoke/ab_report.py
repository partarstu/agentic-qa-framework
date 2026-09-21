# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""The self-contained HTML report of an A/B comparison, readable offline from the CI artifact."""

import re
from dataclasses import dataclass
from html import escape

from tests.smoke import judge
from tests.smoke.artifacts import MetricRegression, RunSnapshot

_RESULT_LABELS: dict[judge.Outcome, str] = {
    "much_better": "IMPROVED",
    "better": "IMPROVED",
    "same": "OK",
    "worse": "WARNING",
    "much_worse": "REGRESSION",
    "inconsistent": "INCONSISTENT",
}
_TONES: dict[str, str] = {
    "IMPROVED": "good",
    "OK": "neutral",
    "WARNING": "warn",
    "REGRESSION": "bad",
    "INCONSISTENT": "neutral",
    "PASSED": "good",
    "PASSED WITH WARNINGS": "warn",
    "FAILED": "bad",
}
_BOLD = re.compile(r"\*\*(.+?)\*\*")

_STYLE = """
:root {
  --bg: #f6f7f9; --surface: #ffffff; --border: #e2e5ea; --text: #1d2330; --muted: #5d6675;
  --good: #1a7f4b; --good-bg: #e3f4ea; --warn: #9a6200; --warn-bg: #fdf1d8;
  --bad: #b42331; --bad-bg: #fbe4e6; --neutral: #4a5363; --neutral-bg: #eceef2;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171c; --surface: #1c2027; --border: #2d333d; --text: #e6e9ee; --muted: #9aa3b2;
    --good: #5fd08f; --good-bg: #173524; --warn: #f0b84a; --warn-bg: #3a2c10;
    --bad: #ff7b86; --bad-bg: #3d1a1f; --neutral: #b7bfcc; --neutral-bg: #2a303a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 40px 0 14px; }
.header { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; }
.meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin-top: 20px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; }
.meta .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }
.meta .value { font-weight: 600; overflow-wrap: anywhere; }
.meta .sub { color: var(--muted); font-size: 13px; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; letter-spacing: .04em; white-space: nowrap; }
.badge.big { font-size: 15px; padding: 6px 16px; }
.good { color: var(--good); background: var(--good-bg); }
.warn { color: var(--warn); background: var(--warn-bg); }
.bad { color: var(--bad); background: var(--bad-bg); }
.neutral { color: var(--neutral); background: var(--neutral-bg); }
.dimensions { display: grid; gap: 14px; }
.dimension { border-left: 4px solid var(--border); }
.edge-good { border-left-color: var(--good); } .edge-warn { border-left-color: var(--warn); }
.edge-bad { border-left-color: var(--bad); }
.dimension-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.dimension-head h3 { margin: 0; font-size: 16px; }
.orders { display: flex; flex-wrap: wrap; gap: 8px 24px; margin: 10px 0 4px; color: var(--muted); font-size: 14px; }
.orders b { color: var(--text); }
details { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; }
summary { cursor: pointer; color: var(--muted); font-size: 14px; }
.rationale { white-space: pre-wrap; margin: 10px 0 0; font-size: 14px; }
.rationale h4 { margin: 0 0 4px; font-size: 13px; color: var(--muted); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
th, td { padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--border); }
th { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.regressed td { background: var(--bad-bg); }
.up { color: var(--good); } .down { color: var(--bad); font-weight: 700; }
"""


@dataclass(slots=True)
class AbResult:
    """The full comparison of the candidate run against the baseline."""

    baseline_metrics: dict[str, dict[str, float]]
    candidate_metrics: dict[str, dict[str, float]]
    metric_regressions: list[MetricRegression]
    comparisons: list[judge.Comparison]


def render_html(baseline_name: str, baseline: RunSnapshot, candidate: RunSnapshot, result: AbResult) -> str:
    status = _overall_status(result)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smoke A/B report</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<div class="header"><h1>Smoke A/B report</h1>{_badge(status, big=True)}</div>
<div class="meta">
{_meta_card("Baseline", baseline_name, f"{escape(baseline.label)}<br>captured {escape(baseline.captured_at)}")}
{_meta_card("Candidate", candidate.label, f"captured {escape(candidate.captured_at)}")}
{_meta_card("Judge", judge.JUDGE_MODEL_NAME, "blinded, judged in both orders")}
</div>
<h2>Judged quality</h2>
<div class="dimensions">
{"".join(_dimension_card(comparison) for comparison in result.comparisons)}
</div>
<h2>Metrics</h2>
{_metrics_table(result)}
</main>
</body>
</html>
"""


def _overall_status(result: AbResult) -> str:
    if result.metric_regressions or any(comparison.regressed for comparison in result.comparisons):
        return "FAILED"
    if any(comparison.degraded for comparison in result.comparisons):
        return "PASSED WITH WARNINGS"
    return "PASSED"


def _badge(label: str, big: bool = False) -> str:
    return f'<span class="badge {_TONES[label]}{" big" if big else ""}">{escape(label)}</span>'


def _meta_card(label: str, value: str, sub_html: str) -> str:
    return (
        f'<div class="card"><div class="label">{label}</div>'
        f'<div class="value">{escape(value)}</div><div class="sub">{sub_html}</div></div>'
    )


def _dimension_card(comparison: judge.Comparison) -> str:
    result = _RESULT_LABELS[comparison.outcome]
    return f"""<section class="card dimension edge-{_TONES[result]}">
<div class="dimension-head"><h3>{escape(comparison.dimension)}</h3>{_badge(result)}</div>
<div class="orders">
<span>Candidate as Output B: <b>{escape(comparison.forward)}</b></span>
<span>Candidate as Output A: <b>{escape(comparison.swapped)}</b></span>
<span>Outcome: <b>{escape(comparison.outcome)}</b></span>
</div>
<details{" open" if comparison.regressed or comparison.degraded else ""}>
<summary>Judge rationale</summary>
<div class="rationale"><h4>Candidate as Output B</h4>{_rationale_html(comparison.forward_rationale)}</div>
<div class="rationale"><h4>Candidate as Output A</h4>{_rationale_html(comparison.swapped_rationale)}</div>
</details>
</section>
"""


def _rationale_html(rationale: str) -> str:
    """Escape the judge's text and keep the bold emphasis it writes in Markdown."""
    return _BOLD.sub(r"<strong>\1</strong>", escape(rationale.strip()))


def _metrics_table(result: AbResult) -> str:
    regressed = {(regression.dimension, regression.metric) for regression in result.metric_regressions}
    rows = []
    for dimension, metrics in result.baseline_metrics.items():
        for metric, baseline_value in metrics.items():
            candidate_value = result.candidate_metrics.get(dimension, {}).get(metric, 0.0)
            delta = candidate_value - baseline_value
            is_regressed = (dimension, metric) in regressed
            delta_tone = "down" if is_regressed else "up" if delta > 0 else ""
            rows.append(
                f'<tr class="{"regressed" if is_regressed else ""}">'
                f"<td>{escape(dimension)}</td><td>{escape(metric)}</td>"
                f'<td class="num">{baseline_value:.2f}</td><td class="num">{candidate_value:.2f}</td>'
                f'<td class="num delta {delta_tone}">{delta:+.2f}</td></tr>'
            )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Dimension</th><th>Metric</th>'
        '<th class="num">Baseline</th><th class="num">Candidate</th><th class="num">Delta</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )
