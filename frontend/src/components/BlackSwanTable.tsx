"use client";

import { Fragment, useState } from "react";
import { BlackSwan, SortField, SortOrder } from "@/lib/api";
import { STRUCTURE_HELP, STRUCTURE_LABEL } from "@/lib/calibration";
import { categoryClass } from "@/lib/categories";
import {
  formatCompact,
  formatDate,
  formatDollars,
  formatMoney,
  formatPct,
  formatUnixDate,
} from "@/lib/format";

interface BlackSwanTableProps {
  events: BlackSwan[];
  loading: boolean;
  error: string | null;
  sort: SortField;
  order: SortOrder;
  onSort: (field: SortField) => void;
}

const COLUMNS: { label: string; help?: string; sort?: SortField }[] = [
  { label: "#" },
  { label: "Event" },
  { label: "Category / type" },
  { label: "7d price", help: "Last closing price at least 7 days before close: the crowd's implied probability", sort: "prediction_price" },
  { label: "Volume", help: "Contracts traded over the market's lifetime", sort: "volume" },
  { label: "7d volume", help: "Contracts traded during the day the 7d price was taken" },
  { label: "Depth @ price", help: "Contracts traded within ±2¢ of the 7d price that day", sort: "volume_at_price" },
  { label: "Closed", sort: "close_time" },
];

function InfoTooltip({ text }: { text: string }) {
  return (
    <span
      className="ml-1 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full border border-muted-foreground/40 text-[9px] font-bold leading-none text-muted-foreground cursor-help"
      title={text}
      aria-label={text}
    >
      i
    </span>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right tabular-nums">{children}</span>
    </div>
  );
}

export default function BlackSwanTable({ events, loading, error, sort, order, onSort }: BlackSwanTableProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (error) {
    return (
      <div className="rounded-xl border border-accent/30 bg-card p-12 text-center text-sm text-muted-foreground">
        Couldn&apos;t load data: {error}
      </div>
    );
  }

  if (loading && events.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-12 text-center">
        <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        <p className="mt-3 text-sm text-muted-foreground">Loading black swan events…</p>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-12 text-center text-sm text-muted-foreground">
        No black swans at this threshold. Try raising it, or clearing the category filter.
      </div>
    );
  }

  const sortIcon = (field?: SortField) =>
    !field ? "" : sort !== field ? " ↕" : order === "asc" ? " ↑" : " ↓";

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              {COLUMNS.map((col) => (
                <th
                  key={col.label}
                  scope="col"
                  aria-sort={col.sort && sort === col.sort ? (order === "asc" ? "ascending" : "descending") : undefined}
                  className={`px-4 py-3 font-medium text-muted-foreground whitespace-nowrap ${
                    col.label === "Event" ? "min-w-[320px]" : ""
                  }`}
                >
                  {col.sort ? (
                    <button type="button" onClick={() => onSort(col.sort!)} className="hover:text-foreground">
                      {col.label}
                      {sortIcon(col.sort)}
                    </button>
                  ) : (
                    col.label
                  )}
                  {col.help && <InfoTooltip text={col.help} />}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.map((ev, idx) => {
              const isOpen = expanded === ev.ticker;
              return (
                <Fragment key={ev.ticker}>
                  <tr
                    className="border-b border-border/50 hover:bg-muted/30 cursor-pointer transition-colors"
                    onClick={() => setExpanded(isOpen ? null : ev.ticker)}
                    aria-expanded={isOpen}
                  >
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">{idx + 1}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium leading-snug">{ev.ai_summary || ev.title}</div>
                      {ev.ai_summary && (
                        <div className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {ev.title}
                          {ev.yes_sub_title ? ` — ${ev.yes_sub_title}` : ""}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {ev.category && (
                        <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${categoryClass(ev.category)}`}>
                          {ev.category}
                        </span>
                      )}
                      <span className="mt-1 block text-xs text-muted-foreground whitespace-nowrap" title={STRUCTURE_HELP[ev.structure]}>
                        {STRUCTURE_LABEL[ev.structure]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className="inline-flex rounded-md bg-accent/10 px-2 py-0.5 font-semibold tabular-nums text-accent"
                        title={ev.prediction_source === "quote" ? "From the bid/ask midpoint: nothing traded that day" : undefined}
                      >
                        {formatPct(ev.prediction_price)}
                        {ev.prediction_source === "quote" && <sup className="ml-0.5 text-[10px]">q</sup>}
                      </span>
                    </td>
                    <td className="px-4 py-3 tabular-nums">{formatCompact(ev.volume)}</td>
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">{formatCompact(ev.prediction_volume)}</td>
                    <td className="px-4 py-3 tabular-nums text-muted-foreground">{formatCompact(ev.volume_at_price)}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">{formatDate(ev.close_time)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-border/50 bg-muted/10">
                      <td colSpan={COLUMNS.length} className="px-6 py-4">
                        <div className="grid grid-cols-1 gap-6 text-sm md:grid-cols-2">
                          <div>
                            <p className="mb-1 text-xs uppercase tracking-wider text-muted-foreground">Market rules</p>
                            <p className="leading-relaxed text-foreground/80">{ev.rules_primary || "No rules available"}</p>
                          </div>
                          <div className="space-y-2">
                            <Detail label="Outcome">{ev.yes_sub_title || "--"}</Detail>
                            <Detail label="7d price taken">{formatUnixDate(ev.prediction_ts)}</Detail>
                            <Detail label="7d price source">
                              {ev.prediction_source === "quote" ? "Bid/ask midpoint (no trades that day)" : "Traded price"}
                            </Detail>
                            <Detail label="Opened">{formatDate(ev.open_time)}</Detail>
                            <Detail label="Settled">{formatDate(ev.settlement_ts)}</Detail>
                            <Detail label="Last trade">{formatDollars(ev.last_price)}</Detail>
                            <Detail label="Open interest">{formatCompact(ev.open_interest)} contracts</Detail>
                            <Detail label="YES upside at depth">
                              {ev.volume_at_price != null
                                ? formatMoney((1 - ev.prediction_price) * ev.volume_at_price)
                                : "--"}
                            </Detail>
                            <Detail label="Ticker">
                              <span className="font-mono text-xs">{ev.ticker}</span>
                            </Detail>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
