"""The audit checks. Each returns a CheckResult with a PASS/WARN/FAIL status."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from modelaudit.config import Gates
from modelaudit.data import max_drawdown, portfolio_returns, sharpe, wide

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class CheckResult:
    key: str
    title: str
    status: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    series: dict[str, Any] = field(default_factory=dict)  # data for charts, not serialized


def data_integrity(prices: pd.DataFrame, positions: pd.DataFrame, gates: Gates) -> CheckResult:
    issues, warnings = [], []
    dup_prices = int(prices.duplicated(["date", "ticker"]).sum())
    dup_positions = int(positions.duplicated(["date", "ticker"]).sum())
    if dup_prices:
        issues.append(f"{dup_prices} duplicate price rows")
    if dup_positions:
        issues.append(f"{dup_positions} duplicate position rows")
    bad_prices = int((prices["close"] <= 0).sum())
    if bad_prices:
        issues.append(f"{bad_prices} zero or negative prices")
    blank_prices = int(prices["close"].isna().sum())
    if blank_prices:
        warnings.append(f"{blank_prices} blank price rows")

    closes = wide(prices, "close")
    rets = closes.pct_change(fill_method=None)
    big_moves = int((rets.abs() > gates.max_abs_daily_move).sum().sum())
    if big_moves:
        warnings.append(f"{big_moves} daily moves above {gates.max_abs_daily_move:.0%} (unadjusted splits?)")

    held = positions[positions["weight"].abs() > 0]
    no_price = held.merge(prices[["date", "ticker"]], on=["date", "ticker"], how="left", indicator=True)
    no_price = int((no_price["_merge"] == "left_only").sum())
    if no_price:
        warnings.append(f"{no_price} held positions have no price that day")

    observed = closes.notna()
    first, last = observed.idxmax(), observed[::-1].idxmax()
    span_start, span_end = closes.index.min(), closes.index.max()
    exits = int((last < span_end).sum())
    entries = int((first > span_start).sum())
    if exits == 0 and entries == 0 and closes.shape[1] >= 10:
        warnings.append("No ticker enters or leaves the universe: possible survivorship bias")

    in_life = observed.cumsum().gt(0) & observed[::-1].cumsum()[::-1].gt(0)
    missing = float((~observed & in_life).sum().sum() / max(in_life.sum().sum(), 1))
    if missing > gates.max_missing_fraction:
        warnings.append(f"{missing:.1%} of prices missing inside tickers' lifetimes")

    status = FAIL if issues else (WARN if warnings else PASS)
    text = "; ".join(issues + warnings) or "No integrity problems found."
    return CheckResult("data_integrity", "Data integrity", status, text, {
        "tickers": int(closes.shape[1]), "dates": int(closes.shape[0]),
        "start": str(span_start.date()), "end": str(span_end.date()),
        "tickers_entering": entries, "tickers_leaving": exits,
        "missing_fraction": round(missing, 4), "large_moves": big_moves,
        "duplicate_price_rows": dup_prices, "duplicate_position_rows": dup_positions,
    })


def lookahead(weights: pd.DataFrame, returns: pd.DataFrame, gates: Gates) -> CheckResult:
    """Delay test: honest signals decay gradually when execution is delayed; leaked ones fall off a cliff."""
    per = gates.periods_per_year
    by_delay = {d: sharpe(portfolio_returns(weights, returns, delay=d), per) for d in (1, 2, 3, 5)}
    s1, s2, s3 = by_delay[1], by_delay[2], by_delay[3]
    ratio = s2 / s1 if s1 > 0 else float("nan")
    first_drop, later_drop = s1 - s2, max(s2 - s3, 0.0)
    # A leak shows one large drop at the first extra day of delay and then levels off;
    # a genuine signal fades smoothly (or not at all for slow signals).
    cliff = first_drop > 1.0 and first_drop > 3 * max(later_drop, 0.1)
    implausible = s1 > gates.lookahead_max_sharpe
    collapse = s1 > 1.0 and ratio == ratio and ratio < gates.lookahead_min_decay_ratio
    reasons = []
    if cliff or collapse:
        reasons.append(f"Sharpe drops from {s1:.2f} to {s2:.2f} with one extra day of delay, "
                       f"then levels off ({s3:.2f} at 3 days)")
    if implausible:
        reasons.append(f"gross Sharpe {s1:.1f} is implausibly high for this kind of strategy")
    # A cliff alone can also be a genuinely fast signal (e.g. one-day reversal), so it is a
    # warning; a cliff together with an implausibly high Sharpe is treated as a leak.
    status = FAIL if ((cliff or collapse) and implausible) else (WARN if reasons else PASS)
    lead = ("Likely look-ahead bias: " if status == FAIL else
            "Possible look-ahead bias, or a very fast signal (confirm when each signal is known): ")
    text = (lead + "; ".join(reasons)) if reasons else \
        "Performance decays gradually with execution delay, as expected for a genuine signal."
    return CheckResult("lookahead", "Look-ahead / leakage (delay test)", status, text,
                       {"sharpe_by_delay": {str(k): round(v, 3) for k, v in by_delay.items()},
                        "decay_ratio_delay2_over_delay1": None if ratio != ratio else round(ratio, 3)},
                       {"by_delay": by_delay})


def costs(weights: pd.DataFrame, returns: pd.DataFrame, gates: Gates) -> CheckResult:
    per = gates.periods_per_year
    aligned = weights.reindex(index=returns.index, columns=returns.columns).ffill().fillna(0.0)
    turnover = float(aligned.diff().abs().sum(axis=1).mean())
    grid = {float(c): sharpe(portfolio_returns(weights, returns, cost_bps=c), per) for c in gates.cost_grid_bps}
    gross = portfolio_returns(weights, returns)
    gross_daily = float(gross.mean())
    breakeven = gross_daily / turnover * 1e4 if turnover > 0 else float("inf")
    edge_text = (f"break-even cost {breakeven:.1f} bps" if breakeven > 0
                 else "no edge even before costs")
    net = portfolio_returns(weights, returns, cost_bps=gates.cost_bps)
    net_sharpe = sharpe(net, per)
    status = PASS if net_sharpe >= gates.min_net_sharpe else (
        WARN if net_sharpe >= 0.8 * gates.min_net_sharpe else FAIL)
    text = (f"Net Sharpe {net_sharpe:.2f} at {gates.cost_bps:g} bps (gate {gates.min_net_sharpe:g}); "
            f"daily turnover {turnover:.1%}; {edge_text}.")
    return CheckResult("costs", "Transaction-cost realism", status, text, {
        "daily_turnover": round(turnover, 4), "annual_turnover": round(turnover * per, 2),
        "breakeven_cost_bps": None if breakeven == float("inf") else round(breakeven, 2),
        "net_sharpe_at_gate_cost": round(net_sharpe, 3),
        "sharpe_by_cost_bps": {f"{k:g}": round(v, 3) for k, v in grid.items()},
    }, {"grid": grid})


def walk_forward(net: pd.Series, gates: Gates) -> CheckResult:
    per = gates.periods_per_year
    clean = net.dropna()
    bounds = np.linspace(0, len(clean), gates.folds + 1).astype(int)
    chunks = [clean.iloc[a:b] for a, b in zip(bounds[:-1], bounds[1:])]
    folds = [{"start": str(c.index[0].date()), "end": str(c.index[-1].date()),
              "sharpe": round(sharpe(c, per), 3), "return": round(float((1 + c).prod() - 1), 4)}
             for c in chunks if len(c) > 1]
    positive = sum(f["sharpe"] > 0 for f in folds) / max(len(folds), 1)
    worst = min((f["sharpe"] for f in folds), default=0.0)
    status = PASS if positive >= gates.min_positive_fold_fraction else (WARN if positive >= 0.5 else FAIL)
    text = (f"{positive:.0%} of {len(folds)} sequential windows are profitable after costs "
            f"(gate {gates.min_positive_fold_fraction:.0%}); worst window Sharpe {worst:.2f}.")
    return CheckResult("walk_forward", "Stability across time (walk-forward windows)", status, text,
                       {"positive_fraction": round(positive, 3), "worst_fold_sharpe": worst, "folds": folds},
                       {"folds": folds})


def deflated_sharpe(net: pd.Series, gates: Gates) -> CheckResult:
    """Bailey & Lopez de Prado (2014): probability the true Sharpe exceeds what the best of
    n_trials random strategies would show by luck."""
    x = net.dropna().to_numpy()
    t = len(x)
    sr = x.mean() / x.std(ddof=1) if t > 1 and x.std(ddof=1) > 0 else 0.0
    skew, kurt = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    sigma = np.sqrt(max((1 - skew * sr + (kurt - 1) / 4 * sr**2) / max(t - 1, 1), 1e-12))
    n = max(gates.n_trials, 1)
    if n > 1:
        euler = 0.5772156649
        expected_max = (1 - euler) * stats.norm.ppf(1 - 1 / n) + euler * stats.norm.ppf(1 - 1 / (n * np.e))
    else:
        expected_max = 0.0
    sr0 = sigma * expected_max
    prob = float(stats.norm.cdf((sr - sr0) / sigma))
    status = PASS if prob >= gates.min_deflated_sharpe_prob else (WARN if prob >= 0.5 else FAIL)
    text = (f"Probability the edge is real after {n} declared trial(s): {prob:.1%} "
            f"(gate {gates.min_deflated_sharpe_prob:.0%}).")
    return CheckResult("deflated_sharpe", "Overfitting (deflated Sharpe ratio)", status, text, {
        "n_trials": n, "observations": t, "annualized_sharpe": round(sr * np.sqrt(gates.periods_per_year), 3),
        "skew": round(skew, 3), "kurtosis": round(kurt, 3),
        "luck_threshold_annualized": round(sr0 * np.sqrt(gates.periods_per_year), 3),
        "probability_real": round(prob, 4),
    })


def risk(net: pd.Series, gates: Gates) -> CheckResult:
    dd = max_drawdown(net)
    worst_day = float(net.min())
    status = PASS if dd >= gates.max_drawdown else (WARN if dd >= gates.max_drawdown * 1.5 else FAIL)
    text = f"Maximum drawdown {dd:.1%} (gate {gates.max_drawdown:.0%}); worst day {worst_day:.1%}."
    return CheckResult("risk", "Drawdown and tail risk", status, text,
                       {"max_drawdown": round(dd, 4), "worst_day": round(worst_day, 4)})


def benchmark(net: pd.Series, returns: pd.DataFrame, gates: Gates) -> CheckResult:
    per = gates.periods_per_year
    if gates.benchmark_ticker and gates.benchmark_ticker in returns.columns:
        bench, name = returns[gates.benchmark_ticker], gates.benchmark_ticker
        universe = returns.drop(columns=[gates.benchmark_ticker])
    else:
        universe = returns
        bench, name = universe.mean(axis=1), "equal-weight universe"
    bench = bench.reindex(net.index).fillna(0.0)
    active = net - bench
    ir = sharpe(active, per)
    cov = np.cov(net, bench)
    beta = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 0 else 0.0
    status = PASS if ir > 0 else WARN
    text = (f"Information ratio vs {name}: {ir:.2f}; beta {beta:.2f}; "
            f"strategy Sharpe {sharpe(net, per):.2f} vs benchmark {sharpe(bench, per):.2f}.")
    return CheckResult("benchmark", "Value over a simple benchmark", status, text,
                       {"benchmark": name, "information_ratio": round(ir, 3), "beta": round(beta, 3),
                        "benchmark_sharpe": round(sharpe(bench, per), 3)},
                       {"benchmark_returns": bench})
