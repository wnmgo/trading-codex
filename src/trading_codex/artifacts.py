from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
from loguru import logger

from trading_codex.engine import (
    BacktestConfig,
    BacktestDataset,
    BacktestResult,
    FundamentalSnapshot,
    StrategyConfig,
    Trade,
)


@dataclass
class RunMetadata:
    run_id: str
    created_at: datetime
    start: str
    end: str
    symbols: List[str]
    final_value: float
    total_return_pct: float
    path: Path


class ArtifactStore:
    """Persist backtest inputs/outputs for replay and analysis."""

    def __init__(self, root: Path | str = Path("runs")) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        dataset: BacktestDataset,
        strategy: StrategyConfig,
        backtest: BacktestConfig,
        result: BacktestResult,
        run_id: Optional[str] = None,
    ) -> RunMetadata:
        run_id = run_id or self._default_run_id()
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        logger.info("Writing artifacts to {}", run_dir)

        self._write_json(run_dir / "strategy.json", strategy.model_dump())
        self._write_json(run_dir / "backtest.json", backtest.model_dump())
        self._write_json(run_dir / "fundamentals.json", self._serialize_fundamentals(dataset.fundamentals))

        prices_frame = self._stack_prices(dataset.prices)
        if not prices_frame.empty:
            prices_frame.to_parquet(run_dir / "prices.parquet", index=False)

        trades_frame = self._trades_frame(result.trades)
        if not trades_frame.empty:
            trades_frame.to_parquet(run_dir / "trades.parquet", index=False)

        equity_frame = result.equity_curve.reset_index().rename(columns={"index": "date"})
        if not equity_frame.empty:
            equity_frame.to_parquet(run_dir / "equity.parquet", index=False)

        metadata = RunMetadata(
            run_id=run_id,
            created_at=datetime.now(UTC),
            start=str(backtest.start),
            end=str(backtest.end),
            symbols=backtest.symbols,
            final_value=result.final_value,
            total_return_pct=result.total_return_pct,
            path=run_dir,
        )
        self._write_json(
            run_dir / "metadata.json",
            {
                "run_id": metadata.run_id,
                "created_at": metadata.created_at.isoformat(),
                "start": metadata.start,
                "end": metadata.end,
                "symbols": metadata.symbols,
                "final_value": metadata.final_value,
                "total_return_pct": metadata.total_return_pct,
            },
        )
        return metadata

    def list_runs(self) -> List[RunMetadata]:
        items: List[RunMetadata] = []
        for metadata_file in self.root.glob("*/metadata.json"):
            try:
                data = json.loads(metadata_file.read_text())
                items.append(
                    RunMetadata(
                        run_id=data["run_id"],
                        created_at=datetime.fromisoformat(data["created_at"]),
                        start=data["start"],
                        end=data["end"],
                        symbols=data.get("symbols", []),
                        final_value=data.get("final_value", 0.0),
                        total_return_pct=data.get("total_return_pct", 0.0),
                        path=metadata_file.parent,
                    )
                )
            except Exception as err:  # noqa: BLE001
                logger.warning("Skipping invalid metadata {}: {}", metadata_file, err)
        items.sort(key=lambda m: m.created_at, reverse=True)
        return items

    def load_metadata(self, run_id: str) -> RunMetadata:
        data = json.loads((self.root / run_id / "metadata.json").read_text())
        return RunMetadata(
            run_id=data["run_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            start=data["start"],
            end=data["end"],
            symbols=data.get("symbols", []),
            final_value=data.get("final_value", 0.0),
            total_return_pct=data.get("total_return_pct", 0.0),
            path=self.root / run_id,
        )

    def load_trades(self, run_id: str) -> pd.DataFrame:
        path = self.root / run_id / "trades.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def load_equity(self, run_id: str) -> pd.DataFrame:
        path = self.root / run_id / "equity.parquet"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def load_prices(self, run_id: str, *, symbol: Optional[str] = None) -> pd.DataFrame:
        path = self.root / run_id / "prices.parquet"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)
        if "date" not in df.columns and df.index.name:
            df = df.reset_index()
        if symbol:
            df = df[df["symbol"] == symbol]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def load_fundamentals(self, run_id: str) -> List[Dict]:
        path = self.root / run_id / "fundamentals.json"
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def _stack_prices(self, prices: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        frames = []
        for symbol, frame in prices.items():
            if frame.empty:
                continue
            tmp = frame.copy().reset_index().rename(columns={"index": "date"})
            tmp["symbol"] = symbol
            frames.append(tmp)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _trades_frame(self, trades: Iterable[Trade]) -> pd.DataFrame:
        rows = []
        for trade in trades:
            rows.append(trade.model_dump())
        return pd.DataFrame(rows)

    def _write_json(self, path: Path, payload: Dict) -> None:
        path.write_text(json.dumps(payload, indent=2, default=str))

    def _serialize_fundamentals(
        self, fundamentals: Dict[str, FundamentalSnapshot]
    ) -> List[Dict]:
        return [snap.model_dump() for snap in fundamentals.values()]

    def _default_run_id(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"{timestamp}-{uuid.uuid4().hex[:8]}"
