import type { EquityPoint, PriceRow, RunDetail, RunMetadata, Trade } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`Request failed (${res.status}) for ${path}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  runs(): Promise<RunMetadata[]> {
    return fetchJson<RunMetadata[]>("/runs");
  },
  runDetail(runId: string): Promise<RunDetail> {
    return fetchJson<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
  },
  trades(runId: string): Promise<Trade[]> {
    return fetchJson<Trade[]>(`/runs/${encodeURIComponent(runId)}/trades`);
  },
  equity(runId: string): Promise<EquityPoint[]> {
    return fetchJson<EquityPoint[]>(`/runs/${encodeURIComponent(runId)}/equity`);
  },
  prices(runId: string, symbol?: string): Promise<PriceRow[]> {
    const search = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
    return fetchJson<PriceRow[]>(`/runs/${encodeURIComponent(runId)}/prices${search}`);
  },
};
