"use client";

import { useState } from "react";
import { BlackSwan } from "@/lib/api";

function formatPct(price: number): string {
  return `${(price * 100).toFixed(1)}%`;
}

function formatDollars(dollars: string): string {
  const val = parseFloat(dollars);
  return `$${val.toFixed(2)}`;
}

function formatVolume(vol: string | number): string {
  const v = typeof vol === "string" ? parseFloat(vol) : vol;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
}

function formatDate(iso: string | null): string {
  if (!iso) return "--";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatMoney(amount: number): string {
  if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `$${(amount / 1_000).toFixed(0)}K`;
  return `$${amount.toFixed(0)}`;
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

type SortField = "prediction_price" | "volume_fp" | "close_time" | "open_interest_fp";

interface BlackSwanTableProps {
  events: BlackSwan[];
  loading: boolean;
  sort: SortField;
  order: "asc" | "desc";
  onSort: (field: SortField) => void;
}

function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="ml-1 inline-flex items-center" title={text}>
      <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-muted-foreground/40 text-[9px] font-bold text-muted-foreground cursor-help leading-none">
        i
      </span>
    </span>
  );
}

export default function BlackSwanTable({
  events,
  loading,
  sort,
  order,
  onSort,
}: BlackSwanTableProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const sortIcon = (field: SortField) => {
    if (sort !== field) return " ↕";
    return order === "asc" ? " ↑" : " ↓";
  };

  if (loading && events.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-12 text-center">
        <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        <p className="mt-3 text-sm text-muted-foreground">Loading black swan events...</p>
      </div>
    );
  }

  if (!loading && events.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-12 text-center">
        <p className="text-4xl mb-3">0</p>
        <p className="text-sm text-muted-foreground">
          No black swan events found. Try running data collection first, or adjust the probability threshold.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="px-4 py-3 font-medium text-muted-foreground">#</th>
              <th className="px-4 py-3 font-medium text-muted-foreground min-w-[320px]">Event</th>
              <th className="px-4 py-3 font-medium text-muted-foreground whitespace-nowrap">Category</th>
              <th
                className="px-4 py-3 font-medium text-muted-foreground cursor-pointer hover:text-foreground whitespace-nowrap"
                onClick={() => onSort("prediction_price")}
              >
                7d Price
                <InfoTooltip text="Market price 7 days before close = implied probability" />
                {sortIcon("prediction_price")}
              </th>
              <th className="px-4 py-3 font-medium text-muted-foreground whitespace-nowrap">
                Last Price
                <InfoTooltip text="Final traded price before settlement" />
              </th>
              <th
                className="px-4 py-3 font-medium text-muted-foreground cursor-pointer hover:text-foreground whitespace-nowrap"
                onClick={() => onSort("volume_fp")}
              >
                Volume
                <InfoTooltip text="Total contracts traded over the market's lifetime" />
                {sortIcon("volume_fp")}
              </th>
              <th className="px-4 py-3 font-medium text-muted-foreground whitespace-nowrap">
                7d Vol
                <InfoTooltip text="Total contracts traded on the day 7 days before close" />
              </th>
              <th className="px-4 py-3 font-medium text-muted-foreground whitespace-nowrap">
                Depth @ Price
                <InfoTooltip text="Contracts traded within ±2¢ of the 7d price on prediction day" />
              </th>
              <th
                className="px-4 py-3 font-medium text-muted-foreground cursor-pointer hover:text-foreground whitespace-nowrap"
                onClick={() => onSort("open_interest_fp")}
              >
                Payout
                <InfoTooltip text="Open interest at settlement = total $ paid to YES holders" />
                {sortIcon("open_interest_fp")}
              </th>
              <th
                className="px-4 py-3 font-medium text-muted-foreground cursor-pointer hover:text-foreground whitespace-nowrap"
                onClick={() => onSort("close_time")}
              >
                Settled{sortIcon("close_time")}
              </th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev, idx) => {
              const oi = parseFloat(ev.open_interest_fp || "0");
              const catColor = CATEGORY_COLORS[ev.category] || CATEGORY_COLORS.Other;

              return (
                <>
                  <tr
                    key={ev.ticker}
                    className="border-b border-border/50 hover:bg-muted/30 cursor-pointer transition-colors"
                    onClick={() => setExpanded(expanded === ev.ticker ? null : ev.ticker)}
                  >
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">{idx + 1}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-foreground leading-snug">
                        {ev.ai_summary || ev.title}
                      </div>
                      {ev.ai_summary && (
                        <div className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {ev.title}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {ev.category && (
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${catColor}`}>
                          {ev.category}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center rounded-md bg-accent/10 px-2 py-0.5 text-accent font-semibold tabular-nums">
                        {formatPct(ev.prediction_price)}
                      </span>
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {formatDollars(ev.last_price_dollars)}
                    </td>
                    <td className="px-4 py-3 tabular-nums">{formatVolume(ev.volume_fp)}</td>
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">
                      {ev.prediction_volume != null ? formatVolume(ev.prediction_volume) : "--"}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">
                      {ev.volume_at_price != null ? formatVolume(ev.volume_at_price) : "--"}
                    </td>
                    <td className="px-4 py-3 tabular-nums font-medium">
                      {oi > 0 ? formatMoney(oi) : "--"}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                      {formatDate(ev.close_time)}
                    </td>
                  </tr>
                  {expanded === ev.ticker && (
                    <tr key={`${ev.ticker}-detail`} className="border-b border-border/50 bg-muted/10">
                      <td colSpan={10} className="px-6 py-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
                          <div>
                            <p className="text-muted-foreground text-xs uppercase tracking-wider mb-1">Market Rules</p>
                            <p className="text-foreground/80 leading-relaxed">{ev.rules_primary || "No rules available"}</p>
                          </div>
                          <div className="space-y-2">
                            <div className="flex justify-between">
                              <span className="text-muted-foreground">Outcome</span>
                              <span className="font-medium">{ev.yes_sub_title}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-muted-foreground">Last Trade Price</span>
                              <span className="tabular-nums">{formatDollars(ev.last_price_dollars)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-muted-foreground">Settlement Date</span>
                              <span>{formatDate(ev.settlement_ts)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-muted-foreground">Prediction Date</span>
                              <span>
                                {ev.prediction_ts
                                  ? formatDate(new Date(ev.prediction_ts * 1000).toISOString())
                                  : "--"}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-muted-foreground">Open Interest at Settlement</span>
                              <span className="tabular-nums">{formatVolume(ev.open_interest_fp)} contracts</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-muted-foreground">YES Bid / Ask</span>
                              <span className="tabular-nums">
                                {formatDollars(ev.yes_bid_dollars)} / {formatDollars(ev.yes_ask_dollars)}
                              </span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-muted-foreground">Ticker</span>
                              <span className="font-mono text-xs">{ev.ticker}</span>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
