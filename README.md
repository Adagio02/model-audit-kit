# Model Audit Kit

**Website and example reports:** https://adagio02.github.io/model-audit-kit/

Independent validation of trading-strategy backtests. A client sends two CSV files
(prices and their daily positions); the tool runs eight checks against gates fixed in
advance and produces a one-page HTML report with a **PASS / CONDITIONAL / FAIL** verdict.

| Check | Question it answers |
|---|---|
| Data integrity | Are prices clean, are delisted stocks present (survivorship), is data missing? |
| Look-ahead / leakage | Does performance collapse when trades are delayed one day? |
| Transaction-cost realism | Does the edge survive realistic costs? What is the break-even cost? |
| Walk-forward stability | Is the edge positive in most time windows, or concentrated in one? |
| Overfitting (deflated Sharpe) | Is the Sharpe still significant after the number of variants tried? (with a 95% bootstrap interval) |
| Drawdown and tail risk | Is the worst loss inside the agreed limit? |
| Exposure and concentration | Does the book respect the mandate's leverage and position limits? Do a few names or days carry the result? |
| Benchmark value | Does it beat simply holding the benchmark? |

## Quick start (Windows PowerShell, in this folder)

    powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1      # .venv + install + tests
    powershell -ExecutionPolicy Bypass -File .\scripts\run_demo.ps1   # demo market + 3 audits

Audit a client: put `prices.csv` and `positions.csv` (and optionally `gates.json`) in
`clients\<name>\input\`, then

    powershell -ExecutionPolicy Bypass -File .\scripts\audit_client.ps1 -Client acme -Strategy "Acme L/S"

Command line anywhere: `modelaudit run --prices p.csv --positions w.csv --gates g.json --name X --out folder`
(exit code 0 = PASS/CONDITIONAL, 2 = FAIL, so it can run in CI).

## Run it on Azure

The same engine runs as an event-driven Azure pipeline: upload a batch to Blob Storage, an Azure
Function audits it, results land in Azure SQL, Power BI/Fabric report on them, and a Microsoft
Foundry model explains each failed check in plain English. A Copilot Studio agent ("Audit Desk")
answers questions such as "what failed validation yesterday?" through a read-only API on the same
Function App. Full plan: [docs/07-AZURE.md](docs/07-AZURE.md).

    powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Azure
    powershell -ExecutionPolicy Bypass -File .\azure\scripts\run_local_pipeline.ps1    # try it with no Azure account
    az login
    powershell -ExecutionPolicy Bypass -File .\azure\scripts\deploy.ps1 -ResourceGroup rg-model-audit -AlertEmail you@example.com

## The demo

`demo/make_demo.py` builds a synthetic market (80 stocks 2015-2024, with listings,
delistings and a benchmark) and four strategies that show what the audit catches:

| Strategy | Verdict | Why |
|---|---|---|
| honest_momentum | PASS | Weekly momentum, decays gradually with delay, survives costs |
| leaky_momentum | FAIL | Uses tomorrow's return by mistake: Sharpe 5.6 falls to 1.8 with one day of delay |
| leaky_momentum_fixed | PASS | Same strategy with the bug fixed (`rets.shift(-1)` -> `rets`): Sharpe 1.68, the real edge |
| high_turnover_reversal | FAIL | Real but tiny edge: Sharpe 1.6 before costs, 0.07 after 10 bps; 43% drawdown; 5.4x gross leverage |

The data is synthetic on purpose: nobody's real strategy is exposed, and the "right answer" is known.

## Folders

    src/modelaudit/   the engine (checks, report, CLI)
    src/modelaudit/cloud/  pipeline shared by CLI, Azure Function and Fabric (storage, SQL, AI explainer)
    azure/            Function app (audit + agent API), Bicep, SQL schema, deploy scripts,
                      Power BI queries/measures/theme, Copilot Studio API spec, instructions and test set
    demo/             synthetic market, gates and sample reports
    templates/        default gates, client data spec
    docs/             the service (SERVICE.md) and the Azure guide (07-AZURE.md)
    site/             the public website (build.py, template.html), published by .github/workflows/pages.yml
    clients/          per-client work (git-ignored, never commit client data)

## The service

The kit is used to deliver independent backtest audits for systematic managers and allocators:
what is checked, what you send, what you get and how data is handled are in
[docs/SERVICE.md](docs/SERVICE.md). Running it on Azure: [docs/07-AZURE.md](docs/07-AZURE.md).

Not investment advice. The audit tests the integrity of a backtest; it does not predict returns.
