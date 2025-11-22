from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FundamentalSnapshot(BaseModel):
    """Static fundamentals used for ranking and screening."""

    symbol: str
    market_cap: Optional[float] = None
    earnings_per_share: Optional[float] = None
    average_daily_volume: Optional[float] = None
    currency: Optional[str] = None


class StrategyConfig(BaseModel):
    """Configuration for a rule-based strategy."""

    top_n: int = Field(10, gt=0, description="Maximum concurrent positions.")
    rebalance_days: int = Field(5, gt=0, description="Rebalance frequency in trading days.")
    lookback_days: int = Field(
        180, gt=0, description="Minimum price history to consider a symbol eligible."
    )
    momentum_window: int = Field(20, gt=0, description="Lookback window for momentum filter.")
    volume_window: int = Field(20, gt=0, description="Lookback window for average dollar volume.")
    take_profit: float = Field(0.05, gt=0, description="Take profit threshold (e.g. 0.05 for 5%).")
    stop_loss: Optional[float] = Field(
        None, description="Optional stop loss (negative fraction, e.g. -0.05 for -5%)."
    )
    max_holding_days: Optional[int] = Field(
        60, gt=0, description="Force exit after this many trading days."
    )
    min_market_cap: Optional[float] = Field(
        None, description="Skip securities below this market cap (in the data currency)."
    )
    min_avg_dollar_vol: Optional[float] = Field(
        None, description="Skip securities below this average daily dollar volume."
    )
    min_momentum: Optional[float] = Field(
        None, description="Minimum momentum (return over momentum_window)."
    )
    allow_fractional: bool = Field(
        True, description="Permit fractional share sizing when allocating capital."
    )
    ranking_factor: str = Field(
        "earnings_per_share",
        description="Fundamental field to rank candidates (default: earnings_per_share).",
    )

    @field_validator("stop_loss")
    def stop_loss_should_be_negative(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value >= 0:
            raise ValueError("stop_loss should be a negative fraction, e.g. -0.05 for -5%.")
        return value


class BacktestConfig(BaseModel):
    """High-level backtest configuration."""

    symbols: List[str]
    start: date
    end: date
    initial_capital: float = Field(100_000.0, gt=0)


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: float


class Trade(BaseModel):
    symbol: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    shares: float
    return_pct: float
    reason: str


class BacktestResult(BaseModel):
    trades: List[Trade]
    equity_curve: pd.DataFrame
    final_value: float
    total_return_pct: float
    model_config = ConfigDict(arbitrary_types_allowed=True)
