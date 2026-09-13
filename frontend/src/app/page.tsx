"use client";

import { useEffect, useState } from "react";
import BlackSwanTable from "@/components/BlackSwanTable";
import StatsCards from "@/components/StatsCards";
import ThresholdSlider from "@/components/ThresholdSlider";
import {
  BlackSwan,
  IS_STATIC,
  Meta,
  STATIC_THRESHOLDS,
  SortField,
  SortOrder,
  Stats,
  fetchBlackSwans,
  fetchMeta,
  fetchStats,
  nearestThreshold,
} from "@/lib/api";
import { formatDate } from "@/lib/format";

export default function Home() {
  const [events, setEvents] = useState<BlackSwan[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [threshold, setThreshold] = useState(0.1);
  const [sort, setSort] = useState<SortField>("volume");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [category, setCategory] = useState<string | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const effectiveThreshold = IS_STATIC ? nearestThreshold(threshold) : threshold;
  const queryKey = JSON.stringify([effectiveThreshold, sort, order, category]);
  const loading = loadedKey !== queryKey;

  useEffect(() => {
    fetchMeta().then(setMeta);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchBlackSwans({ threshold: effectiveThreshold, sort, order, category }),
      fetchStats(effectiveThreshold),
    ])
      .then(([rows, s]) => {
        if (cancelled) return;
        setEvents(rows);
        setStats(s);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(queryKey);
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveThreshold, sort, order, category, queryKey]);

  const handleSort = (field: SortField) => {
    if (sort === field) {
      setOrder(order === "asc" ? "desc" : "asc");
    } else {
      setSort(field);
      setOrder(field === "prediction_price" || field === "close_time" ? "asc" : "desc");
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <h1 className="text-2xl font-bold tracking-tight">Black Swan Event Intelligence</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            When were prediction markets wrong? Kalshi markets that resolved YES even though traders
            priced them below {(effectiveThreshold * 100).toFixed(0)}% a week before close.
          </p>
          {meta?.data_as_of && (
            <p className="mt-2 text-xs text-muted-foreground">
              Data as of {formatDate(meta.data_as_of)}
            </p>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
        <StatsCards stats={stats} loading={loading} category={category} onCategory={setCategory} />

        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-lg font-semibold">
            {category ? `${category} black swans` : "Black swan events"}
            {!loading && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                ({events.length.toLocaleString()} shown)
              </span>
            )}
          </h2>
          <ThresholdSlider
            value={effectiveThreshold}
            onChange={setThreshold}
            steps={IS_STATIC ? STATIC_THRESHOLDS : undefined}
          />
        </div>

        <BlackSwanTable
          events={events}
          loading={loading}
          error={error}
          sort={sort}
          order={order}
          onSort={handleSort}
        />

        <section className="rounded-xl border border-border bg-card p-5 text-sm leading-relaxed text-muted-foreground">
          <h2 className="mb-2 text-xs font-medium uppercase tracking-wider">Methodology</h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              Settled Kalshi markets with at least 1,000 contracts traded. Sports and multi-leg
              parlays are excluded using Kalshi&apos;s own series categories.
            </li>
            <li>
              The <strong className="text-foreground">7-day price</strong> is the closing price of the
              last daily candle that ended at least 7 days before the market closed, so it never
              includes later information. If nothing traded that day, the bid/ask midpoint is used
              when the spread is 10¢ or less (marked <sup>q</sup>).
            </li>
            <li>
              Markets open for less than 7 days have no week-ahead price and are left out
              {stats ? ` (${stats.short_lived_excluded.toLocaleString()} excluded)` : ""}.
            </li>
            <li>
              <strong className="text-foreground">YES-side upside</strong> is (1 − price) × contracts
              traded within ±2¢ of that price on that day: an upper bound, since some of those buyers
              may have exited before settlement.
            </li>
            <li>
              Headlines are generated by Claude{meta?.summary_model ? ` (${meta.summary_model})` : ""}{" "}
              from each market&apos;s title and rules.
            </li>
          </ul>
        </section>
      </main>

      <footer className="mt-12 border-t border-border">
        <div className="mx-auto max-w-7xl px-4 py-6 text-center text-xs text-muted-foreground sm:px-6 lg:px-8">
          Data from Kalshi&apos;s public API. Not affiliated with Kalshi. Not financial advice.
        </div>
      </footer>
    </div>
  );
}
