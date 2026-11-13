# Model Audit Kit

Independent validation of trading-strategy backtests. A client sends two CSV files
(prices and their daily positions); the tool runs seven checks against gates fixed in
advance and produces a one-page HTML report with a **PASS / CONDITIONAL / FAIL** verdict.

| Check | Question it answers |
|---|---|
| Data integrity | Are prices clean, are delisted stocks present (survivorship), is data missing? |
| Look-ahead / leakage | Does performance collapse when trades are delayed one day? |
| Transaction-cost realism | Does the edge survive realistic costs? What is the break-even cost? |
| Walk-forward stability | Is the edge positive in most time windows, or concentrated in one? |
| Overfitting (deflated Sharpe) | Is the Sharpe still significant after the number of variants tried? |
| Drawdown and tail risk | Is the worst loss inside the agreed limit? |
| Benchmark value | Does it beat simply holding the benchmark? |

## Quick start (Windows PowerShell, in this folder)

    powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1      # .venv + install + tests
    powershell -ExecutionPolicy Bypass -File .\scripts\run_demo.ps1   # demo market + 3 audits

Audit a client: put `prices.csv` and `positions.csv` (and optionally `gates.json`) in
`clients\<name>\input\`, then

    powershell -ExecutionPolicy Bypass -File .\scripts\audit_client.ps1 -Client acme -Strategy "Acme L/S"

Command line anywhere: `modelaudit run --prices p.csv --positions w.csv --gates g.json --name X --out folder`
(exit code 0 = PASS/CONDITIONAL, 2 = FAIL, so it can run in CI).

## The demo

`demo/make_demo.py` builds a synthetic market (80 stocks 2015-2024, with listings,
delistings and a benchmark) and three strategies that show what the audit catches:

| Strategy | Verdict | Why |
|---|---|---|
| honest_momentum | PASS | Weekly momentum, decays gradually with delay, survives costs |
| leaky_momentum | FAIL | Uses tomorrow's return by mistake: Sharpe 5.6 falls to 1.8 with one day of delay |
| high_turnover_reversal | FAIL | Real but tiny edge: Sharpe 1.6 before costs, 0.07 after 10 bps; 43% drawdown |

The data is synthetic on purpose: nobody's real strategy is exposed, and the "right answer" is known.

## Folders

    src/modelaudit/   the engine (checks, report, CLI)
    demo/             synthetic market, gates and sample reports
    templates/        default gates, client data spec
    docs/             guides
    clients/          per-client work (git-ignored, never commit client data)

Not investment advice. The audit tests the integrity of a backtest; it does not predict returns.
