"""Tests for the audit checks. Run with:  python -m pytest"""

import numpy as np
import pandas as pd
import pytest

from modelaudit import checks as c
from modelaudit.audit import run_audit, verdict_for
from modelaudit.config import Gates
from modelaudit.data import max_drawdown, portfolio_returns, sharpe

RNG = np.random.default_rng(7)


def market(n_days=1500, n_stocks=40, drift=0.0):
    dates = pd.bdate_range("2015-01-01", periods=n_days)
    tickers = [f"S{i:02d}" for i in range(n_stocks)]
    rets = pd.DataFrame(RNG.normal(drift, 0.015, (n_days, n_stocks)), dates, tickers)
    closes = 100 * (1 + rets).cumprod()
    return closes, rets


def long_frame(wide_df, value):
    out = wide_df.stack().rename(value).reset_index()
    out.columns = ["date", "ticker", value]
    return out


def test_portfolio_returns_uses_next_day_return():
    dates = pd.bdate_range("2024-01-01", periods=3)
    w = pd.DataFrame({"A": [1.0, 1.0, 1.0]}, dates)
    r = pd.DataFrame({"A": [0.10, 0.02, -0.01]}, dates)
    out = portfolio_returns(w, r, delay=1)
    assert list(out.round(4)) == [0.02, -0.01]


def test_costs_charge_turnover():
    dates = pd.bdate_range("2024-01-01", periods=3)
    w = pd.DataFrame({"A": [1.0, -1.0, -1.0]}, dates)
    r = pd.DataFrame({"A": [0.0, 0.0, 0.0]}, dates)
    out = portfolio_returns(w, r, delay=1, cost_bps=10)
    # flipping from +1 to -1 is turnover 2, charged on the day after the trade
    assert out.round(6).tolist() == [0.0, -0.002]


def test_sharpe_and_drawdown():
    s = pd.Series([0.01, -0.02, 0.01, 0.01])
    assert sharpe(pd.Series([0.0, 0.0]), 252) == 0.0
    assert max_drawdown(s) == pytest.approx(-0.02)


def test_verdict_rules():
    mk = lambda s: c.CheckResult("k", "t", s, "", {}, {})  # noqa: E731
    assert verdict_for([mk("PASS"), mk("PASS")]) == "PASS"
    assert verdict_for([mk("PASS"), mk("WARN")]) == "CONDITIONAL"
    assert verdict_for([mk("WARN"), mk("FAIL")]) == "FAIL"


def test_lookahead_flags_a_leak_and_passes_a_slow_signal():
    closes, rets = market()
    gates = Gates()
    leak = np.sign(rets.shift(-1)).fillna(0.0) / rets.shape[1]
    assert c.lookahead(leak, rets, gates).status == "FAIL"
    slow = np.sign(closes.shift(5) / closes.shift(120) - 1).fillna(0.0) / rets.shape[1]
    assert c.lookahead(slow, rets, gates).status == "PASS"


def test_integrity_fails_on_duplicates_and_bad_prices():
    closes, _ = market(200, 5)
    prices = long_frame(closes, "close")
    positions = long_frame(closes * 0 + 0.2, "weight")
    assert c.data_integrity(prices, positions, Gates()).status in {"PASS", "WARN"}
    bad = pd.concat([prices, prices.head(1)])
    bad.loc[bad.index[5], "close"] = -1
    result = c.data_integrity(bad, positions, Gates())
    assert result.status == "FAIL"


def test_unknown_gate_keys_are_rejected(tmp_path):
    path = tmp_path / "gates.json"
    path.write_text('{"min_net_sharp": 1.0}')
    with pytest.raises(ValueError):
        Gates.load(path)


def test_end_to_end_noise_strategy_does_not_pass():
    closes, rets = market()
    weights = pd.DataFrame(RNG.choice([-1.0, 1.0], rets.shape) / rets.shape[1], rets.index, rets.columns)
    result = run_audit(long_frame(closes, "close"), long_frame(weights, "weight"),
                       Gates(n_trials=20), "noise")
    assert result.verdict == "FAIL"
    data = result.to_json()
    assert data["verdict"] == "FAIL" and len(data["checks"]) == 8


def _book(rets, weight_fn):
    weights = pd.DataFrame(0.0, rets.index, rets.columns)
    for i in range(len(rets)):
        weights.iloc[i] = weight_fn(i)
    return weights


def test_exposure_passes_a_diversified_book_and_flags_mandate_breaches():
    _, rets = market(n_days=300, n_stocks=40)
    n = rets.shape[1]
    even = pd.DataFrame(1.0 / n, rets.index, rets.columns)
    net = portfolio_returns(even, rets, cost_bps=10)
    ok = c.exposure(even, rets, net, Gates())
    assert ok.metrics["max_gross_leverage"] == pytest.approx(1.0)
    assert ok.metrics["max_position_weight"] == pytest.approx(1 / n)
    assert ok.metrics["median_effective_names"] == pytest.approx(n)
    assert "gross leverage" not in ok.summary

    levered = even * 3.5  # 3.5x gross: above the 3x limit, below 1.5 x limit -> WARN
    assert c.exposure(levered, rets, portfolio_returns(levered, rets), Gates()).status == "WARN"
    very = even * 5.0  # above 1.5 x the limit -> FAIL
    assert c.exposure(very, rets, portfolio_returns(very, rets), Gates()).status == "FAIL"

    single = even.copy()
    single.iloc[:, 0] = 0.20  # one name at 20%: above 1.5 x the 10% limit
    result = c.exposure(single, rets, portfolio_returns(single, rets), Gates())
    assert result.status == "FAIL" and "single position" in result.summary


def test_exposure_warns_when_a_few_names_carry_the_result():
    dates = pd.bdate_range("2020-01-01", periods=260)
    tickers = [f"T{i}" for i in range(20)]
    rets = pd.DataFrame(0.0, dates, tickers)
    rets.iloc[1:, :3] = 0.002  # only three names ever make money
    weights = pd.DataFrame(1.0 / 20, dates, tickers)
    net = portfolio_returns(weights, rets)
    result = c.exposure(weights, rets, net, Gates())
    assert result.status == "WARN"
    assert result.metrics["top5_names_pnl_share"] == pytest.approx(1.0)
    assert set(result.metrics["top5_names"][:3]) == {"T0", "T1", "T2"}


def test_exposure_warns_when_the_result_needs_a_few_lucky_days():
    dates = pd.bdate_range("2020-01-01", periods=500)
    rets = pd.DataFrame({"A": -0.0005, "B": -0.0005}, dates)
    rets.iloc[[50, 150, 250, 350, 450], :] = 0.08  # five big days rescue an otherwise losing book
    weights = pd.DataFrame(0.05, dates, ["A", "B"])
    net = portfolio_returns(weights, rets)
    result = c.exposure(weights, rets, net, Gates())
    assert result.metrics["net_log_return"] > 0
    assert result.metrics["net_log_return_without_best_1pct_days"] < 0
    assert result.status == "WARN" and "best" in result.summary


def test_sharpe_interval_is_reproducible_and_brackets_the_estimate():
    _, rets = market(n_days=1000, n_stocks=1, drift=0.0008)
    series = rets.iloc[:, 0]
    low, high = c.sharpe_interval(series, 252, block=20)
    assert (low, high) == c.sharpe_interval(series, 252, block=20)
    assert low < sharpe(series, 252) < high
    assert np.isnan(c.sharpe_interval(series.iloc[:10], 252, block=20)[0])


def test_report_lists_fixes_for_flagged_checks():
    from modelaudit.report import render_html

    closes, rets = market(n_days=400, n_stocks=20)
    weights = pd.DataFrame(0.25, rets.index, rets.columns)  # 5x gross, 25% per name
    result = run_audit(long_frame(closes, "close"), long_frame(weights, "weight"), Gates(), "levered")
    page = render_html(result)
    assert "What to fix first" in page and "Exposure and concentration" in page
    assert "Exposure over time" not in page or "data:image/png" in page
