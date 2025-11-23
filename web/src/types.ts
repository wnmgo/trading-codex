export interface RunMetadata {
  run_id: string;
  created_at: string;
  start: string;
  end: string;
  symbols: string[];
  final_value: number;
  total_return_pct: number;
  path: string;
}

export interface RunDetail {
  metadata: RunMetadata;
  strategy: Record<string, unknown>;
  backtest: Record<string, unknown>;
  fundamentals: Fundamental[];
}

export interface Trade {
  symbol: string;
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  shares: number;
  return_pct: number;
  reason: string;
}

export interface EquityPoint {
  date: string;
  equity: number;
  cash: number;
}

export interface PriceRow {
  symbol: string;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Fundamental {
  symbol: string;
  market_cap?: number;
  earnings_per_share?: number;
  average_daily_volume?: number;
  currency?: string;
}
