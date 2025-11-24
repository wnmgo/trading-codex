from datetime import date

import pandas as pd

from trading_codex.engine import (
    BacktestConfig,
    BacktestDataset,
    Backtester,
    FundamentalSnapshot,
    StrategyConfig,
)


def test_take_profit_exit_hits_target() -> None:
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    price_up = pd.DataFrame(
        {
            "open": [100, 101, 103, 106, 105, 104],
            "high": [100, 102, 104, 107, 106, 105],
            "low": [99, 100, 102, 105, 104, 103],
            "close": [100, 102, 104, 106, 105, 104],
            "volume": [1_000_000] * 6,
        },
        index=dates,
    )
    price_flat = pd.DataFrame(
        {
            "open": [50] * 6,
            "high": [50] * 6,
            "low": [50] * 6,
            "close": [50] * 6,
            "volume": [500_000] * 6,
        },
        index=dates,
    )
    fundamentals = {
        "AAA": FundamentalSnapshot(symbol="AAA", earnings_per_share=5.0, market_cap=10_000_000_000),
        "BBB": FundamentalSnapshot(symbol="BBB", earnings_per_share=1.0, market_cap=5_000_000_000),
    }
    dataset = BacktestDataset(prices={"AAA": price_up, "BBB": price_flat}, fundamentals=fundamentals)
    strategy = StrategyConfig(
        top_n=1,
        take_profit=0.05,
        rebalance_days=1,
        lookback_days=1,
        momentum_window=1,
        volume_window=1,
    )
    backtest_cfg = BacktestConfig(
        symbols=["AAA", "BBB"], start=dates[0].date(), end=dates[-1].date(), initial_capital=1_000.0
    )

    backtester = Backtester(dataset=dataset, strategy=strategy, backtest=backtest_cfg)
    result = backtester.run()

    assert result.trades, "Strategy should close at least one trade."
    trade = result.trades[0]
    assert trade.symbol == "AAA"
    assert trade.reason == "take_profit"
    assert trade.return_pct >= 0.05
    assert result.final_value > backtest_cfg.initial_capital
