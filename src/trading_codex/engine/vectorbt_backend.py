from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

import numpy as np
import pandas as pd

from trading_codex.engine.backends import Engine
from trading_codex.engine.backtester import BacktestDataset
from trading_codex.engine.models import (
    BacktestConfig,
    BacktestResult,
    FundamentalSnapshot,
    Position,
    StrategyConfig,
    Trade,
)


@dataclass
class VectorBTBacktester(Engine):
    """Vectorbt-backed runner with a feature subset (rebalance + tp/sl/max holding)."""

    dataset: BacktestDataset
    strategy: StrategyConfig
    backtest: BacktestConfig
    _trading_days: List[pd.Timestamp] = field(init=False)

    def __post_init__(self) -> None:
        import vectorbt as _  # noqa: F401
        self.dataset = self._prepare_dataset(self.dataset, self.backtest)
        self._trading_days = self._trading_calendar()

    def run(self) -> BacktestResult:
        import vectorbt as vbt

        positions: Dict[str, Position] = {}
        trades: List[Trade] = []
        cash = self.backtest.initial_capital

        symbols = list(self.dataset.prices.keys())
        if not symbols:
            raise ValueError("No price data available for selected symbols.")

        entries = pd.DataFrame(False, index=self._trading_days, columns=symbols)
        exits = pd.DataFrame(False, index=self._trading_days, columns=symbols)
        sizes = pd.DataFrame(np.nan, index=self._trading_days, columns=symbols)
        equity_rows: List[Dict[str, float]] = []

        for i, current_ts in enumerate(self._trading_days):
            prices_today = {sym: self._price_asof(sym, current_ts) for sym in symbols}

            # exits
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
                    exits.loc[current_ts, symbol] = True
                    trades.append(
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
                    cash += pos.shares * price
                    positions.pop(symbol, None)

            # rebalancing entries
            if i % self.strategy.rebalance_days == 0:
                additions = self._select_candidates(current_ts, exclude=set(positions.keys()))
                slots = max(self.strategy.top_n - len(positions), 0)
                additions = additions[:slots]
                budget = cash / (len(additions) if additions else 1) if additions else 0
                for symbol in additions:
                    price = prices_today.get(symbol)
                    if price is None or price <= 0:
                        continue
                    shares = budget / price
                    if not self.strategy.allow_fractional:
                        shares = float(int(shares))
                    if shares <= 0:
                        continue
                    entries.loc[current_ts, symbol] = True
                    sizes.loc[current_ts, symbol] = shares
                    positions[symbol] = Position(
                        symbol=symbol, entry_date=current_ts, entry_price=price, shares=shares
                    )
                    cash -= shares * price

            equity = cash + sum(
                pos.shares * prices_today.get(pos.symbol, pos.entry_price) for pos in positions.values()
            )
            equity_rows.append({"date": current_ts, "cash": cash, "equity": equity})

        close_df = pd.DataFrame(
            {sym: self.dataset.prices[sym]["close"] for sym in symbols}
        ).reindex(self._trading_days)
        portfolio = vbt.Portfolio.from_signals(
            close_df,
            entries=entries.values,
            exits=exits.values,
            init_cash=self.backtest.initial_capital,
            size=sizes.values,
            freq="1D",
            fees=0.0,
        )
        equity_curve = portfolio.value()
        total_return = portfolio.total_return()
        if hasattr(total_return, "iat"):
            total_return_pct = float(total_return.iat[0])
        else:
            total_return_pct = float(total_return)
        if isinstance(equity_curve, pd.Series):
            equity_values = equity_curve
        else:
            equity_values = equity_curve.sum(axis=1)
        result_equity = equity_values.to_frame(name="equity")
        result_equity["cash"] = 0.0  # placeholder

        return BacktestResult(
            trades=trades,
            equity_curve=result_equity,
            final_value=float(equity_values.iloc[-1]),
            total_return_pct=total_return_pct,
        )

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

    def _price_asof(self, symbol: str, ts: pd.Timestamp) -> float:
        df = self.dataset.prices.get(symbol)
        if df is None or df.empty:
            raise KeyError(f"No price data for {symbol}")
        subset = df.loc[:ts]
        if subset.empty:
            raise KeyError(f"No price data for {symbol} up to {ts}")
        return float(subset["close"].iloc[-1])

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
