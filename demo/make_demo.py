"""Builds the public demo: a synthetic 80-stock market (2015-2024, with listings and
delistings) and three example strategies with different, known flaws.

Synthetic data is used on purpose: it can be shared freely (no market-data licence), and
because we built it, we know which strategy is honest and which one cheats.

    python demo/make_demo.py      -> demo/data/*.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent / "data"
RNG = np.random.default_rng(20241113)
N_STOCKS, START, END = 80, "2015-01-01", "2024-12-31"


def make_market() -> pd.DataFrame:
    dates = pd.bdate_range(START, END)
    n_days = len(dates)
    market = RNG.normal(0.0003, 0.010, n_days)
    # Slowly varying stock-specific drift: the persistent part that momentum can detect.
    drift = np.zeros((n_days, N_STOCKS))
    for t in range(1, n_days):
        drift[t] = 0.995 * drift[t - 1] + RNG.normal(0, 0.00008, N_STOCKS)
    beta = RNG.uniform(0.7, 1.3, N_STOCKS)
    shocks = RNG.normal(0, 0.017, (n_days, N_STOCKS))
    # Small short-term overreaction: part of each day's move reverses the next day.
    noise = shocks.copy()
    noise[1:] -= 0.04 * shocks[:-1]
    returns = drift + market[:, None] * beta + noise
    prices = 50 * np.exp(np.cumsum(returns, axis=0))
    frame = pd.DataFrame(prices, index=dates, columns=[f"STK{i:02d}" for i in range(N_STOCKS)])
    # Realistic universe: 10 stocks list late, 10 delist early (avoids survivorship bias).
    for i in range(10):
        frame.iloc[: RNG.integers(250, 1000), i] = np.nan
        frame.iloc[RNG.integers(1500, 2400):, N_STOCKS - 1 - i] = np.nan
    frame["SPY"] = 200 * np.exp(np.cumsum(market))
    long = frame.stack().dropna().rename("close").reset_index()
    long.columns = ["date", "ticker", "close"]
    return long


def long_short(score: pd.DataFrame, rebalance_every: int, quantile: float = 0.2,
               tradable: pd.DataFrame | None = None) -> pd.DataFrame:
    ranks = score.rank(axis=1, pct=True)
    longs = (ranks >= 1 - quantile).astype(float)
    shorts = (ranks <= quantile).astype(float)
    weights = longs.div(longs.sum(axis=1), axis=0) * 0.5 - shorts.div(shorts.sum(axis=1), axis=0) * 0.5
    weights = weights.fillna(0.0)
    keep = np.arange(len(weights)) % rebalance_every == 0
    held = weights.where(pd.Series(keep, index=weights.index), np.nan).ffill().fillna(0.0)
    if tradable is not None:
        # Exit a position as soon as the stock stops trading (delisting), instead of holding a ghost.
        held = held.where(tradable, 0.0)
    return held


def to_long(weights: pd.DataFrame) -> pd.DataFrame:
    out = weights.stack().rename("weight").reset_index()
    out.columns = ["date", "ticker", "weight"]
    return out[out["weight"] != 0]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prices = make_market()
    closes = prices.pivot(index="date", columns="ticker", values="close").drop(columns="SPY")
    rets = closes.pct_change(fill_method=None)

    # 1) Honest 6-month momentum (skip last week), weekly rebalance. Uses data up to today's close only.
    momentum = closes.shift(5) / closes.shift(126) - 1
    honest = long_short(momentum, rebalance_every=5, tradable=closes.notna())

    # 2) Leaky: same strategy, but the score secretly includes TOMORROW's return (look-ahead bug,
    #    e.g. a feature computed with .shift(-1) or a join on the wrong date).
    leaky_score = momentum.rank(axis=1, pct=True) + 0.6 * rets.shift(-1).rank(axis=1, pct=True)
    leaky = long_short(leaky_score, rebalance_every=1, tradable=closes.notna())

    # 2b) Leak fixed: the same score with the bug removed. rets.shift(-1) became rets, the return
    #     already known at today's close. The audit then shows what the strategy is really worth.
    fixed_score = momentum.rank(axis=1, pct=True) + 0.6 * rets.rank(axis=1, pct=True)
    fixed = long_short(fixed_score, rebalance_every=1, tradable=closes.notna())

    # 3) Cost-fragile: 1-day reversal traded every day. Looks fine before costs, not after.
    reversal = -rets
    fragile = long_short(reversal, rebalance_every=1, quantile=0.1, tradable=closes.notna())

    prices.to_csv(OUT / "prices.csv", index=False, float_format="%.4f")
    for name, weights in (("honest_momentum", honest), ("leaky_momentum", leaky),
                          ("leaky_momentum_fixed", fixed),
                          ("high_turnover_reversal", fragile)):
        to_long(weights).to_csv(OUT / f"positions_{name}.csv", index=False, float_format="%.6f")
    print(f"Demo data written to {OUT}")


if __name__ == "__main__":
    main()
