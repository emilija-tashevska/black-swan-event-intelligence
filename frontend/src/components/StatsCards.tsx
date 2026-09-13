"use client";

import { Stats } from "@/lib/api";
import { categoryClass } from "@/lib/categories";
import { formatCompact, formatDate, formatMoney, formatPct } from "@/lib/format";

interface StatsCardsProps {
  stats: Stats | null;
  loading: boolean;
  category: string | null;
  onCategory: (category: string | null) => void;
}

export default function StatsCards({ stats, loading, category, onCategory }: StatsCardsProps) {
  const cards = [
    {
      label: "Black swans",
      value: stats ? stats.total_black_swans.toLocaleString() : "--",
      sub: stats
        ? `of ${stats.markets_scored.toLocaleString()} YES markets scored`
        : "",
      accent: true,
    },
    {
      label: "Avg 7-day price",
      value: formatPct(stats?.avg_prediction_price),
      sub: stats ? `lowest ${formatPct(stats.lowest_prediction_price)}` : "",
    },
    {
      label: "YES-side upside",
      value: stats ? formatMoney(stats.yes_side_upside) : "--",
      sub: "upper bound for contracts traded near the 7-day price",
    },
    {
      label: "Contracts traded",
      value: stats ? formatCompact(stats.total_volume) : "--",
      sub: stats ? `${formatDate(stats.earliest_close)} – ${formatDate(stats.latest_close)}` : "",
    },
  ];

  const categories = stats?.category_stats ?? [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((card) => (
          <div
            key={card.label}
            className={`rounded-xl border p-5 ${
              card.accent ? "border-accent/30 bg-accent/5" : "border-border bg-card"
            } ${loading ? "animate-pulse" : ""}`}
          >
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">
              {card.label}
            </p>
            <p
              className={`text-3xl font-bold tabular-nums ${
                card.accent ? "text-accent" : "text-foreground"
              }`}
            >
              {card.value}
            </p>
            {card.sub && <p className="text-xs text-muted-foreground mt-1">{card.sub}</p>}
          </div>
        ))}
      </div>

      {categories.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              By category
            </p>
            <p className="text-xs text-muted-foreground">
              share of each category&apos;s scored YES markets that were black swans · click to filter
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onCategory(null)}
              aria-pressed={category === null}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                category === null
                  ? "border-foreground/40 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              All
            </button>
            {categories.map((c) => {
              const active = category === c.category;
              return (
                <button
                  type="button"
                  key={c.category}
                  onClick={() => onCategory(active ? null : c.category)}
                  aria-pressed={active}
                  className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs transition-colors ${
                    active ? "border-foreground/40" : "border-transparent hover:border-border"
                  }`}
                >
                  <span className={`rounded-full px-2 py-0.5 font-medium ${categoryClass(c.category)}`}>
                    {c.category}
                  </span>
                  <span className="font-semibold tabular-nums">{c.count}</span>
                  {c.rate != null && (
                    <span className="text-muted-foreground tabular-nums">{formatPct(c.rate, 0)}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
