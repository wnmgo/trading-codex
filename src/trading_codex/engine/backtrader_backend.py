from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

import backtrader as bt
import numpy as np
import pandas as pd

from trading_codex.engine.backends import Engine
from trading_codex.engine.backtester import BacktestDataset
from trading_codex.engine.models import (
    BacktestConfig,
    BacktestResult,
    FundamentalSnapshot,
    StrategyConfig,
    Trade,
)


class PriceFeed(bt.feeds.PandasData):
    params = (
        ("datetime", None),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", None),
    )


class SimpleStrategy(bt.Strategy):
    params = dict(
        targets=None,
        take_profit=0.05,
        stop_loss=None,
        rebalance_days=5,
    )

    def __init__(self):
        self.targets = self.p.targets or {}  # type: ignore[attr-defined]
        self.day_count = 0

    def next(self):
        self.day_count += 1
        dt = self.datas[0].datetime.date(0)
        todays_targets = self.targets.get(dt, {}) if isinstance(self.targets, dict) else {}

        # exit non-targets
        for data in self.datas:
            pos = self.getposition(data)
            if pos.size != 0 and data._name not in todays_targets:
                self.close(data=data)

        # check tp/sl
        for data in self.datas:
            pos = self.getposition(data)
            if pos.size == 0:
                continue
            entry_price = pos.price
            change = (data.close[0] - entry_price) / entry_price
            if self.p.take_profit and change >= self.p.take_profit:
                self.close(data=data)
            if self.p.stop_loss is not None and change <= self.p.stop_loss:
                self.close(data=data)

        # rebalance
        if self.day_count % self.p.rebalance_days == 1:
            total_value = self.broker.getvalue()
            for data in self.datas:
                weight = todays_targets.get(data._name, 0)
                if weight <= 0:
                    continue
                alloc = total_value * weight
                size = alloc / data.close[0] if data.close[0] else 0
                if size > 0:
                    self.order_target_size(data=data, target=size)


@dataclass
class BacktraderRunner(Engine):
    dataset: BacktestDataset
    strategy: StrategyConfig
    backtest: BacktestConfig
    _trading_days: List[pd.Timestamp] = field(init=False)

    def __post_init__(self) -> None:
        self.dataset = self._prepare_dataset(self.dataset, self.backtest)
        self._trading_days = self._trading_calendar()

    def run(self) -> BacktestResult:
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.backtest.initial_capital)
        targets = self._build_targets()

        for symbol, frame in self.dataset.prices.items():
            feed = PriceFeed(dataname=frame)
            cerebro.adddata(feed, name=symbol)

        cerebro.addstrategy(
            SimpleStrategy,
            targets=targets,
            take_profit=self.strategy.take_profit,
            stop_loss=self.strategy.stop_loss,
            rebalance_days=self.strategy.rebalance_days,
        )
        result = cerebro.run()
        trades: List[Trade] = []
        # Minimal equity curve: end-of-run broker value.
        equity_df = pd.DataFrame({"equity": [cerebro.broker.getvalue()]}, index=[self._trading_days[-1]])
        equity_df["cash"] = np.nan
        final_value = float(cerebro.broker.getvalue())
        total_return_pct = (final_value - self.backtest.initial_capital) / self.backtest.initial_capital
        return BacktestResult(
            trades=trades,
            equity_curve=equity_df,
            final_value=final_value,
            total_return_pct=total_return_pct,
        )

    def _build_targets(self) -> Dict[pd.Timestamp, Dict[str, float]]:
        targets: Dict[pd.Timestamp, Dict[str, float]] = {}
        for i, current_ts in enumerate(self._trading_days):
            if i % self.strategy.rebalance_days != 0:
                continue
            picks = self._select_candidates(current_ts, exclude=set())
            if not picks:
                continue
            weight = 1 / len(picks)
            targets[pd.Timestamp(current_ts).to_pydatetime().date()] = {sym: weight for sym in picks}
        return targets

    def _prepare_dataset(
        self, dataset: BacktestDataset, backtest: BacktestConfig
    ) -> BacktestDataset:
        start_ts = pd.Timestamp(backtest.start)
        end_ts = pd.Timestamp(backtest.end)
        normalized_prices: Dict[str, pd.DataFrame] = {}
        requested = set(backtest.symbols)
        for symbol, frame in dataset.prices.items():
            if symbol not in requested:
                continue
            df = frame.copy()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df = df.rename(columns=str.lower)
            df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
            if df.empty:
                continue
            normalized_prices[symbol] = df
        fundamentals = {
            symbol: snap
            for symbol, snap in dataset.fundamentals.items()
            if not requested or symbol in requested
        }
        return BacktestDataset(prices=normalized_prices, fundamentals=fundamentals)

    def _trading_calendar(self) -> List[pd.Timestamp]:
        all_days = set()
        for df in self.dataset.prices.values():
            all_days.update(df.index)
        return sorted(all_days)

    def _select_candidates(self, current_ts: pd.Timestamp, exclude: Set[str]) -> List[str]:
        candidates = []
        for symbol, snap in self.dataset.fundamentals.items():
            if symbol in exclude:
                continue
            price_frame = self.dataset.prices.get(symbol)
            if price_frame is None or price_frame.empty:
                continue
            price_history = price_frame.loc[:current_ts]
            if len(price_history) < self.strategy.lookback_days:
                continue

            momentum = self._momentum(symbol, current_ts, self.strategy.momentum_window)
            avg_dollar_vol = self._avg_dollar_volume(
                symbol, current_ts, self.strategy.volume_window
            )

            if self.strategy.min_market_cap is not None and snap.market_cap is not None:
                if snap.market_cap < self.strategy.min_market_cap:
                    continue
            if self.strategy.min_momentum is not None:
                if momentum is None or momentum < self.strategy.min_momentum:
                    continue
            if self.strategy.min_avg_dollar_vol is not None:
                if avg_dollar_vol is None or avg_dollar_vol < self.strategy.min_avg_dollar_vol:
                    continue

            ranking_value = getattr(snap, self.strategy.ranking_factor, None)
            candidates.append((symbol, ranking_value if ranking_value is not None else -np.inf))

        candidates.sort(key=lambda item: item[1], reverse=True)
        return [sym for sym, _ in candidates[: self.strategy.top_n]]

    def _momentum(self, symbol: str, current_ts: pd.Timestamp, window: int) -> float | None:
        df = self.dataset.prices.get(symbol)
        if df is None:
            return None
        history = df.loc[:current_ts].tail(window + 1)
        if len(history) < window + 1:
            return None
        start_price = history["close"].iloc[0]
        end_price = history["close"].iloc[-1]
        return (end_price - start_price) / start_price if start_price else None

    def _avg_dollar_volume(
        self, symbol: str, current_ts: pd.Timestamp, window: int
    ) -> float | None:
        df = self.dataset.prices.get(symbol)
        if df is None:
            return None
        history = df.loc[:current_ts].tail(window)
        if history.empty:
            return None
        return float((history["close"] * history["volume"]).mean())
