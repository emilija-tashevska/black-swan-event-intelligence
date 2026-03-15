"use client";

import { Stats } from "@/lib/api";

function formatPrice(price: number | null): string {
  if (price === null) return "--";
  return `${(price * 100).toFixed(1)}%`;
}

function formatVolume(vol: number): string {
  if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000) return `${(vol / 1_000).toFixed(1)}K`;
  return vol.toFixed(0);
}

function formatDate(iso: string | null): string {
  if (!iso) return "--";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

const CATEGORY_COLORS: Record<string, string> = {
  Crypto: "bg-orange-500/15 text-orange-400",
  Finance: "bg-blue-500/15 text-blue-400",
  Weather: "bg-cyan-500/15 text-cyan-400",
  Entertainment: "bg-purple-500/15 text-purple-400",
  Politics: "bg-red-500/15 text-red-400",
  Business: "bg-emerald-500/15 text-emerald-400",
  Culture: "bg-pink-500/15 text-pink-400",
  Other: "bg-gray-500/15 text-gray-400",
};

interface StatsCardsProps {
  stats: Stats | null;
  loading: boolean;
}

export default function StatsCards({ stats, loading }: StatsCardsProps) {
  const cards = [
    {
      label: "Black Swans Found",
      value: stats ? stats.total_black_swans.toLocaleString() : "--",
      sub: stats ? `of ${stats.total_markets_analyzed.toLocaleString()} markets analyzed` : "",
      accent: true,
    },
    {
      label: "Avg 7-Day Price",
      value: formatPrice(stats?.avg_prediction_price ?? null),
      sub: "market price 7 days before close",
      accent: false,
    },
    {
      label: "Profit at 7d Price",
      value: stats ? (stats.total_profit_at_price >= 1_000_000 ? `$${(stats.total_profit_at_price / 1_000_000).toFixed(1)}M` : `$${formatVolume(stats.total_profit_at_price)}`) : "--",
      sub: "profit for traders who bought at the 7d prediction price",
      accent: false,
    },
    {
      label: "Total Contracts Traded",
      value: stats ? formatVolume(stats.total_volume) : "--",
      sub: stats
        ? `${formatDate(stats.earliest_settlement)} \u2013 ${formatDate(stats.latest_settlement)}`
        : "",
      accent: false,
    },
  ];

  const categoryStats = stats?.category_stats ?? [];
  const topCategories = categoryStats.slice(0, 6);
  const totalBS = stats?.total_black_swans ?? 1;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((card) => (
          <div
            key={card.label}
            className={`rounded-xl border p-5 transition-colors ${
              card.accent
                ? "border-accent/30 bg-accent/5"
                : "border-border bg-card"
            } ${loading ? "animate-pulse" : ""}`}
          >
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">
              {card.label}
            </p>
            <p className={`text-3xl font-bold tabular-nums ${card.accent ? "text-accent" : "text-foreground"}`}>
              {card.value}
            </p>
            {card.sub && (
              <p className="text-xs text-muted-foreground mt-1">{card.sub}</p>
            )}
          </div>
        ))}
      </div>

      {topCategories.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
            Most Unpredictable Categories
          </p>
          <div className="flex flex-wrap gap-3">
            {topCategories.map((cat) => {
              const colorClass = CATEGORY_COLORS[cat.category] || CATEGORY_COLORS.Other;
              const pct = ((cat.count / totalBS) * 100).toFixed(0);
              return (
                <div key={cat.category} className="flex items-center gap-2">
                  <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${colorClass}`}>
                    {cat.category}
                  </span>
                  <span className="text-sm font-semibold tabular-nums">{cat.count}</span>
                  <span className="text-xs text-muted-foreground">({pct}%)</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
