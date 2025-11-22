# Trading Codex

Backtesting playground for rule-based investing ideas. Quickly validate hypotheses such as “buy highest earnings stocks and sell at +5%” and iterate with filters (market cap, recent momentum, dollar volume, etc.).

## What’s inside
- Python 3.11+ project managed by PDM with SCM-driven versioning (`[tool.pdm.version]` writes `_version.py` during builds).
- Yahoo Finance data client (open source) for prices and lightweight fundamentals.
- Rule-based backtester with configurable selection filters and exit rules (take-profit, stop-loss, max-holding days).
- Typer CLI (`trading-codex`) to fetch data and run an experiment quickly.
- Pytest coverage for the core take-profit flow.

## Quickstart
1) Install dependencies (includes dev tooling):
```bash
pdm install --dev
```

2) Run a sample idea (defaults: top 5 symbols, take-profit 5%, rebalance every 5 trading days):
```bash
pdm run trading-codex run --take-profit 0.05 --rebalance-days 5 --tickers AAPL,MSFT,AMZN,GOOGL,NVDA
```

3) Tweak filters:
```bash
pdm run trading-codex run \
  --tickers AAPL,MSFT,AMZN,GOOGL,NVDA \
  --min-market-cap 5_000_000_000 \
  --min-momentum 0.02 \
  --min-dollar-vol 50_000_000 \
  --take-profit 0.05 \
  --stop-loss -0.03
```

4) Run tests:
```bash
pdm run pytest
```

## Data and extensibility
- Default data source is Yahoo Finance (via `yfinance`); it is free but unofficial—data gaps are possible.
- For more stable fundamentals or intraday data, consider paid/open APIs like Tiingo, Alpha Vantage, Polygon, or Nasdaq Data Link. The system is designed so you can swap the data client while reusing the backtester.

## Versioning
Version is derived from git tags (`v*` by default) via PDM’s SCM integration. Builds write the resolved version to `src/trading_codex/_version.py` using the configured template. Use `git tag v0.1.0` (for example) before packaging to emit the correct version.
