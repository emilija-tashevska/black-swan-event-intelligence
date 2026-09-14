import type { Meta, Stats } from "@/lib/api";
import { STRUCTURE_HELP, STRUCTURE_LABEL } from "@/lib/calibration";
import { formatDate } from "@/lib/format";

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-5 sm:p-6">
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="mt-3 space-y-2 text-sm text-muted-foreground leading-relaxed">{children}</div>
    </section>
  );
}

export default function MethodologySection({ meta, stats }: { meta: Meta | null; stats: Stats | null }) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Block title="Which markets">
        <p>
          Every settled Kalshi market{meta?.first_close && meta?.last_close ? <> closing {formatDate(meta.first_close)} – {formatDate(meta.last_close)}</> : null},
          from the live and archive APIs, with at least {meta?.min_volume?.toLocaleString() ?? "1,000"} contracts traded.
          Sports and multi-leg parlays are excluded using Kalshi&apos;s own series categories.
        </p>
        <p>
          Markets open for less than 8 days have no full day of trading before the 7-day mark, so they&apos;re left out rather
          than scored on a stale last trade
          {stats ? <> ({stats.short_lived_excluded.toLocaleString()} YES markets excluded)</> : null}. Most are hourly and daily
          crypto markets.
        </p>
      </Block>
      <Block title="The 7-day price">
        <p>
          The closing price of the last daily candle that ended at least {meta?.lookback_days ?? 7} days before the market closed,
          so it never includes later information. If nothing traded that day, the bid/ask midpoint is used when the spread
          is 10¢ or less (marked <sup>q</sup> in the table).
        </p>
        <p>
          <strong className="text-foreground">Black swan:</strong> a market that resolved YES with a 7-day price under the
          chosen threshold (5–25%).
        </p>
      </Block>
      <Block title="Calibration">
        <p>
          All scored markets, YES and NO, are grouped by 7-day price, and each group&apos;s share of YES outcomes is compared with
          its average price. Ranges are 95% Wilson intervals on an effective sample size: markets from the same event move
          together, so the interval is widened by a design effect estimated from between-event variation.
        </p>
        <p>
          A group is called over- or under-priced only when its whole range sits on one side of its average price, with 30+
          markets from 10+ events. The Brier score summarizes accuracy across all prices (lower is better).
        </p>
      </Block>
      <Block title="Market types">
        <ul className="space-y-1.5">
          {(["standalone", "pick_one", "ladder", "bundle"] as const).map((s) => (
            <li key={s}>
              <strong className="text-foreground">{STRUCTURE_LABEL[s]}:</strong> {STRUCTURE_HELP[s]}
            </li>
          ))}
        </ul>
        <p>Labels come from Kalshi&apos;s event data: whether outcomes are mutually exclusive, how many markets the event has, and their strike type.</p>
      </Block>
      <Block title="Open-market watchlist">
        <p>
          Liquid markets closing in 4–10 days (to match the 7-day horizon) and priced under 25%, using a tight bid/ask midpoint
          or the last trade. Each is matched to the most specific historical group with enough data: category × type, then
          type, then category, then all markets.
        </p>
      </Block>
      <Block title="Other measures">
        <p>
          <strong className="text-foreground">Depth @ price:</strong> contracts traded within ±2¢ of the 7-day price that day.{" "}
          <strong className="text-foreground">YES-side upside:</strong> (1 − price) × depth, an upper bound since some buyers
          may have sold before settlement.
        </p>
        <p>
          Headlines are written by Claude{meta?.summary_model ? ` (${meta.summary_model})` : ""} from each market&apos;s title
          and rules. Data from Kalshi&apos;s public API; not affiliated with Kalshi; not financial advice.
        </p>
      </Block>
    </div>
  );
}
