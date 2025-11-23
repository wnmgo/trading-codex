from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd
from loguru import logger

from .models import (
    BacktestConfig,
    BacktestResult,
    FundamentalSnapshot,
    Position,
    StrategyConfig,
    Trade,
)


@dataclass
class BacktestDataset:
    prices: Dict[str, pd.DataFrame]
    fundamentals: Dict[str, FundamentalSnapshot]


class Backtester:
    """Simple long-only backtester with rule-driven selection."""

    def __init__(
        self,
        dataset: BacktestDataset,
        strategy: StrategyConfig,
        backtest: BacktestConfig,
    ) -> None:
        self.dataset = self._prepare_dataset(dataset, backtest)
        self.strategy = strategy
        self.backtest = backtest

    def _prepare_dataset(
        self, dataset: BacktestDataset, backtest: BacktestConfig
    ) -> BacktestDataset:
        start_ts = pd.Timestamp(backtest.start)
        end_ts = pd.Timestamp(backtest.end)
        normalized_prices: Dict[str, pd.DataFrame] = {}
        requested = set(backtest.symbols)
        for symbol, frame in dataset.prices.items():
            if requested and symbol not in requested:
                continue
            df = frame.copy()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df = df.rename(columns=str.lower)
            df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
            if df.empty:
                logger.warning("No price data for %s after trimming to range.", symbol)
                continue
            normalized_prices[symbol] = df
        fundamentals = {
            symbol: snap
            for symbol, snap in dataset.fundamentals.items()
            if not requested or symbol in requested
        }
        return BacktestDataset(prices=normalized_prices, fundamentals=fundamentals)

    def run(self) -> BacktestResult:
        positions: Dict[str, Position] = {}
        trades: List[Trade] = []
        cash = self.backtest.initial_capital

        trading_days = self._trading_calendar()
        if not trading_days:
            raise ValueError("No price data available for the requested symbols and date range.")
        equity_rows: List[Dict[str, float]] = []

        for i, current_ts in enumerate(trading_days):
            prices_today = {
                symbol: self._price_asof(symbol, current_ts) for symbol in positions.keys()
            }

            closed_today = self._maybe_exit_positions(
                positions=positions, prices_today=prices_today, current_ts=current_ts
            )
            for trade in closed_today:
                cash += trade.exit_price * trade.shares
                trades.append(trade)
                positions.pop(trade.symbol, None)

            if self._should_rebalance(i):
                additions = self._select_candidates(current_ts, exclude=set(positions.keys()))
                cash = self._open_positions(additions, positions, current_ts, cash)

            equity = cash + sum(
                pos.shares * self._price_asof(pos.symbol, current_ts) for pos in positions.values()
            )
            equity_rows.append({"date": current_ts, "cash": cash, "equity": equity})

        # force exit remaining positions at last known price
        if trading_days:
            last_ts = trading_days[-1]
            for pos in list(positions.values()):
                price = self._price_asof(pos.symbol, last_ts)
                trades.append(
                    Trade(
                        symbol=pos.symbol,
                        entry_date=pos.entry_date.to_pydatetime(),
                        exit_date=last_ts.to_pydatetime(),
                        entry_price=pos.entry_price,
                        exit_price=price,
                        shares=pos.shares,
                        return_pct=(price - pos.entry_price) / pos.entry_price,
                        reason="end_of_data",
                    )
                )
            positions.clear()

        equity_curve = pd.DataFrame(equity_rows).set_index("date")
        final_value = equity_curve["equity"].iloc[-1] if not equity_curve.empty else cash
        total_return_pct = (
            (final_value - self.backtest.initial_capital) / self.backtest.initial_capital
            if self.backtest.initial_capital
            else 0.0
        )

        return BacktestResult(
            trades=trades, equity_curve=equity_curve, final_value=final_value, total_return_pct=total_return_pct
        )

    def _trading_calendar(self) -> List[pd.Timestamp]:
        all_days = set()
        for df in self.dataset.prices.values():
            all_days.update(df.index)
        return sorted(all_days)

    def _should_rebalance(self, index: int) -> bool:
        return index % self.strategy.rebalance_days == 0

    def _price_asof(self, symbol: str, ts: pd.Timestamp) -> float:
        df = self.dataset.prices.get(symbol)
        if df is None or df.empty:
            raise KeyError(f"No price data for {symbol}")
        # use last available price on or before ts
        subset = df.loc[:ts]
        if subset.empty:
            raise KeyError(f"No price data for {symbol} up to {ts}")
        return float(subset["close"].iloc[-1])

    def _select_candidates(self, current_ts: pd.Timestamp, exclude: set[str]) -> List[str]:
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
        selected = [symbol for symbol, _ in candidates[: self.strategy.top_n]]
        return selected

    def _open_positions(
        self,
        additions: Iterable[str],
        positions: Dict[str, Position],
        current_ts: pd.Timestamp,
        cash: float,
    ) -> float:
        additions_list = [sym for sym in additions if sym not in positions]
        slots_to_fill = min(self.strategy.top_n - len(positions), len(additions_list))
        if slots_to_fill <= 0:
            return cash
        budget_per_position = cash / slots_to_fill if slots_to_fill else 0

        for symbol in additions_list:
            price = self._price_asof(symbol, current_ts)
            if price <= 0:
                continue
            shares = budget_per_position / price
            if not self.strategy.allow_fractional:
                shares = math.floor(shares)
            if shares <= 0:
                continue
            positions[symbol] = Position(
                symbol=symbol, entry_date=current_ts, entry_price=price, shares=shares
            )
            cash -= shares * price
            logger.debug("Opened %s: shares=%s price=%.2f", symbol, shares, price)
        return cash

    def _maybe_exit_positions(
        self,
        positions: Dict[str, Position],
        prices_today: Dict[str, float],
        current_ts: pd.Timestamp,
    ) -> List[Trade]:
        closed: List[Trade] = []
        for symbol, pos in list(positions.items()):
            price = prices_today.get(symbol)
            if price is None:
                continue
            change = (price - pos.entry_price) / pos.entry_price
            days_held = (current_ts - pos.entry_date).days
            exit_reason = None
            if change >= self.strategy.take_profit:
                exit_reason = "take_profit"
            elif self.strategy.stop_loss is not None and change <= self.strategy.stop_loss:
                exit_reason = "stop_loss"
            elif self.strategy.max_holding_days and days_held >= self.strategy.max_holding_days:
                exit_reason = "max_holding_days"

            if exit_reason:
                closed.append(
                    Trade(
                        symbol=symbol,
                        entry_date=pos.entry_date.to_pydatetime(),
                        exit_date=current_ts.to_pydatetime(),
                        entry_price=pos.entry_price,
                        exit_price=price,
                        shares=pos.shares,
                        return_pct=change,
                        reason=exit_reason,
                    )
                )
        return closed

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
