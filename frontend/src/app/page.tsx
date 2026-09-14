"use client";

import { useCallback, useEffect, useState } from "react";
import BlackSwanTable from "@/components/BlackSwanTable";
import CalibrationSection from "@/components/CalibrationSection";
import MethodologySection from "@/components/MethodologySection";
import OverviewSection from "@/components/OverviewSection";
import StatsCards from "@/components/StatsCards";
import ThresholdSlider from "@/components/ThresholdSlider";
import WatchlistSection from "@/components/WatchlistSection";
import {
  BlackSwan,
  Calibration,
  IS_STATIC,
  Meta,
  STATIC_THRESHOLDS,
  SortField,
  SortOrder,
  Stats,
  Watchlist,
  fetchBlackSwans,
  fetchCalibration,
  fetchMeta,
  fetchStats,
  fetchWatchlist,
  nearestThreshold,
} from "@/lib/api";
import { formatDate } from "@/lib/format";

type Tab = "overview" | "swans" | "calibration" | "watchlist" | "methodology";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "swans", label: "Black swans" },
  { id: "calibration", label: "Calibration" },
  { id: "watchlist", label: "Open-market watchlist" },
  { id: "methodology", label: "Methodology" },
];

const OVERVIEW_THRESHOLD = 0.1;

function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err);
}

function tabFromHash(): Tab {
  if (typeof window === "undefined") return "overview";
  const id = window.location.hash.replace("#", "");
  return TABS.some((t) => t.id === id) ? (id as Tab) : "overview";
}

export default function Home() {
  const [tab, setTabState] = useState<Tab>("overview");
  const [meta, setMeta] = useState<Meta | null>(null);
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [calibrationError, setCalibrationError] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<Watchlist | null>(null);
  const [watchlistError, setWatchlistError] = useState<string | null>(null);
  const [overviewStats, setOverviewStats] = useState<Stats | null>(null);
  const [overviewSwans, setOverviewSwans] = useState<BlackSwan[] | null>(null);

  const [events, setEvents] = useState<BlackSwan[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [threshold, setThreshold] = useState(0.1);
  const [sort, setSort] = useState<SortField>("volume");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [category, setCategory] = useState<string | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const effectiveThreshold = IS_STATIC ? nearestThreshold(threshold) : threshold;
  const queryKey = JSON.stringify([effectiveThreshold, sort, order, category]);
  const loading = loadedKey !== queryKey;

  const setTab = useCallback((next: Tab) => {
    setTabState(next);
    window.history.replaceState(null, "", next === "overview" ? window.location.pathname : `#${next}`);
    window.scrollTo({ top: 0 });
  }, []);

  useEffect(() => {
    const sync = () => setTabState(tabFromHash());
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  useEffect(() => {
    fetchMeta().then(setMeta);
    fetchCalibration().then(setCalibration, (e) => setCalibrationError(errorText(e)));
    fetchWatchlist().then(setWatchlist, (e) => setWatchlistError(errorText(e)));
    fetchStats(OVERVIEW_THRESHOLD).then(setOverviewStats, () => undefined);
    fetchBlackSwans({ threshold: OVERVIEW_THRESHOLD, sort: "volume", order: "desc", category: null }).then(
      setOverviewSwans,
      () => undefined,
    );
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
        if (!cancelled) setError(errorText(err));
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
        <div className="mx-auto max-w-7xl px-4 pt-6 sm:px-6 lg:px-8">
          <h1 className="text-2xl font-bold tracking-tight">Black Swan Event Intelligence</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            How often do unlikely events on Kalshi&apos;s prediction markets actually happen, and were the prices right?
          </p>
          {meta?.data_as_of && (
            <p className="mt-2 text-xs text-muted-foreground">Data as of {formatDate(meta.data_as_of)}</p>
          )}
          <nav className="mt-5 flex gap-1 overflow-x-auto" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                aria-current={tab === t.id ? "page" : undefined}
                className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  tab === t.id
                    ? "border-accent text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
        {tab === "overview" && (
          <OverviewSection
            calibration={calibration}
            stats={overviewStats}
            swans={overviewSwans}
            watchlist={watchlist}
            meta={meta}
            onNavigate={setTab}
          />
        )}
        {tab === "calibration" && <CalibrationSection calibration={calibration} error={calibrationError} />}
        {tab === "watchlist" && <WatchlistSection watchlist={watchlist} error={watchlistError} />}
        {tab === "methodology" && <MethodologySection meta={meta} stats={overviewStats} />}
        {tab === "swans" && (
          <>
            <p className="max-w-3xl text-sm text-muted-foreground leading-relaxed">
              Kalshi markets that resolved YES even though traders priced them below{" "}
              {(effectiveThreshold * 100).toFixed(0)}% a week before close. Click a row for the market&apos;s rules and details.
            </p>
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
          </>
        )}
      </main>

      <footer className="mt-12 border-t border-border">
        <div className="mx-auto max-w-7xl px-4 py-6 text-center text-xs text-muted-foreground sm:px-6 lg:px-8">
          Data from Kalshi&apos;s public API. Not affiliated with Kalshi. Not financial advice.
        </div>
      </footer>
    </div>
  );
}
