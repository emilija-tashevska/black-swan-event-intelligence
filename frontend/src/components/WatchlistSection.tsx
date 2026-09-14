"use client";

import type { Assessment, Watchlist } from "@/lib/api";
import { categoryClass } from "@/lib/categories";
import { STRUCTURE_HELP, STRUCTURE_LABEL, daysUntil } from "@/lib/calibration";
import { formatDate, formatPct } from "@/lib/format";
import { formatScope } from "@/lib/story";

interface WatchlistSectionProps {
  watchlist: Watchlist | null;
  error: string | null;
}

const ASSESSMENT: Record<Assessment, { label: string; className: string }> = {
  happens_more_often: { label: "Similar markets happened more often", className: "bg-accent/15 text-accent" },
  in_line: { label: "In line with history", className: "bg-emerald-500/15 text-emerald-300" },
  happens_less_often: { label: "Similar markets happened less often", className: "bg-blue-500/15 text-blue-300" },
  insufficient_history: { label: "Not enough history", className: "bg-zinc-500/15 text-zinc-400" },
};

export default function WatchlistSection({ watchlist, error }: WatchlistSectionProps) {
  if (error) {
    return <p className="rounded-xl border border-accent/30 bg-card p-8 text-center text-sm text-muted-foreground">Couldn&apos;t load watchlist: {error}</p>;
  }
  if (!watchlist) {
    return <p className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">Loading watchlist…</p>;
  }

  const [minDays, maxDays] = watchlist.horizon_days;
  const counts = watchlist.markets.reduce<Record<Assessment, number>>(
    (acc, m) => ({ ...acc, [m.assessment]: acc[m.assessment] + 1 }),
    { happens_more_often: 0, in_line: 0, happens_less_often: 0, insufficient_history: 0 },
  );

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-card p-5 text-sm leading-relaxed text-muted-foreground">
        <p>
          Open markets closing in {minDays}–{maxDays} days and priced under {formatPct(watchlist.max_price, 0)}, each
          compared with <em>similar past markets</em>: same price range a week before close, and the same market type
          and category where there&apos;s enough history. A flag
          means that group of past markets resolved YES more (or less) often than its own average price implied, by
          more than chance would explain.
        </p>
        <p className="mt-2 text-xs">
          This is a base rate, not a forecast about any single market, and not financial advice.
          {watchlist.fetched_at && <> Prices as of {formatDate(watchlist.fetched_at)}.</>}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {(Object.keys(ASSESSMENT) as Assessment[]).map((a) => (
            <span key={a} className={`rounded-full px-2 py-0.5 text-xs ${ASSESSMENT[a].className}`}>
              {ASSESSMENT[a].label}: <span className="tabular-nums font-semibold">{counts[a]}</span>
            </span>
          ))}
        </div>
      </div>

      {watchlist.markets.length === 0 ? (
        <p className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
          No open markets match right now.
        </p>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th scope="col" className="px-4 py-3 font-medium min-w-[280px]">Market</th>
                  <th scope="col" className="px-4 py-3 font-medium">Category</th>
                  <th scope="col" className="px-4 py-3 font-medium text-right whitespace-nowrap">Closes in</th>
                  <th scope="col" className="px-4 py-3 font-medium text-right whitespace-nowrap">Price now</th>
                  <th scope="col" className="px-4 py-3 font-medium text-right whitespace-nowrap">Similar markets happened</th>
                  <th scope="col" className="px-4 py-3 font-medium">History says</th>
                </tr>
              </thead>
              <tbody>
                {watchlist.markets.map((m) => {
                  const days = daysUntil(m.close_time);
                  const b = m.base_rate;
                  return (
                    <tr key={m.ticker} className="border-b border-border/50 align-top">
                      <td className="px-4 py-3">
                        <div className="font-medium leading-snug">{m.title}</div>
                        {m.yes_sub_title && <div className="text-xs text-muted-foreground mt-0.5">{m.yes_sub_title}</div>}
                        <div className="text-xs text-muted-foreground mt-0.5" title={STRUCTURE_HELP[m.structure]}>
                          {STRUCTURE_LABEL[m.structure]}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${categoryClass(m.category)}`}>{m.category}</span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums whitespace-nowrap">
                        {days == null ? "--" : days < 0 ? "closed" : `${days.toFixed(1)}d`}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {formatPct(m.price)}
                        <span className="block text-xs text-muted-foreground whitespace-nowrap">{m.price_source === "quote" ? "bid/ask mid" : "last trade"}</span>
                      </td>
                      <td
                        className="px-4 py-3 text-right tabular-nums whitespace-nowrap"
                        title={
                          b
                            ? `${b.yes} of ${b.n} past markets (${b.events} events; ${formatScope(b.scope)}) priced ` +
                              `${formatPct(b.lo, 0)}–${formatPct(b.hi, 0)} (avg ${formatPct(b.mean_price)}) resolved YES; ` +
                              `95% range ${formatPct(b.ci_low)}–${formatPct(b.ci_high)}`
                            : undefined
                        }
                      >
                        {b ? (
                          <>
                            {formatPct(b.rate)}
                            <span className="text-xs text-muted-foreground"> vs {formatPct(b.mean_price)} priced</span>
                            <span className="block text-xs text-muted-foreground">
                              {formatPct(b.ci_low)}–{formatPct(b.ci_high)} · {b.events.toLocaleString()} events
                              <span className="block">{formatScope(b.scope)}</span>
                            </span>
                          </>
                        ) : (
                          "--"
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded-full px-2 py-0.5 text-xs whitespace-nowrap ${ASSESSMENT[m.assessment].className}`}>
                          {ASSESSMENT[m.assessment].label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
