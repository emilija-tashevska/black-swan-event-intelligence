"use client";

import { useCallback, useEffect, useState } from "react";
import StatsCards from "@/components/StatsCards";
import BlackSwanTable from "@/components/BlackSwanTable";
import ThresholdSlider from "@/components/ThresholdSlider";
import {
  BlackSwan,
  Stats,
  fetchBlackSwans,
  fetchStats,
  triggerCollection,
} from "@/lib/api";

const IS_STATIC = process.env.NEXT_PUBLIC_STATIC === "true";
const STATIC_THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25];

type SortField = "prediction_price" | "volume_fp" | "close_time" | "open_interest_fp";

export default function Home() {
  const [events, setEvents] = useState<BlackSwan[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [threshold, setThreshold] = useState(0.10);
  const [sort, setSort] = useState<SortField>("volume_fp");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [collectResult, setCollectResult] = useState<string | null>(null);

  const effectiveThreshold = IS_STATIC
    ? STATIC_THRESHOLDS.reduce((prev, curr) =>
        Math.abs(curr - threshold) < Math.abs(prev - threshold) ? curr : prev
      )
    : threshold;

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [bsData, statsData] = await Promise.all([
        fetchBlackSwans(effectiveThreshold, sort, order),
        fetchStats(effectiveThreshold),
      ]);
      setEvents(bsData.black_swans);
      setStats(statsData);
    } catch (err) {
      console.error("Failed to load data:", err);
    } finally {
      setLoading(false);
    }
  }, [effectiveThreshold, sort, order]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSort = (field: SortField) => {
    if (sort === field) {
      setOrder(order === "asc" ? "desc" : "asc");
    } else {
      setSort(field);
      setOrder(field === "prediction_price" ? "asc" : "desc");
    }
  };

  const handleCollect = async () => {
    setCollecting(true);
    setCollectResult(null);
    try {
      const result = await triggerCollection(threshold);
      if (result.status === "already_running") {
        setCollectResult("Collection already in progress...");
      } else if (result.status === "static_mode") {
        setCollectResult("Running in static mode — data is pre-computed.");
      } else {
        setCollectResult(
          `Done! Fetched ${result.total_markets_fetched?.toLocaleString() ?? 0} markets, ` +
          `enriched ${result.yes_markets_enriched?.toLocaleString() ?? 0} with prediction prices.`
        );
        await loadData();
      }
    } catch (err) {
      setCollectResult(`Error: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setCollecting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">
                Black Swan Analytics
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                When were prediction markets wrong? Events that resolved YES with &lt;{(threshold * 100).toFixed(0)}% implied probability.
              </p>
            </div>
            {!IS_STATIC && (
              <button
                onClick={handleCollect}
                disabled={collecting}
                className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:bg-accent/90 disabled:opacity-50 transition-colors self-start"
              >
                {collecting ? (
                  <>
                    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent-foreground border-t-transparent" />
                    Collecting...
                  </>
                ) : (
                  "Fetch from Kalshi"
                )}
              </button>
            )}
          </div>
          {collectResult && (
            <div className="mt-3 rounded-lg bg-muted/50 border border-border px-4 py-2 text-sm text-muted-foreground">
              {collectResult}
            </div>
          )}
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        <StatsCards stats={stats} loading={loading} />

        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <h2 className="text-lg font-semibold">
            Black Swan Events
            {stats && !loading && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                ({stats.total_black_swans} found)
              </span>
            )}
          </h2>
          <ThresholdSlider
            value={threshold}
            onChange={setThreshold}
            steps={IS_STATIC ? STATIC_THRESHOLDS : undefined}
          />
        </div>

        <BlackSwanTable
          events={events}
          loading={loading}
          sort={sort}
          order={order}
          onSort={handleSort}
        />
      </main>

      <footer className="border-t border-border mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <p className="text-xs text-muted-foreground text-center">
            Data sourced from Kalshi prediction markets. Prediction price = daily candlestick close, 7 days before market close.
          </p>
        </div>
      </footer>
    </div>
  );
}
