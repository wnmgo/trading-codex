from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from trading_codex.artifacts import ArtifactStore


def create_app(artifact_root: Path = Path("runs"), web_dir: Optional[Path] = None) -> FastAPI:
    store = ArtifactStore(artifact_root)

    app = FastAPI(title="Trading Codex", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/runs")
    def list_runs() -> List[Dict[str, Any]]:
        return [_meta_dict(meta) for meta in store.list_runs()]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> Dict[str, Any]:
        meta = _ensure_metadata(store, run_id)
        strategy = _read_optional_json(meta.path / "strategy.json")
        backtest = _read_optional_json(meta.path / "backtest.json")
        fundamentals = store.load_fundamentals(run_id)
        return {
            "metadata": _meta_dict(meta),
            "strategy": strategy,
            "backtest": backtest,
            "fundamentals": fundamentals,
        }

    @app.get("/api/runs/{run_id}/trades")
    def trades(run_id: str) -> List[Dict[str, Any]]:
        _ensure_metadata(store, run_id)
        df = store.load_trades(run_id)
        if df.empty:
            return []
        df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.strftime("%Y-%m-%d")
        df["exit_date"] = pd.to_datetime(df["exit_date"]).dt.strftime("%Y-%m-%d")
        df["return_pct"] = df["return_pct"].astype(float)
        return df.to_dict(orient="records")

    @app.get("/api/runs/{run_id}/equity")
    def equity(run_id: str) -> List[Dict[str, Any]]:
        _ensure_metadata(store, run_id)
        df = store.load_equity(run_id)
        if df.empty:
            return []
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df.to_dict(orient="records")

    @app.get("/api/runs/{run_id}/prices")
    def prices(
        run_id: str,
        symbol: Optional[str] = Query(None, description="Filter by symbol"),
        limit: Optional[int] = Query(
            2000,
            description="Maximum number of rows to return (default 2000, set to 0 for all).",
        ),
    ) -> List[Dict[str, Any]]:
        _ensure_metadata(store, run_id)
        df = store.load_prices(run_id, symbol=symbol)
        if df.empty:
            return []
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        if limit and limit > 0:
            df = df.sort_values("date").head(limit)
        return df.to_dict(orient="records")

    @app.get("/api/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    if web_dir and web_dir.exists():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="spa")

    return app


def _meta_dict(meta) -> Dict[str, Any]:
    return {
        "run_id": meta.run_id,
        "created_at": meta.created_at.isoformat(),
        "start": meta.start,
        "end": meta.end,
        "symbols": meta.symbols,
        "final_value": meta.final_value,
        "total_return_pct": meta.total_return_pct,
        "path": str(meta.path),
    }


def _read_optional_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _ensure_metadata(store: ArtifactStore, run_id: str):
    try:
        return store.load_metadata(run_id)
    except FileNotFoundError as err:
        raise HTTPException(status_code=404, detail="Run not found") from err
