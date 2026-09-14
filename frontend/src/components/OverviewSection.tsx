"use client";

import { useState } from "react";
import { GapChart, StatusLegend, StructureLongshotChart } from "@/components/charts";
import type { BlackSwan, Calibration, Meta, Stats, Watchlist } from "@/lib/api";
import { STRUCTURE_HELP, STRUCTURE_LABEL } from "@/lib/calibration";
import { categoryClass } from "@/lib/categories";
import { formatCompact, formatDate, formatPct } from "@/lib/format";
import {
  gapRows,
  negativeShare,
  longshotHeadline,
  robustness,
  type Robustness,
  notableSegments,
  structureFindings,
  formatScope,
  topBlackSwans,
  watchlistCounts,
  watchlistExamples,
} from "@/lib/story";

type Tab = "swans" | "calibration" | "watchlist" | "methodology";

interface OverviewSectionProps {
  calibration: Calibration | null;
  stats: Stats | null;
  swans: BlackSwan[] | null;
  watchlist: Watchlist | null;
  meta: Meta | null;
  onNavigate: (tab: Tab) => void;
}

function Section({ step, title, children }: { step: number; title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-5 sm:p-6 space-y-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-accent">{step.toString().padStart(2, "0")}</p>
        <h2 className="mt-1 text-xl font-semibold tracking-tight">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg bg-muted/40 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>
    </div>
  );
}

type Basis = "all" | "trade" | "mid";

function GapPanel({ calibration, check }: { calibration: Calibration; check: Robustness | null }) {
  const [basis, setBasis] = useState<Basis>("all");
  const buckets =
    basis === "all" || !calibration.midpoint_check
      ? calibration.overall.buckets
      : basis === "trade"
        ? calibration.midpoint_check.by_trade.buckets
        : calibration.midpoint_check.by_mid.buckets;
  const options: { id: Basis; label: string }[] = [
    { id: "all", label: "All scored markets" },
    { id: "trade", label: "Traded prices" },
    { id: "mid", label: "Bid/ask midpoints" },
  ];
  return (
    <div className="space-y-3">
      {check && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Price basis:</span>
          <div className="inline-flex rounded-md border border-border p-0.5" role="group" aria-label="Price basis">
            {options.map((o) => (
              <button
                key={o.id}
                type="button"
                onClick={() => setBasis(o.id)}
                aria-pressed={basis === o.id}
                className={`rounded px-2.5 py-1 text-xs transition-colors ${
                  basis === o.id ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
          {basis !== "all" && (
            <span className="text-xs text-muted-foreground">
              same {check.markets.toLocaleString()} markets that traded that day with a tight book
            </span>
          )}
        </div>
      )}
      <StatusLegend />
      <GapChart rows={gapRows(buckets)} />
    </div>
  );
}

function LinkButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="text-sm font-medium text-accent hover:underline">
      {children} →
    </button>
  );
}

export default function OverviewSection({ calibration, stats, swans, watchlist, meta, onNavigate }: OverviewSectionProps) {
  if (!calibration || !stats || !swans) {
    return <p className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">Loading findings…</p>;
  }

  const headline = longshotHeadline(calibration);
  const ls = calibration.overall.longshots;
  const rows = gapRows(calibration.overall.buckets);
  const check = robustness(calibration);
  const lessBuckets = rows.filter((r) => r.status === "less");
  const moreBuckets = rows.filter((r) => r.status === "more");
  const findings = structureFindings(calibration);
  const segments = notableSegments(calibration);
  const top = topBlackSwans(swans);
  const counts = watchlist ? watchlistCounts(watchlist) : null;
  const flagged = watchlist ? watchlistExamples(watchlist) : [];
  const period = meta?.first_close && meta?.last_close ? `${formatDate(meta.first_close)} – ${formatDate(meta.last_close)}` : "";

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-accent/30 bg-accent/5 p-5 sm:p-6">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          The short answer{period && <> · markets closing {period}</>}
        </p>
        <h2 className="mt-2 max-w-3xl text-2xl sm:text-3xl font-semibold tracking-tight leading-tight">{headline.title}</h2>
        <p className="mt-3 max-w-3xl text-muted-foreground leading-relaxed">
          {headline.detail}
          {headline.verdict === "overpriced" && headline.robust && headline.ratio != null && (
            <> Buying cheap YES contracts paid out about <strong className="text-foreground">{headline.ratio.toFixed(1)}×</strong> as often as the price implied.</>
          )}
        </p>
        <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Kpi label="Markets scored" value={calibration.overall.n.toLocaleString()} sub={`from ${calibration.overall.events.toLocaleString()} events, YES and NO`} />
          <Kpi label="Black swans" value={stats.total_black_swans.toLocaleString()} sub={`YES outcomes priced under ${formatPct(stats.threshold, 0)}`} />
          <Kpi label="Longshots priced" value={formatPct(ls.mean_price)} sub="average, a week before close" />
          <Kpi label="Longshots happened" value={formatPct(ls.rate)} sub={`95% range ${formatPct(ls.ci_low)}–${formatPct(ls.ci_high)}`} />
        </div>
      </section>

      <Section step={1} title="Surprises happen, and some were big">
        <p className="max-w-3xl text-sm text-muted-foreground leading-relaxed">
          {stats.total_black_swans.toLocaleString()} markets resolved YES after trading below {formatPct(stats.threshold, 0)} a week before close.
          The most heavily traded (one per event):
        </p>
        <ol className="divide-y divide-border/60">
          {top.map((s) => (
            <li key={s.ticker} className="flex items-start gap-4 py-3">
              <span className="mt-0.5 inline-flex min-w-[3.5rem] justify-center rounded-md bg-accent/10 px-2 py-0.5 text-sm font-semibold tabular-nums text-accent">
                {formatPct(s.prediction_price)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-medium leading-snug">{s.ai_summary || s.title}</p>
                <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  <span className={`rounded-full px-2 py-0.5 font-medium ${categoryClass(s.category)}`}>{s.category}</span>
                  <span>{STRUCTURE_LABEL[s.structure]}</span>
                  <span>·</span>
                  <span>{formatDate(s.close_time)}</span>
                  <span>·</span>
                  <span className="tabular-nums">{formatCompact(s.volume)} contracts traded</span>
                </p>
              </div>
            </li>
          ))}
        </ol>
        <LinkButton onClick={() => onNavigate("swans")}>Explore all black swans</LinkButton>
      </Section>

      <Section
        step={2}
        title={
          headline.verdict === "overpriced" && headline.robust
            ? "But across all markets, cheap YES contracts came true less often than priced"
            : "Across every market, prices were close to what happened"
        }
      >
        <p className="max-w-3xl text-sm text-muted-foreground leading-relaxed">
          Black swans alone can&apos;t tell you whether markets were wrong: for every surprise there are many longshots that
          didn&apos;t happen. So every resolved market, YES and NO, is grouped by its price a week before close, and each group&apos;s
          hit rate is compared with its price. A dot on the zero line means the price was honest.
        </p>
        <GapPanel calibration={calibration} check={check} />
        <p className="max-w-3xl text-sm text-muted-foreground leading-relaxed">
          {lessBuckets.length > 0 && (
            <>
              {lessBuckets.length} of {rows.length} price groups came true less often than priced
              ({lessBuckets.map((r) => `${r.label}%`).join(", ")}){moreBuckets.length === 0 ? " and none clearly more often" : ""}.{" "}
            </>
          )}
          {negativeShare(rows) >= 0.7 &&
            (check && check.belowMid / Math.max(check.groupsMid, 1) < 0.6 ? (
              <>
                {Math.round(negativeShare(rows) * rows.length)} of {rows.length} dots sit a little below zero, but most of that tilt
                comes from where trades happen: traded prices sit above the bid/ask midpoint, and on midpoints only{" "}
                {check.belowMid} of {check.groupsMid} groups are below zero.
              </>
            ) : (
              <>
                {Math.round(negativeShare(rows) * rows.length)} of {rows.length} dots sit below zero, at both cheap and expensive
                prices. That suggests the YES side trades a little rich overall, rather than the classic &ldquo;longshots
                overpriced, favourites underpriced&rdquo; pattern.
              </>
            ))}
        </p>
        {check && (
          <div className="rounded-lg bg-muted/40 p-4">
            <p className="text-sm font-medium">
              Robustness check: {check.holds ? "the longshot finding holds on bid/ask midpoints" : "the longshot gap mostly disappears on bid/ask midpoints"}
            </p>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground leading-relaxed">{check.summary}</p>
          </div>
        )}
        <LinkButton onClick={() => onNavigate("calibration")}>Explore the calibration curve</LinkButton>
      </Section>

      <Section
        step={3}
        title={
          findings.some((f) => f.verdict === "overpriced" || f.verdict === "underpriced")
            ? "It depends on how the market is built"
            : segments.length > 0
              ? "By market type prices held up; the gaps are in specific corners"
              : "Prices held up across market types"
        }
      >
        <p className="max-w-3xl text-sm text-muted-foreground leading-relaxed">
          A 2% nominee in a seven-way award race and a 2% standalone yes/no question aren&apos;t the same bet. Each event is
          labelled by structure, and longshots (priced under {formatPct(calibration.longshot_max_price, 0)}) are compared within each type.
        </p>
        <StatusLegend />
        <StructureLongshotChart findings={findings} />
        <div className="grid gap-3 sm:grid-cols-2">
          {findings.map((f) => (
            <div key={f.structure} className="rounded-lg bg-muted/40 p-3">
              <p className="text-sm font-medium">{STRUCTURE_LABEL[f.structure]}</p>
              <p className="mt-1 text-xs text-muted-foreground leading-relaxed">{STRUCTURE_HELP[f.structure]}</p>
            </div>
          ))}
        </div>
        {segments.length > 0 && (
          <div className="text-sm leading-relaxed">
            <p className="text-muted-foreground">Clearest differences within a category and type:</p>
            <ul className="mt-2 space-y-1">
              {segments.map((g) => (
                <li key={`${g.category}-${g.structure}`}>
                  <span className="font-medium">{g.category} · {g.structure ? STRUCTURE_LABEL[g.structure] : ""}</span>
                  <span className="text-muted-foreground">
                    {" "}— priced {formatPct(g.longshots.mean_price)}, happened {formatPct(g.longshots.rate)} (
                    {g.longshots.n.toLocaleString()} markets from {g.longshots.events.toLocaleString()} events):{" "}
                  </span>
                  <span style={{ color: g.verdict === "overpriced" ? "#60a5fa" : "#fb7185" }}>
                    {g.verdict === "overpriced" ? "less often than priced" : "more often than priced"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      {watchlist && counts && (
        <Section step={4} title="What history says about markets open right now">
          <p className="max-w-3xl text-sm text-muted-foreground leading-relaxed">
            {watchlist.markets.length.toLocaleString()} liquid markets close in the next {watchlist.horizon_days[0]}–{watchlist.horizon_days[1]} days
            priced under {formatPct(watchlist.max_price, 0)}. Each is matched to past markets of the same type, category and price.
            {" "}{counts.in_line.toLocaleString()} look in line with history; {counts.happens_more_often} sit in groups that happened more often
            than priced and {counts.happens_less_often} in groups that happened less often.
          </p>
          {flagged.length > 0 && (
            <ul className="divide-y divide-border/60">
              {flagged.map((m) => (
                <li key={m.ticker} className="flex items-start gap-4 py-2.5 text-sm">
                  <span className="mt-0.5 min-w-[3.5rem] text-right font-semibold tabular-nums">{formatPct(m.price)}</span>
                  <div className="min-w-0 flex-1">
                    <p className="leading-snug">{m.title}{m.yes_sub_title ? ` — ${m.yes_sub_title}` : ""}</p>
                    {m.base_rate && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        Similar markets ({formatScope(m.base_rate.scope)}) priced {formatPct(m.base_rate.mean_price)}, happened{" "}
                        <span style={{ color: m.assessment === "happens_more_often" ? "#fb7185" : "#60a5fa" }}>{formatPct(m.base_rate.rate)}</span>
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <LinkButton onClick={() => onNavigate("watchlist")}>See the full watchlist</LinkButton>
        </Section>
      )}

      <section className="rounded-xl border border-border bg-card p-5 sm:p-6">
        <h2 className="text-sm font-semibold">Read with care</h2>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-muted-foreground leading-relaxed">
          <li>Ranges are 95% intervals widened for markets that share an event, but related events (e.g. daily crypto ladders on the same coin) can still move together.</li>
          {check ? (
            <li>
              Prices are same-day trades or tight bid/ask midpoints; markets with neither are left out. Traded prices sat{" "}
              {check.premium == null ? "--" : `${check.premium >= 0 ? "+" : ""}${(check.premium * 100).toFixed(1)} pts`} from the
              midpoint on average, and the robustness check above shows whether that changes the conclusion.
            </li>
          ) : (
            <li>Prices are same-day trades or tight bid/ask midpoints. If most trades hit the ask, traded YES prices sit slightly above the midpoint.</li>
          )}
          <li>Base rates describe groups of past markets, not the odds of any single open market. Nothing here is financial advice.</li>
        </ul>
        <div className="mt-3">
          <LinkButton onClick={() => onNavigate("methodology")}>How this was measured</LinkButton>
        </div>
      </section>
    </div>
  );
}
