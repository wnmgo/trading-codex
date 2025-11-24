from datetime import date

import pandas as pd

from trading_codex.artifacts import ArtifactStore
from trading_codex.engine import (
    BacktestConfig,
    BacktestDataset,
    Backtester,
    FundamentalSnapshot,
    StrategyConfig,
)


def _sample_dataset() -> BacktestDataset:
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
    return BacktestDataset(prices={"AAA": price_up, "BBB": price_flat}, fundamentals=fundamentals)


def test_artifact_store_round_trip(tmp_path) -> None:
    dataset = _sample_dataset()
    strategy = StrategyConfig(
        top_n=1,
        take_profit=0.05,
        rebalance_days=1,
        lookback_days=1,
        momentum_window=1,
        volume_window=1,
    )
    backtest_cfg = BacktestConfig(
        symbols=["AAA", "BBB"], start=date(2024, 1, 1), end=date(2024, 1, 6), initial_capital=1_000.0
    )

    result = Backtester(dataset=dataset, strategy=strategy, backtest=backtest_cfg).run()

    store = ArtifactStore(tmp_path)
    meta = store.save(dataset=dataset, strategy=strategy, backtest=backtest_cfg, result=result, run_id="testrun")

    assert (meta.path / "metadata.json").exists()
    assert not store.load_trades(meta.run_id).empty
    equity = store.load_equity(meta.run_id)
    assert not equity.empty
    prices = store.load_prices(meta.run_id, symbol="AAA")
    assert set(prices["symbol"].unique()) == {"AAA"}
    fundamentals = store.load_fundamentals(meta.run_id)
    assert any(item["symbol"] == "AAA" for item in fundamentals)

    # Simulate legacy parquet with index instead of date column.
    legacy_path = meta.path / "prices.parquet"
    legacy_df = prices.set_index("date")
    legacy_df.to_parquet(legacy_path)
    recovered = store.load_prices(meta.run_id, symbol="AAA")
    assert "date" in recovered.columns
