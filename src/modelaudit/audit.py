"""Runs every check and produces the verdict."""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from modelaudit import __version__
from modelaudit.checks import FAIL, PASS, WARN, CheckResult
from modelaudit import checks as c
from modelaudit.config import Gates
from modelaudit.data import (load_positions, load_prices, max_drawdown, portfolio_returns,
                             sha256_file, sharpe, wide)


@dataclass
class AuditResult:
    strategy: str
    verdict: str
    checks: list[CheckResult]
    gates: Gates
    manifest: dict
    net: pd.Series
    gross: pd.Series

    def to_json(self) -> dict:
        return {
            "strategy": self.strategy,
            "verdict": self.verdict,
            "headline": {
                "gross_sharpe": round(sharpe(self.gross, self.gates.periods_per_year), 3),
                "net_sharpe": round(sharpe(self.net, self.gates.periods_per_year), 3),
                "net_total_return": round(float((1 + self.net).prod() - 1), 4),
                "max_drawdown": round(max_drawdown(self.net), 4),
            },
            "checks": [{"key": x.key, "title": x.title, "status": x.status,
                        "summary": x.summary, "metrics": x.metrics} for x in self.checks],
            "gates": self.gates.to_dict(),
            "manifest": self.manifest,
        }


def verdict_for(results: list[CheckResult]) -> str:
    statuses = {r.status for r in results}
    if FAIL in statuses:
        return "FAIL"
    if WARN in statuses:
        return "CONDITIONAL"
    return "PASS"


def run_audit(prices: pd.DataFrame, positions: pd.DataFrame, gates: Gates,
              strategy: str = "strategy", input_hashes: dict | None = None) -> AuditResult:
    closes = wide(prices, "close")
    returns = closes.pct_change(fill_method=None).fillna(0.0)
    weights = wide(positions, "weight")

    gross = portfolio_returns(weights, returns)
    net = portfolio_returns(weights, returns, cost_bps=gates.cost_bps)

    results = [
        c.data_integrity(prices, positions, gates),
        c.lookahead(weights, returns, gates),
        c.costs(weights, returns, gates),
        c.walk_forward(net, gates),
        c.deflated_sharpe(net, gates),
        c.risk(net, gates),
        c.benchmark(net, returns, gates),
    ]
    manifest = {
        "tool": f"modelaudit {__version__}",
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "inputs_sha256": input_hashes or {},
        "contract": ("Weights are decided at the close of each date using only information available "
                     "then, and earn the next period's return."),
    }
    return AuditResult(strategy, verdict_for(results), results, gates, manifest, net, gross)


def run_from_files(prices_path: str, positions_path: str, gates_path: str | None,
                   strategy: str) -> AuditResult:
    gates = Gates.load(gates_path)
    hashes = {Path(prices_path).name: sha256_file(prices_path),
              Path(positions_path).name: sha256_file(positions_path)}
    if gates_path:
        hashes[Path(gates_path).name] = sha256_file(gates_path)
    return run_audit(load_prices(prices_path), load_positions(positions_path), gates, strategy, hashes)


def write_json(result: AuditResult, path: str | Path) -> None:
    Path(path).write_text(json.dumps(result.to_json(), indent=2, default=str), encoding="utf-8")


__all__ = ["AuditResult", "run_audit", "run_from_files", "write_json", "PASS", "WARN", "FAIL"]
