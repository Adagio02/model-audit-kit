"""Audit gates. Fixed BEFORE an audit runs and recorded in the report."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Gates:
    periods_per_year: int = 252
    cost_bps: float = 10.0                 # one-way cost per unit of turnover, in basis points
    cost_grid_bps: tuple = (0, 5, 10, 25, 50)
    min_net_sharpe: float = 0.5            # annualized, after cost_bps
    max_drawdown: float = -0.25            # most negative acceptable drawdown
    folds: int = 5                         # contiguous walk-forward evaluation windows
    min_positive_fold_fraction: float = 0.6
    n_trials: int = 1                      # strategy variants the client tried (for the deflated Sharpe)
    min_deflated_sharpe_prob: float = 0.95
    lookahead_max_sharpe: float = 4.0      # higher annualized Sharpe is implausible for daily equity strategies
    lookahead_min_decay_ratio: float = 0.30  # Sharpe(delay 2) / Sharpe(delay 1); a cliff signals look-ahead
    max_abs_daily_move: float = 0.5        # larger daily price moves suggest unadjusted splits or bad ticks
    max_missing_fraction: float = 0.05
    benchmark_ticker: str | None = None    # optional, e.g. "SPY" if present in prices
    labels: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None) -> "Gates":
        if not path:
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "cost_grid_bps" in data:
            data["cost_grid_bps"] = tuple(data["cost_grid_bps"])
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown gate settings: {sorted(unknown)}")
        return cls(**data)

    def to_dict(self) -> dict:
        out = asdict(self)
        out["cost_grid_bps"] = list(self.cost_grid_bps)
        return out
