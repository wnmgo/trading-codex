from __future__ import annotations

import sys
from datetime import date, timedelta
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from trading_codex.data.yahoo import YahooDataClient
from trading_codex.engine import BacktestConfig, Backtester, StrategyConfig

app = typer.Typer(help="Rule-based investing playground and backtesting CLI.")


def _default_start_end() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=365), today


@app.command()
def run(
    tickers: str = typer.Argument(
        "AAPL,MSFT,GOOGL,AMZN,NVDA", help="Comma-separated tickers to test."
    ),
    top_n: int = typer.Option(5, help="Maximum concurrent positions."),
    take_profit: float = typer.Option(0.05, help="Take-profit threshold as fraction."),
    stop_loss: Optional[float] = typer.Option(
        None, help="Optional stop-loss as negative fraction (e.g. -0.05)."
    ),
    rebalance_days: int = typer.Option(5, help="Rebalance frequency in trading days."),
    min_market_cap: Optional[float] = typer.Option(
        None, help="Ignore symbols below this market cap (same currency as data)."
    ),
    min_momentum: Optional[float] = typer.Option(
        None, help="Minimum momentum over the momentum window."
    ),
    min_dollar_vol: Optional[float] = typer.Option(
        None, help="Minimum average daily dollar volume over the volume window."
    ),
    momentum_window: int = typer.Option(20, help="Lookback window (in trading days) for momentum."),
    volume_window: int = typer.Option(20, help="Lookback window (in trading days) for average dollar volume."),
    lookback_days: int = typer.Option(180, help="Require at least this many days of price history."),
    max_holding_days: Optional[int] = typer.Option(60, help="Force exit after this many trading days."),
    start: Optional[date] = typer.Option(None, help="Start date (YYYY-MM-DD)."),
    end: Optional[date] = typer.Option(None, help="End date (YYYY-MM-DD)."),
    capital: float = typer.Option(100_000.0, help="Starting capital."),
    allow_fractional: bool = typer.Option(
        True, help="Allow fractional share sizing when allocating capital."
    ),
) -> None:
    """Fetch data from Yahoo Finance and run the rule-based backtester."""
    logger.remove()
    logger.add(sys.stderr, level="INFO", enqueue=False, backtrace=False, diagnose=False)
    start_date, end_date = _default_start_end()
    if start:
        start_date = start
    if end:
        end_date = end

    symbols = [s.strip().upper() for s in tickers.split(",") if s.strip()]
    if not symbols:
        raise typer.BadParameter("Please provide at least one ticker.")

    strategy = StrategyConfig(
        top_n=top_n,
        take_profit=take_profit,
        stop_loss=stop_loss,
        rebalance_days=rebalance_days,
        min_market_cap=min_market_cap,
        min_momentum=min_momentum,
        min_avg_dollar_vol=min_dollar_vol,
        momentum_window=momentum_window,
        volume_window=volume_window,
        lookback_days=lookback_days,
        max_holding_days=max_holding_days,
        allow_fractional=allow_fractional,
    )
    backtest_cfg = BacktestConfig(symbols=symbols, start=start_date, end=end_date, initial_capital=capital)

    console = Console()
    console.print(f"[bold]Fetching[/bold] {len(symbols)} symbols from {start_date} to {end_date}...")
    dataset = YahooDataClient().fetch(symbols, start=start_date, end=end_date)
    backtester = Backtester(dataset=dataset, strategy=strategy, backtest=backtest_cfg)
    result = backtester.run()

    pct = result.total_return_pct * 100
    console.print(
        f"[green bold]Finished[/green bold]: final value ${result.final_value:,.2f} ({pct:.2f}% return)"
    )
    console.print(f"Closed trades: {len(result.trades)}")

    if result.trades:
        table = Table(title="Trades", show_lines=False)
        table.add_column("Symbol")
        table.add_column("Entry")
        table.add_column("Exit")
        table.add_column("Return %")
        table.add_column("Reason")
        for trade in result.trades:
            table.add_row(
                trade.symbol,
                trade.entry_date.date().isoformat(),
                trade.exit_date.date().isoformat(),
                f"{trade.return_pct*100:.2f}",
                trade.reason,
            )
        console.print(table)


if __name__ == "__main__":
    app()
