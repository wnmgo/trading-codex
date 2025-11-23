import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "./api";
import type { EquityPoint, PriceRow, RunDetail, RunMetadata, Trade } from "./types";

const currency = (value: number) => `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const currencyCompact = (value: number) =>
  new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(value);
const pct = (value: number) => `${(value * 100).toFixed(2)}%`;

function App() {
  const [runs, setRuns] = useState<RunMetadata[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [prices, setPrices] = useState<PriceRow[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingPrices, setLoadingPrices] = useState<boolean>(false);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.runs();
        setRuns(data);
        if (data.length > 0) {
          setSelectedRunId(data[0].run_id);
        }
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, []);

  useEffect(() => {
    if (!selectedRunId) return;
    setLoading(true);
    Promise.all([
      api.runDetail(selectedRunId),
      api.trades(selectedRunId),
      api.equity(selectedRunId),
    ])
      .then(([detailData, tradeData, equityData]) => {
        setDetail(detailData);
        setTrades(tradeData);
        setEquity(equityData);
        const symbols = detailData?.metadata?.symbols || [];
        setSelectedSymbol(symbols[0] ?? null);
      })
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId || !selectedSymbol) return;
    setLoadingPrices(true);
    api
      .prices(selectedRunId, selectedSymbol)
      .then(setPrices)
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoadingPrices(false));
  }, [selectedRunId, selectedSymbol]);

  const stats = useMemo(() => summarize(trades, equity), [trades, equity]);

  return (
    <div className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">Trading Codex • Interactive Lab</p>
          <h1>Replay, investigate, and share every idea.</h1>
          <p className="lede">
            Each backtest run is persisted for long-term study. Switch between runs, drill into trades,
            fundamentals, equity, and raw prices — all rendered in a calm, confident interface.
          </p>
          <div className="hero-actions">
            <span className="pill">Artifacts served from your local `runs/` directory.</span>
            {detail?.metadata?.path ? <span className="pill ghost">Path: {detail.metadata.path}</span> : null}
          </div>
        </div>
        <div className="glow-card">
          <div className="glow-header">
            <span className="glow-label">Active Run</span>
            <strong>{selectedRunId ?? "None"}</strong>
          </div>
          <div className="glow-body">
            <div>
              <p className="label">Range</p>
              <p className="value">
                {detail ? `${detail.metadata.start} → ${detail.metadata.end}` : "–"}
              </p>
            </div>
            <div>
              <p className="label">Return</p>
              <p className={`value ${stats.totalReturn >= 0 ? "positive" : "negative"}`}>
                {pct(stats.totalReturn)}
              </p>
            </div>
            <div>
              <p className="label">Symbols</p>
              <p className="value">{detail?.metadata?.symbols?.join(", ") || "–"}</p>
            </div>
          </div>
        </div>
      </header>

      {error && <div className="error-banner">⚠️ {error}</div>}

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Runs</p>
            <h2>Saved experiments</h2>
          </div>
          <select
            className="select"
            value={selectedRunId ?? ""}
            onChange={(e) => setSelectedRunId(e.target.value)}
          >
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.run_id} • {run.start} → {run.end}
              </option>
            ))}
          </select>
        </div>
        <div className="run-grid">
          {runs.map((run) => (
            <button
              key={run.run_id}
              className={`run-card ${run.run_id === selectedRunId ? "active" : ""}`}
              onClick={() => setSelectedRunId(run.run_id)}
            >
              <div className="run-title">
                <span>{run.run_id}</span>
                <span className={`pill ${run.total_return_pct >= 0 ? "pill-positive" : "pill-negative"}`}>
                  {pct(run.total_return_pct)}
                </span>
              </div>
              <p className="run-sub">{run.start} → {run.end}</p>
              <p className="run-meta">{run.symbols.join(", ")}</p>
            </button>
          ))}
          {runs.length === 0 && <p>No runs found. Execute `pdm run trading-codex` to generate artifacts.</p>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Performance</p>
            <h2>Equity & outcomes</h2>
          </div>
          {loading && <span className="pill ghost">Loading data…</span>}
        </div>
        <div className="metrics-grid">
          <MetricCard label="Final Value" value={currency(stats.finalValue)} />
          <MetricCard
            label="Total Return"
            value={pct(stats.totalReturn)}
            tone={stats.totalReturn >= 0 ? "positive" : "negative"}
          />
          <MetricCard label="Trades" value={`${trades.length}`} />
          <MetricCard label="Win Rate" value={stats.winRate} />
          <MetricCard label="Avg Trade" value={pct(stats.avgReturn)} />
          <MetricCard label="Max Drawdown" value={pct(stats.maxDrawdown)} />
        </div>
        <div className="chart-row">
          <ChartCard title="Equity curve" subtitle="Includes cash + open positions">
            <EquityChart data={equity} />
          </ChartCard>
          <ChartCard title="Price explorer" subtitle="Raw prices saved with the run">
            <div className="chart-controls">
              <label>
                Symbol
                <select
                  className="select"
                  value={selectedSymbol ?? ""}
                  onChange={(e) => setSelectedSymbol(e.target.value)}
                >
                  {(detail?.metadata?.symbols || []).map((sym) => (
                    <option key={sym} value={sym}>
                      {sym}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {loadingPrices ? <div className="ghost-text">Loading prices…</div> : <PriceChart data={prices} />}
          </ChartCard>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Strategy</p>
            <h2>Inputs & filters</h2>
          </div>
          <span className="pill ghost">Replayable without network</span>
        </div>
        <div className="config-grid">
          <ConfigCard title="Backtest">
            <KeyValueList entries={detail?.backtest ?? {}} />
          </ConfigCard>
          <ConfigCard title="Strategy">
            <KeyValueList entries={detail?.strategy ?? {}} />
          </ConfigCard>
          <ConfigCard title="Fundamentals">
            <FundamentalsTable fundamentals={detail?.fundamentals ?? []} />
          </ConfigCard>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Executions</p>
            <h2>Trades log</h2>
          </div>
          <span className="pill ghost">{trades.length} rows</span>
        </div>
        <TradesTable trades={trades} />
      </section>
    </div>
  );
}

function MetricCard({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className={`metric-card ${tone ?? ""}`}>
      <p className="label">{label}</p>
      <p className="metric-value">{value}</p>
    </div>
  );
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <div>
          <p className="label">{subtitle}</p>
          <h3>{title}</h3>
        </div>
      </div>
      <div className="chart-card-body">{children}</div>
    </div>
  );
}

function ConfigCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <h3>{title}</h3>
      </div>
      <div className="chart-card-body">{children}</div>
    </div>
  );
}

function KeyValueList({ entries }: { entries: Record<string, unknown> }) {
  const keys = Object.keys(entries);
  if (keys.length === 0) {
    return <p className="ghost-text">No data saved for this run.</p>;
  }
  return (
    <ul className="kv-list">
      {keys.map((key) => (
        <li key={key}>
          <span>{key}</span>
          <span>{String(entries[key])}</span>
        </li>
      ))}
    </ul>
  );
}

function FundamentalsTable({ fundamentals }: { fundamentals: RunDetail["fundamentals"] }) {
  if (!fundamentals || fundamentals.length === 0) {
    return <p className="ghost-text">No fundamentals captured.</p>;
  }
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Market Cap</th>
            <th>EPS</th>
            <th>Avg Volume</th>
            <th>Currency</th>
          </tr>
        </thead>
        <tbody>
          {fundamentals.map((row) => (
            <tr key={row.symbol}>
              <td>{row.symbol}</td>
              <td>{row.market_cap ? currency(row.market_cap) : "–"}</td>
              <td>{row.earnings_per_share?.toFixed(2) ?? "–"}</td>
              <td>{row.average_daily_volume ? row.average_daily_volume.toLocaleString() : "–"}</td>
              <td>{row.currency ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({ trades }: { trades: Trade[] }) {
  if (!trades || trades.length === 0) {
    return <p className="ghost-text">No trades for this run.</p>;
  }
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>Return</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={`${trade.symbol}-${trade.entry_date}-${trade.exit_date}`}>
              <td>{trade.symbol}</td>
              <td>{trade.entry_date}</td>
              <td>{trade.exit_date}</td>
              <td className={trade.return_pct >= 0 ? "positive" : "negative"}>{pct(trade.return_pct)}</td>
              <td>{trade.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EquityChart({ data }: { data: EquityPoint[] }) {
  if (!data || data.length === 0) {
    return <p className="ghost-text">No equity data saved.</p>;
  }
  const sorted = [...data].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={sorted} margin={{ left: 12, right: 8, top: 10, bottom: 4 }}>
          <defs>
            <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#7ef3c8" stopOpacity={0.9} />
              <stop offset="100%" stopColor="#7ef3c8" stopOpacity={0.1} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(148,163,184,0.2)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={shortDate} stroke="#94a3b8" tickMargin={8} />
          <YAxis tickFormatter={(v) => currencyCompact(Number(v))} stroke="#94a3b8" width={90} tickMargin={8} />
          <Tooltip
            formatter={(value: number) => `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            labelFormatter={(label) => `Date: ${label}`}
            contentStyle={{ background: "#0f172a", border: "1px solid rgba(148,163,184,0.2)", color: "#e2e8f0" }}
          />
          <Area type="monotone" dataKey="equity" stroke="#7ef3c8" fill="url(#equityFill)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function PriceChart({ data }: { data: PriceRow[] }) {
  if (!data || data.length === 0) {
    return <p className="ghost-text">No price data saved.</p>;
  }
  const sorted = [...data].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={sorted} margin={{ left: 12, right: 8, top: 10, bottom: 4 }}>
          <defs>
            <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fcd34d" stopOpacity={0.9} />
              <stop offset="100%" stopColor="#fcd34d" stopOpacity={0.1} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(148,163,184,0.2)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={shortDate} stroke="#94a3b8" tickMargin={8} />
          <YAxis tickFormatter={(v) => currencyCompact(Number(v))} stroke="#94a3b8" width={90} tickMargin={8} />
          <Tooltip
            formatter={(value: number) => `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            labelFormatter={(label) => `Date: ${label}`}
            contentStyle={{ background: "#0f172a", border: "1px solid rgba(148,163,184,0.2)", color: "#e2e8f0" }}
          />
          <Area type="monotone" dataKey="close" stroke="#fcd34d" fill="url(#priceFill)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function shortDate(value: string) {
  // Value is already ISO date string; avoid timezone shifts by not using toISOString.
  if (value.length >= 10) return value.slice(5, 10);
  return value;
}

function summarize(trades: Trade[], equity: EquityPoint[]) {
  const finalValue = equity.length ? equity[equity.length - 1].equity : 0;
  const totalReturn = equity.length ? (equity[equity.length - 1].equity - equity[0].equity) / equity[0].equity : 0;
  const wins = trades.filter((t) => t.return_pct > 0).length;
  const winRate = trades.length ? `${((wins / trades.length) * 100).toFixed(1)}%` : "–";
  const avgReturn = trades.length
    ? trades.reduce((sum, t) => sum + t.return_pct, 0) / trades.length
    : 0;
  const maxDrawdown = computeDrawdown(equity);
  return {
    finalValue,
    totalReturn,
    winRate,
    avgReturn,
    maxDrawdown,
  };
}

function computeDrawdown(equity: EquityPoint[]) {
  if (!equity || equity.length === 0) return 0;
  let peak = equity[0].equity;
  let maxDd = 0;
  for (const point of equity) {
    peak = Math.max(peak, point.equity);
    const dd = (point.equity - peak) / peak;
    maxDd = Math.min(maxDd, dd);
  }
  return maxDd;
}

export default App;
