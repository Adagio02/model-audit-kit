"""Input loading and the return contract.

Contract (stated in every report):
- prices: one row per (date, ticker) with an adjusted close.
- positions: target weights decided at the CLOSE of `date`, using only information
  available at that close. They earn the NEXT period's return.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise(frame: pd.DataFrame, value: str, name: str) -> pd.DataFrame:
    frame = frame.rename(columns={c: c.strip().lower() for c in frame.columns})
    missing = {"date", "ticker", value} - set(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")
    frame = frame[["date", "ticker", value]].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame[value] = pd.to_numeric(frame[value], errors="coerce")
    return frame


def load_prices(path: str | Path) -> pd.DataFrame:
    return _normalise(pd.read_csv(path), "close", "prices")


def load_positions(path: str | Path) -> pd.DataFrame:
    return _normalise(pd.read_csv(path), "weight", "positions")


def wide(frame: pd.DataFrame, value: str) -> pd.DataFrame:
    deduped = frame.drop_duplicates(["date", "ticker"], keep="last")
    return deduped.pivot(index="date", columns="ticker", values=value).sort_index()


def portfolio_returns(weights: pd.DataFrame, returns: pd.DataFrame, delay: int = 1,
                      cost_bps: float = 0.0) -> pd.Series:
    """Daily portfolio return when weights set at t earn the return of t+delay, net of costs."""
    weights = weights.reindex(index=returns.index, columns=returns.columns).ffill().fillna(0.0)
    gross = (weights.shift(delay) * returns).sum(axis=1)
    turnover = weights.diff().abs().sum(axis=1).shift(delay).fillna(0.0)
    return (gross - turnover * cost_bps / 1e4).iloc[delay:]


def sharpe(series: pd.Series, periods: int) -> float:
    series = series.dropna()
    if len(series) < 2 or series.std(ddof=1) == 0:
        return 0.0
    return float(series.mean() / series.std(ddof=1) * np.sqrt(periods))


def max_drawdown(series: pd.Series) -> float:
    equity = (1 + series.fillna(0)).cumprod()
    return float((equity / equity.cummax() - 1).min())
