"""What each flagged check means and what to do about it, in plain English.

Shared by the HTML report ("What to fix first") and the rule-based explainer, which is also the
fallback whenever the Foundry model is unavailable. Each entry is (explanation, suggested action);
{summary} is replaced by the check's own one-line summary.
"""

from __future__ import annotations

RULES: dict[str, tuple[str, str]] = {
    "data_integrity": (
        "The input data has problems that can distort any result: {summary}",
        "Fix the listed data issues (adjust prices for splits and dividends, include delisted stocks, "
        "remove duplicates) and resubmit before reading the other checks.",
    ),
    "lookahead": (
        "Performance drops sharply when every trade is delayed by one day, which is the typical "
        "sign that the strategy uses information it would not have had in time: {summary}",
        "Check every feature and join for future data (for example .shift(-1), or joining on the "
        "wrong date) and make sure each weight uses only data available at that day's close.",
    ),
    "costs": (
        "The edge does not survive realistic trading costs: {summary}",
        "Trade less often, add a turnover limit, or confirm that the assumed cost per trade is "
        "realistic for the size and liquidity you trade.",
    ),
    "walk_forward": (
        "Returns are not consistent across time; most of the result comes from a few periods: {summary}",
        "Find out what drove the strong windows and whether those conditions can be expected to recur.",
    ),
    "deflated_sharpe": (
        "Once the number of variants tried is taken into account, the Sharpe ratio may be luck: {summary}",
        "Report the true number of variants tried, and confirm the result on data that was not "
        "used to choose the strategy.",
    ),
    "risk": (
        "The worst loss is outside the agreed limit: {summary}",
        "Reduce position sizes or add risk controls until the drawdown fits the limit.",
    ),
    "exposure": (
        "The positions break the agreed limits, or the result depends on very few names or days: {summary}",
        "Confirm the leverage and position limits in the mandate, cap position sizes, and check whether "
        "the result still holds without the few names or days that drive it.",
    ),
    "benchmark": (
        "The strategy does not clearly beat simply holding the benchmark: {summary}",
        "Compare against the benchmark after costs and decide whether the extra complexity is worth it.",
    ),
}


def remediation(key: str, summary: str) -> tuple[str, str]:
    text, action = RULES.get(key, ("{summary}", "Review this check with the auditor."))
    return text.format(summary=summary), action
