const IS_STATIC = process.env.NEXT_PUBLIC_STATIC === "true";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || (IS_STATIC ? "" : "http://localhost:8000");

export interface BlackSwan {
  ticker: string;
  event_ticker: string;
  title: string;
  yes_sub_title: string;
  prediction_price: number;
  prediction_ts: number | null;
  prediction_volume: number | null;
  volume_at_price: number | null;
  last_price_dollars: string;
  volume_fp: string;
  open_interest_fp: string;
  close_time: string;
  settlement_ts: string | null;
  result: string;
  yes_bid_dollars: string;
  yes_ask_dollars: string;
  rules_primary: string;
  category: string;
  ai_summary: string;
}

export interface BlackSwanResponse {
  black_swans: BlackSwan[];
  count: number;
  limit?: number;
  offset?: number;
}

export interface CategoryStat {
  category: string;
  count: number;
}

export interface Stats {
  total_black_swans: number;
  total_markets_analyzed: number;
  avg_prediction_price: number | null;
  lowest_prediction_price: number | null;
  total_volume: number;
  total_profit_at_price: number;
  earliest_settlement: string | null;
  latest_settlement: string | null;
  category_stats: CategoryStat[];
}

export interface CollectResponse {
  status: string;
  total_markets_fetched?: number;
  yes_markets_enriched?: number;
}

function thresholdPct(threshold: number): number {
  return Math.round(threshold * 100);
}

const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

export async function fetchBlackSwans(
  threshold = 0.10,
  sort = "prediction_price",
  order = "asc",
  limit = 500,
  offset = 0,
): Promise<BlackSwanResponse> {
  if (IS_STATIC) {
    const pct = thresholdPct(threshold);
    const res = await fetch(`${basePath}/data/black-swans-${pct}.json`);
    if (!res.ok) {
      const fallback = await fetch(`${basePath}/data/black-swans-10.json`);
      return fallback.json();
    }
    const data: BlackSwanResponse = await res.json();
    const items = [...data.black_swans];
    const sortKey = sort as keyof BlackSwan;
    items.sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const na = typeof av === "string" ? parseFloat(av) || 0 : Number(av);
      const nb = typeof bv === "string" ? parseFloat(bv) || 0 : Number(bv);
      if (!isNaN(na) && !isNaN(nb)) return order === "asc" ? na - nb : nb - na;
      return order === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return { black_swans: items.slice(offset, offset + limit), count: items.length };
  }

  const params = new URLSearchParams({
    threshold: threshold.toString(),
    sort,
    order,
    limit: limit.toString(),
    offset: offset.toString(),
  });
  const res = await fetch(`${API_BASE}/api/black-swans?${params}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function fetchStats(threshold = 0.10): Promise<Stats> {
  if (IS_STATIC) {
    const pct = thresholdPct(threshold);
    const res = await fetch(`${basePath}/data/stats-${pct}.json`);
    if (!res.ok) {
      const fallback = await fetch(`${basePath}/data/stats-10.json`);
      return fallback.json();
    }
    return res.json();
  }

  const params = new URLSearchParams({ threshold: threshold.toString() });
  const res = await fetch(`${API_BASE}/api/stats?${params}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function triggerCollection(threshold = 0.10): Promise<CollectResponse> {
  if (IS_STATIC) {
    return { status: "static_mode" };
  }
  const params = new URLSearchParams({ threshold: threshold.toString() });
  const res = await fetch(`${API_BASE}/api/collect?${params}`, { method: "POST" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
