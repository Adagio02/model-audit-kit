"""Builds site/index.html, the public one-page website (published to GitHub Pages by
.github/workflows/pages.yml together with the demo reports).

Run from the project folder after scripts/run_demo.ps1 has created demo/data:

    python site/build.py --name "Your Name" --email you@yourdomain.com [--linkedin https://...]

The hero chart is computed from the leaky_momentum demo: the strategy as backtested versus the same
positions traded one day later, both after 10 bps of costs.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEMOS = ["honest_momentum", "leaky_momentum", "leaky_momentum_fixed", "high_turnover_reversal"]


def curves() -> dict:
    import pandas as pd

    from modelaudit.data import load_positions, load_prices, portfolio_returns, wide

    prices = load_prices(ROOT / "demo/data/prices.csv")
    returns = wide(prices, "close").pct_change(fill_method=None).fillna(0.0)
    weights = wide(load_positions(ROOT / "demo/data/positions_leaky_momentum.csv"), "weight")
    tested = portfolio_returns(weights, returns, delay=1, cost_bps=10)
    delayed = portfolio_returns(weights, returns, delay=2, cost_bps=10)
    common = tested.index.intersection(delayed.index)
    equity = pd.DataFrame({"a": (1 + tested[common]).cumprod(), "b": (1 + delayed[common]).cumprod()})
    weekly = equity.resample("W-FRI").last().dropna()
    return {"dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
            "tested": [round(float(x), 4) for x in weekly.a],
            "delayed": [round(float(x), 4) for x in weekly.b]}


def chart_svg(d: dict) -> str:
    """Log-scale growth of $1, as a static SVG (no JavaScript, no external requests)."""
    W, H, L, R, T, B = 960, 380, 64, 215, 16, 34
    xs = len(d["dates"]) - 1
    ymin, ymax = math.log10(0.8), math.log10(80)

    def X(i):
        return L + (W - L - R) * i / xs

    def Y(v):
        return T + (H - T - B) * (1 - (math.log10(v) - ymin) / (ymax - ymin))

    def path(series):
        return "M" + " L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(series))

    grid = "".join(
        f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
        f'<text x="{L - 10}" y="{Y(v) + 4:.1f}" class="axis" text-anchor="end">{label}</text>'
        for v, label in [(1, "$1"), (2, "$2"), (5, "$5"), (10, "$10"), (20, "$20"), (50, "$50")])
    years = "".join(
        f'<text x="{X(i):.1f}" y="{H - 10}" class="axis" text-anchor="middle">{s[:4]}</text>'
        for i, s in enumerate(d["dates"])
        if (i == 0 or s[:4] != d["dates"][i - 1][:4]) and i < xs - 30 and int(s[:4]) % 2 == 1)
    ta, tb = d["tested"][-1], d["delayed"][-1]
    end = X(xs) + 12
    return (
        f'<svg class="delay-chart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="chart-title chart-desc">\n'
        '<title id="chart-title">Growth of $1: the leaky momentum backtest, and the same positions traded '
        'one day later</title>\n'
        f'<desc id="chart-desc">As backtested, $1 grows to ${ta:.0f} between 2015 and 2024. With every trade '
        f'delayed by one day it grows to ${tb:.2f}. Both after 10 basis points of trading costs. '
        'Logarithmic scale.</desc>\n'
        f'{grid}{years}\n'
        f'<path d="{path(d["delayed"])}" class="line delayed"/>\n'
        f'<path d="{path(d["tested"])}" class="line tested"/>\n'
        f'<circle cx="{X(xs):.1f}" cy="{Y(ta):.1f}" r="4" class="dot tested"/>\n'
        f'<circle cx="{X(xs):.1f}" cy="{Y(tb):.1f}" r="4" class="dot delayed"/>\n'
        f'<text x="{end:.1f}" y="{Y(ta):.1f}" dy="-0.25em" class="end tested">As backtested</text>\n'
        f'<text x="{end:.1f}" y="{Y(ta):.1f}" dy="1.05em" class="endnum">+{(ta - 1) * 100:,.0f}%</text>\n'
        f'<text x="{end:.1f}" y="{Y(tb):.1f}" dy="-0.25em" class="end delayed">One day later</text>\n'
        f'<text x="{end:.1f}" y="{Y(tb):.1f}" dy="1.05em" class="endnum">+{(tb - 1) * 100:,.0f}%</text>\n'
        '</svg>')


def main() -> int:
    parser = argparse.ArgumentParser(description="Build site/index.html")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--linkedin", default="")
    args = parser.parse_args()
    html = (ROOT / "site/template.html").read_text(encoding="utf-8")
    html = html.replace("{{CHART}}", chart_svg(curves()))
    for name in DEMOS:
        result = json.loads((ROOT / "demo/reports" / name / "results.json").read_text(encoding="utf-8"))
        html = html.replace("{{S_%s}}" % name, f"{result['headline']['net_sharpe']:.2f}")
    html = html.replace("{{NAME}}", args.name).replace("{{EMAIL}}", args.email)
    linkedin = f' or <a href="{args.linkedin}">LinkedIn</a>' if args.linkedin else ""
    html = html.replace("{{LINKEDIN_LINE}}", linkedin)
    if "{{" in html:
        raise SystemExit("Unfilled placeholder: " + html[html.index("{{"):][:40])
    (ROOT / "site/index.html").write_text(html, encoding="utf-8")
    print(f"Wrote site/index.html ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
