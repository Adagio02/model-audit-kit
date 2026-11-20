"""Self-contained HTML audit report (charts embedded), suitable to send to a client."""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from modelaudit.audit import AuditResult  # noqa: E402
from modelaudit.remediation import remediation  # noqa: E402

INK, MUTED, LINE, ACCENT, BAD = "#1d2733", "#5b6776", "#d9dee5", "#1f6f8b", "#b23b3b"
STATUS_COLOR = {"PASS": "#1e7b4f", "WARN": "#a86a00", "FAIL": "#b23b3b",
                "CONDITIONAL": "#a86a00"}


def _fig_to_data_uri(fig) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=144, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(LINE)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=LINE, linewidth=0.6)
    ax.set_axisbelow(True)


def _equity_chart(result: AuditResult) -> str:
    bench = next(c for c in result.checks if c.key == "benchmark").series["benchmark_returns"]
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    ax.plot((1 + result.gross).cumprod(), color=MUTED, linewidth=1, label="Gross")
    ax.plot((1 + result.net).cumprod(), color=ACCENT, linewidth=1.6, label=f"Net of {result.gates.cost_bps:g} bps")
    ax.plot((1 + bench).cumprod(), color="#9aa5b1", linewidth=1, linestyle="--", label="Benchmark")
    ax.set_title("Growth of $1", loc="left", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    return _fig_to_data_uri(fig)


def _exposure_chart(result: AuditResult) -> str:
    series = next(c for c in result.checks if c.key == "exposure").series
    fig, ax = plt.subplots(figsize=(7.2, 2.2))
    ax.plot(series["gross"], color=ACCENT, linewidth=1.2, label="Gross (sum of |weights|)")
    ax.plot(series["net"], color=MUTED, linewidth=1, label="Net (sum of weights)")
    ax.axhline(result.gates.max_gross_leverage, color=BAD, linewidth=0.8, linestyle="--",
               label=f"Gross limit {result.gates.max_gross_leverage:g}x")
    ax.set_title("Exposure over time", loc="left", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8, ncol=3)
    _style(ax)
    return _fig_to_data_uri(fig)


def _bar_chart(labels, values, title, xlabel, highlight=None) -> str:
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    colors = [BAD if v < 0 else ACCENT for v in values]
    if highlight is not None:
        colors = [BAD if (i == highlight) else col for i, col in enumerate(colors)]
    ax.bar([str(x) for x in labels], values, color=colors, width=0.6)
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    ax.set_xlabel(xlabel, fontsize=8, color=MUTED)
    _style(ax)
    return _fig_to_data_uri(fig)


def render_html(result: AuditResult) -> str:
    by_key = {c.key: c for c in result.checks}
    delays = by_key["lookahead"].series["by_delay"]
    grid = by_key["costs"].series["grid"]
    folds = by_key["walk_forward"].series["folds"]
    charts = {
        "equity": _equity_chart(result),
        "exposure": _exposure_chart(result),
        "delay": _bar_chart(list(delays), list(delays.values()), "Sharpe vs execution delay", "days of delay"),
        "cost": _bar_chart([f"{k:g}" for k in grid], list(grid.values()), "Net Sharpe vs cost", "bps per trade"),
        "folds": _bar_chart([str(i + 1) for i in range(len(folds))], [f["sharpe"] for f in folds],
                            "Net Sharpe by time window", "window (oldest to newest)"),
    }
    data = result.to_json()
    head = data["headline"]
    verdict = result.verdict
    vcolor = STATUS_COLOR[verdict]

    rows = "".join(
        f"<tr><td>{html.escape(c.title)}</td>"
        f"<td><span class='pill' style='background:{STATUS_COLOR[c.status]}'>{c.status}</span></td>"
        f"<td>{html.escape(c.summary)}</td></tr>"
        for c in result.checks
    )
    hashes = "".join(f"<li><code>{html.escape(k)}</code> {v}</li>"
                     for k, v in result.manifest["inputs_sha256"].items()) or "<li>Not recorded</li>"
    gates = "".join(f"<li><code>{html.escape(k)}</code>: {html.escape(str(v))}</li>"
                    for k, v in result.gates.to_dict().items() if k != "labels")
    order = {"FAIL": 0, "WARN": 1}
    flagged = sorted((c for c in result.checks if c.status in order), key=lambda c: order[c.status])
    fixes = "".join(
        f"<li><span class='pill' style='background:{STATUS_COLOR[c.status]}'>{c.status}</span> "
        f"<b>{html.escape(c.title)}.</b> {html.escape(remediation(c.key, c.summary)[1])}</li>"
        for c in flagged)
    fix_section = (f"<h2>What to fix first</h2><ol class='fixes'>{fixes}</ol>" if fixes else "")
    deflated = by_key["deflated_sharpe"].metrics
    interval = ("" if deflated.get("sharpe_ci95_low") is None else
                f"<div class='kpi'><span>Net Sharpe 95% interval</span><strong>"
                f"{deflated['sharpe_ci95_low']:.2f} to {deflated['sharpe_ci95_high']:.2f}</strong></div>")
    meaning = {
        "PASS": "No material problems were found under the stated gates.",
        "CONDITIONAL": "No disqualifying problem, but one or more checks need attention before relying on this backtest.",
        "FAIL": "At least one disqualifying problem was found. The backtest should not be relied on as it stands.",
    }[verdict]

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Audit: {html.escape(result.strategy)}</title>
<style>
 :root {{ --ink:{INK}; --muted:{MUTED}; --line:{LINE}; }}
 body {{ font-family: "Segoe UI", system-ui, -apple-system, sans-serif; color:var(--ink); background:#fff;
        margin:0 auto; max-width:900px; padding:32px 20px 48px; line-height:1.5; }}
 h1 {{ font-size:24px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:32px 0 10px; }}
 .sub {{ color:var(--muted); font-size:13px; }}
 .verdict {{ border:1px solid var(--line); border-left:6px solid {vcolor}; border-radius:0; padding:14px 18px; margin:22px 0; }}
 .verdict b {{ color:{vcolor}; font-size:20px; letter-spacing:.04em; }}
 .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }}
 .kpi {{ border:1px solid var(--line); border-radius:8px; padding:10px 14px; }}
 .kpi span {{ display:block; font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
 .kpi strong {{ font-size:20px; font-variant-numeric:tabular-nums; }}
 table {{ width:100%; border-collapse:collapse; font-size:13px; }}
 td {{ border-top:1px solid var(--line); padding:8px 6px; vertical-align:top; }}
 td:first-child {{ width:30%; font-weight:600; }}
 .pill {{ color:#fff; border-radius:999px; padding:2px 9px; font-size:11px; font-weight:600; }}
 .charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
 img {{ max-width:100%; }}
 ul {{ font-size:12px; color:var(--muted); padding-left:18px; }} code {{ font-size:11px; }}
 .fixes {{ font-size:13px; color:var(--ink); }} .fixes li {{ margin-bottom:6px; }}
 .foot {{ margin-top:36px; font-size:11px; color:var(--muted); border-top:1px solid var(--line); padding-top:12px; }}
</style></head><body>
<h1>Strategy audit: {html.escape(result.strategy)}</h1>
<div class="sub">Generated {result.manifest["generated_utc"]} UTC by {result.manifest["tool"]}</div>
<div class="verdict"><b>{verdict}</b><div>{meaning}</div></div>
<div class="kpis">
 <div class="kpi"><span>Gross Sharpe</span><strong>{head["gross_sharpe"]:.2f}</strong></div>
 <div class="kpi"><span>Net Sharpe ({result.gates.cost_bps:g} bps)</span><strong>{head["net_sharpe"]:.2f}</strong></div>
 <div class="kpi"><span>Net total return</span><strong>{head["net_total_return"]:.1%}</strong></div>
 <div class="kpi"><span>Max drawdown</span><strong>{head["max_drawdown"]:.1%}</strong></div>
 {interval}
</div>
<h2>Findings</h2><table>{rows}</table>
<p class="sub">Verdict rule: any FAIL makes the verdict FAIL; otherwise any WARN makes it CONDITIONAL;
otherwise PASS. The gates were fixed before the audit and are listed below.</p>
{fix_section}
<h2>Evidence</h2>
<img src="{charts["equity"]}" alt="Growth of one dollar, gross, net and benchmark">
<img src="{charts["exposure"]}" alt="Gross and net exposure over time">
<div class="charts">
 <img src="{charts["delay"]}" alt="Sharpe ratio by execution delay">
 <img src="{charts["cost"]}" alt="Net Sharpe ratio by cost assumption">
 <img src="{charts["folds"]}" alt="Net Sharpe ratio by time window">
</div>
<h2>How to read the checks</h2>
<ul>
 <li><b>Delay test:</b> a genuine signal loses performance gradually when trades are delayed. A collapse after one extra day means the backtest used information it would not have had.</li>
 <li><b>Costs:</b> the break-even cost is the trading cost at which the edge disappears. High turnover makes small edges fragile.</li>
 <li><b>Deflated Sharpe:</b> adjusts for how many variants were tried. The more variants, the higher the bar luck alone could clear.</li>
 <li><b>Exposure and concentration:</b> checks the book against the mandate's leverage and position limits, and whether a few names or days produce most of the result.</li>
 <li><b>Time windows:</b> a reliable edge should be positive in most periods, not concentrated in one.</li>
</ul>
<h2>Method and reproducibility</h2>
<ul><li>{html.escape(result.manifest["contract"])}</li></ul>
<b style="font-size:12px">Gates (fixed before the audit)</b><ul>{gates}</ul>
<b style="font-size:12px">Input fingerprints (SHA-256)</b><ul>{hashes}</ul>
<div class="foot">This audit tests the integrity of a backtest. It is not investment advice and does not
predict future returns. Results depend on the data and positions supplied.</div>
</body></html>"""


def write_html(result: AuditResult, path: str | Path) -> None:
    Path(path).write_text(render_html(result), encoding="utf-8")
