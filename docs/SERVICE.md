# Independent backtest audits: the service

Before you trade a systematic strategy or show it to investors, an independent check that the backtest
was built soundly. You send prices and positions; you get a verdict against limits agreed in advance,
a report you can share, and a list of what to fix.

## What is checked

Every audit runs the eight checks in this repository, with the gates (pass/fail limits) fixed before
the audit starts and printed in the report:

| Check | The question |
|---|---|
| Data integrity | Are prices clean? Are delisted stocks included (survivorship)? Is data missing? |
| Look-ahead / leakage | Does performance collapse when every trade is delayed by one day? |
| Transaction costs | Does the edge survive realistic costs? At what cost does it disappear? |
| Stability over time | Is the result positive in most periods, or concentrated in one? |
| Overfitting | Is the Sharpe ratio still significant after the number of variants tried? |
| Drawdown | Is the worst loss inside your limit? |
| Exposure and concentration | Does the book respect your leverage and position limits? Do a few names or days carry the result? |
| Benchmark | Does it beat simply holding the benchmark? |

The [demo reports](../demo/reports) show what you receive. The `leaky_momentum` report shows a strategy
with 5,500% backtested returns failing the look-ahead check, and `leaky_momentum_fixed` the same
strategy after the bug is fixed.

## What you send

Two CSV files: daily prices and the positions your strategy held
([data specification](../templates/CLIENT-DATA-SPEC.md)). No code, and no explanation of your signal.
Plus your cost assumption, the number of variants you tried, and your drawdown, leverage and position limits.

## What you get

- An HTML report with the verdict (**PASS**, **CONDITIONAL** or **FAIL**), the evidence charts and a
  "What to fix first" list.
- A written findings memo with recommended fixes, and a review call.
- A re-test after you fix the issues.
- For ongoing work: a monthly audit with a dashboard across your strategies, and an assistant that
  answers questions such as *"what failed this month, and why?"*.

## How your data is handled

- Used only for your audit. Input files are deleted 30 days after delivery unless you ask otherwise.
- Every report records the SHA-256 fingerprint of your files and the gates used, so results can be
  reproduced exactly.
- When explanations are drafted by an AI model, the model receives only the audit's summary numbers,
  never your files, and every explanation is reviewed before it reaches you.
- If you prefer, the whole pipeline can run in **your own** Azure subscription, so your data never leaves it.

## What it is not

The audit tests how a backtest was built, under the stated assumptions. It is not investment advice,
not a recommendation to buy or sell anything, and not a prediction of future returns. A PASS means no
disqualifying problem was found by these tests; it does not mean the strategy will make money.

## Contact

Felipe Taruselli · [ftarusel@gmail.com](mailto:ftarusel@gmail.com) · [adagio02.github.io/model-audit-kit](https://adagio02.github.io/model-audit-kit/). A free first scan of one strategy is available on request.
