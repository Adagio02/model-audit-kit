# What to send for an audit

Two CSV files, one row per date and ticker. Daily data is the default; tell us if yours is weekly or intraday.

**prices.csv**

    date,ticker,close
    2024-01-02,AAPL,185.64

- `close` must be adjusted for splits and dividends (or tell us it is not).
- Include stocks that were later delisted. Leaving them out inflates results (survivorship bias).
- Optional: include your benchmark (e.g. SPY) as another ticker.

**positions.csv**

    date,ticker,weight
    2024-01-02,AAPL,0.05

- `weight` is the fraction of capital held after trading at that day's close (negative = short).
- The weight on a date must use only information available at that close.
  If your signal uses that day's close, say so: the audit assumes trades happen at the close.
- Omit or zero tickers you do not hold.

**Also tell us** (goes into `gates.json`):
- your realistic cost per trade in basis points (commission + spread + impact);
- how many strategy variants or parameter sets you tried before this one (honest number);
- your drawdown limit and benchmark;
- your leverage and position-size limits (gross exposure, largest single position), if any.

You do not need to send code or explain the signal. Files are deleted 30 days after delivery unless you ask otherwise.
