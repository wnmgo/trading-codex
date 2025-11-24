from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, Sequence

import pandas as pd
import yfinance as yf
from loguru import logger

from trading_codex.engine.models import FundamentalSnapshot
from trading_codex.engine.backtester import BacktestDataset


@dataclass
class YahooFetchConfig:
    interval: str = "1d"
    auto_adjust: bool = True


class YahooDataClient:
    """Lightweight wrapper around yfinance for prices and basic fundamentals."""

    def __init__(self, config: YahooFetchConfig | None = None) -> None:
        self.config = config or YahooFetchConfig()

    def fetch(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> BacktestDataset:
        prices = self._fetch_price_history(symbols, start, end)
        fundamentals = self._fetch_fundamentals(symbols)
        return BacktestDataset(prices=prices, fundamentals=fundamentals)

    def _fetch_price_history(
        self, symbols: Sequence[str], start: date, end: date
    ) -> Dict[str, pd.DataFrame]:
        result: Dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            logger.info("Fetching price history for {}", symbol)
            df = yf.download(
                symbol,
                start=start,
                end=end,
                interval=self.config.interval,
                auto_adjust=self.config.auto_adjust,
                progress=False,
                group_by="ticker",
            )
            if df.empty:
                logger.warning("No data returned for {}", symbol)
                continue
            if isinstance(df.columns, pd.MultiIndex):
                if symbol in df.columns.get_level_values(0):
                    df = df.xs(symbol, axis=1, level=0)
                else:
                    df.columns = ["_".join(map(str, col)).strip().lower() for col in df.columns]
            df.columns = [str(col).strip().lower() for col in df.columns]
            df.index = pd.to_datetime(df.index).tz_localize(None)
            needed = ["open", "high", "low", "close", "volume"]
            missing = [col for col in needed if col not in df.columns]
            if missing:
                logger.warning("Missing columns {} for {}", missing, symbol)
                continue
            result[symbol] = df[needed]
        return result

    def _fetch_fundamentals(self, symbols: Iterable[str]) -> Dict[str, FundamentalSnapshot]:
        fundamentals: Dict[str, FundamentalSnapshot] = {}
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = dict(getattr(ticker, "fast_info", {}) or {})
                eps = None
                try:
                    earnings = ticker.get_earnings_dates(limit=1)
                    if earnings is not None and not earnings.empty and "Reported EPS" in earnings:
                        eps_val = earnings["Reported EPS"].dropna()
                        if not eps_val.empty:
                            eps = float(eps_val.iloc[-1])
                except Exception as err:  # noqa: BLE001
                    logger.debug("Failed to fetch EPS for {}: {}", symbol, err)

                if eps is None:
                    try:
                        info_full = ticker.get_info()
                        eps = info_full.get("trailingEps")
                        if not info.get("ten_day_average_volume"):
                            info["ten_day_average_volume"] = info_full.get("averageDailyVolume10Day")
                        if not info.get("three_month_average_volume"):
                            info["three_month_average_volume"] = info_full.get("averageDailyVolume3Month")
                        if not info.get("market_cap"):
                            info["market_cap"] = info_full.get("marketCap")
                    except Exception as err:  # noqa: BLE001
                        logger.debug("Failed to fetch extended fundamentals for {}: {}", symbol, err)

                fundamentals[symbol] = FundamentalSnapshot(
                    symbol=symbol,
                    market_cap=info.get("market_cap"),
                    earnings_per_share=eps or info.get("trailingEps"),
                    average_daily_volume=info.get("ten_day_average_volume")
                    or info.get("three_month_average_volume"),
                    currency=info.get("currency"),
                )
            except Exception as err:  # noqa: BLE001
                logger.warning("Failed to fetch fundamentals for {}: {}", symbol, err)
        return fundamentals
