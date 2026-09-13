export const IS_STATIC = process.env.NEXT_PUBLIC_STATIC === "true";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

export const STATIC_THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.25];

export interface BlackSwan {
  ticker: string;
  event_ticker: string;
  series_ticker: string;
  category: string;
  title: string;
  yes_sub_title: string;
  rules_primary: string;
  open_time: string | null;
  close_time: string | null;
  settlement_ts: string | null;
  last_price: number;
  volume: number;
  open_interest: number;
  prediction_price: number;
  prediction_source: "trade" | "quote" | null;
  prediction_ts: number | null;
  prediction_volume: number | null;
  volume_at_price: number | null;
  ai_summary: string;
}

export interface CategoryStat {
  category: string;
  count: number;
  scored: number;
  rate: number | null;
}

export interface Stats {
  threshold: number;
  total_black_swans: number;
  avg_prediction_price: number | null;
  lowest_prediction_price: number | null;
  total_volume: number;
  yes_side_upside: number;
  earliest_close: string | null;
  latest_close: string | null;
  markets_collected: number;
  yes_markets: number;
  markets_scored: number;
  short_lived_excluded: number;
  category_stats: CategoryStat[];
}

export interface Meta {
  exported_at: string;
  data_as_of: string | null;
  lookback_days: number;
  min_volume: number;
  summary_model: string;
}

export type SortField =
  | "prediction_price"
  | "volume"
  | "close_time"
  | "open_interest"
  | "volume_at_price";
export type SortOrder = "asc" | "desc";

export interface Query {
  threshold: number;
  sort: SortField;
  order: SortOrder;
  category: string | null;
}

export function nearestThreshold(value: number, steps: number[] = STATIC_THRESHOLDS): number {
  return steps.reduce((best, s) => (Math.abs(s - value) < Math.abs(best - value) ? s : best));
}

/** Sort and filter client-side, mirroring the API's ordering: nulls always last. */
export function applyQuery(items: BlackSwan[], q: Pick<Query, "sort" | "order" | "category">) {
  const filtered = q.category ? items.filter((i) => i.category === q.category) : [...items];
  const dir = q.order === "asc" ? 1 : -1;
  return filtered.sort((a, b) => {
    const av = a[q.sort];
    const bv = b[q.sort];
    if (av == null && bv == null) return a.ticker.localeCompare(b.ticker);
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = typeof av === "number" && typeof bv === "number"
      ? av - bv
      : String(av).localeCompare(String(bv));
    return cmp !== 0 ? cmp * dir : a.ticker.localeCompare(b.ticker);
  });
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed (${res.status}): ${url}`);
  return res.json();
}

export async function fetchBlackSwans(q: Query): Promise<BlackSwan[]> {
  if (IS_STATIC) {
    const pct = Math.round(nearestThreshold(q.threshold) * 100);
    const data = await getJson<{ black_swans: BlackSwan[] }>(
      `${BASE_PATH}/data/black-swans-${pct}.json`,
    );
    return applyQuery(data.black_swans, q);
  }
  const params = new URLSearchParams({
    threshold: String(q.threshold),
    sort: q.sort,
    order: q.order,
    limit: "1000",
  });
  if (q.category) params.set("category", q.category);
  const data = await getJson<{ black_swans: BlackSwan[] }>(`${API_BASE}/api/black-swans?${params}`);
  return data.black_swans;
}

export async function fetchStats(threshold: number): Promise<Stats> {
  if (IS_STATIC) {
    const pct = Math.round(nearestThreshold(threshold) * 100);
    return getJson<Stats>(`${BASE_PATH}/data/stats-${pct}.json`);
  }
  return getJson<Stats>(`${API_BASE}/api/stats?threshold=${threshold}`);
}

export async function fetchMeta(): Promise<Meta | null> {
  if (!IS_STATIC) return null;
  try {
    return await getJson<Meta>(`${BASE_PATH}/data/meta.json`);
  } catch {
    return null;
  }
}
