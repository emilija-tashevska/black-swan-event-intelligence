import type {
  Assessment,
  BlackSwan,
  Calibration,
  CalibrationBucket,
  CalibrationGroup,
  GroupStats,
  Structure,
  Watchlist,
  WatchlistMarket,
} from "./api";
import { STRUCTURE_LABEL, ratio, verdict, type Verdict } from "./calibration";

/** Findings are derived from the data, never hard-coded, so the story stays
 *  true when the pipeline re-runs. */

export type GapStatus = "more" | "less" | "in_line";

export interface GapRow {
  label: string;
  lo: number;
  hi: number;
  n: number;
  events: number;
  priced: number;
  happened: number;
  gap: number; // happened - priced, in probability units
  gapLow: number;
  gapHigh: number;
  status: GapStatus;
}

export function gapRows(buckets: CalibrationBucket[]): GapRow[] {
  return buckets.map((b) => ({
    label: `${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}`,
    lo: b.lo,
    hi: b.hi,
    n: b.n,
    events: b.events,
    priced: b.mean_price,
    happened: b.rate,
    gap: b.rate - b.mean_price,
    gapLow: b.ci_low - b.mean_price,
    gapHigh: b.ci_high - b.mean_price,
    status: b.ci_low > b.mean_price ? "more" : b.ci_high < b.mean_price ? "less" : "in_line",
  }));
}

/** Share of price groups where things happened less often than priced (point estimate). */
export function negativeShare(rows: GapRow[]): number {
  return rows.length ? rows.filter((r) => r.gap < 0).length / rows.length : 0;
}

export interface Headline {
  verdict: Verdict;
  /** False when the verdict doesn't survive the bid/ask midpoint check. */
  robust: boolean;
  ratio: number | null;
  title: string;
  detail: string;
}

export function longshotHeadline(calibration: Calibration): Headline {
  const ls = calibration.overall.longshots;
  const v = verdict(ls);
  const r = ratio(ls);
  const pct = (x: number | null) => (x == null ? "--" : `${(x * 100).toFixed(1)}%`);
  const cutoff = `${Math.round(calibration.longshot_max_price * 100)}%`;
  const detail =
    `Markets priced under ${cutoff} a week before close averaged ${pct(ls.mean_price)}; ` +
    `${pct(ls.rate)} of them actually happened (${ls.yes.toLocaleString()} of ${ls.n.toLocaleString()}).`;
  const check = robustness(calibration);
  const robust = check ? check.holds : true;
  const title =
    v === "overpriced"
      ? robust
        ? "Unlikely events do happen, but less often than the price says."
        : "Unlikely events happen about as often as the price says, if slightly less."
      : v === "underpriced"
        ? robust
          ? "Unlikely events happen more often than the price says."
          : "Unlikely events happen about as often as the price says, if slightly more."
        : v === "in_line"
          ? "Unlikely events happen about as often as the price says."
          : "Not enough history yet to judge longshot prices.";
  return { verdict: v, robust, ratio: r, title, detail };
}

export interface StructureFinding {
  structure: Structure;
  n: number;
  events: number;
  longshots: GroupStats;
  verdict: Verdict;
}

const STRUCTURE_ORDER: Structure[] = ["pick_one", "ladder", "bundle", "standalone", "unknown"];

export function structureFindings(calibration: Calibration): StructureFinding[] {
  return calibration.structures
    .filter((g): g is CalibrationGroup & { structure: Structure } => !!g.structure && g.structure !== "unknown")
    .map((g) => ({
      structure: g.structure,
      n: g.n,
      events: g.events,
      longshots: g.longshots,
      verdict: verdict(g.longshots),
    }))
    .sort((a, b) => STRUCTURE_ORDER.indexOf(a.structure) - STRUCTURE_ORDER.indexOf(b.structure));
}

/** Category × structure segments whose longshots were clearly mispriced,
 *  most markets first, always including the largest one in each direction. */
export function notableSegments(calibration: Calibration, limit = 4): (CalibrationGroup & { verdict: Verdict })[] {
  const flagged = calibration.segments
    .map((g) => ({ ...g, verdict: verdict(g.longshots) }))
    .filter((g) => g.verdict === "overpriced" || g.verdict === "underpriced")
    .sort((a, b) => b.longshots.n - a.longshots.n);
  const leaders = (["overpriced", "underpriced"] as const)
    .map((v) => flagged.find((g) => g.verdict === v))
    .filter((g): g is (typeof flagged)[number] => !!g);
  const rest = flagged.filter((g) => !leaders.includes(g));
  return [...leaders, ...rest].slice(0, limit).sort((a, b) => b.longshots.n - a.longshots.n);
}

/** Most-traded black swans, one per event so a single ladder can't fill the list. */
export function topBlackSwans(rows: BlackSwan[], limit = 5): BlackSwan[] {
  const seen = new Set<string>();
  return [...rows]
    .sort((a, b) => b.volume - a.volume || a.ticker.localeCompare(b.ticker))
    .filter((r) => (seen.has(r.event_ticker) ? false : (seen.add(r.event_ticker), true)))
    .slice(0, limit);
}

/** Watchlist examples: one market per event, alternating directions. */
export function watchlistExamples(watchlist: Watchlist, limit = 6): WatchlistMarket[] {
  const pick = (assessment: Assessment) => {
    const seen = new Set<string>();
    return watchlist.markets
      .filter((m) => m.assessment === assessment)
      .sort((a, b) => b.volume - a.volume)
      .filter((m) => (seen.has(m.event_ticker) ? false : (seen.add(m.event_ticker), true)));
  };
  const more = pick("happens_more_often");
  const less = pick("happens_less_often");
  const out: WatchlistMarket[] = [];
  for (let i = 0; out.length < limit && (i < more.length || i < less.length); i++) {
    if (i < more.length) out.push(more[i]);
    if (i < less.length && out.length < limit) out.push(less[i]);
  }
  return out;
}

/** "Crypto · ladder" -> "Crypto · Threshold ladder". */
export function formatScope(scope: string): string {
  return scope
    .split(" · ")
    .map((part) => (part in STRUCTURE_LABEL ? STRUCTURE_LABEL[part as Structure] : part))
    .join(" · ");
}

export function watchlistCounts(watchlist: Watchlist) {
  const counts = { happens_more_often: 0, in_line: 0, happens_less_often: 0, insufficient_history: 0 };
  for (const m of watchlist.markets) counts[m.assessment] += 1;
  return counts;
}

export interface Robustness {
  markets: number;
  events: number;
  premium: number | null;
  trade: GroupStats;
  mid: GroupStats;
  tradeVerdict: Verdict;
  midVerdict: Verdict;
  belowTrade: number;
  belowMid: number;
  groupsTrade: number;
  groupsMid: number;
  /** Whether longshots get the same verdict on midpoints as the headline (all markets). */
  holds: boolean;
  summary: string;
}

/** Does the headline longshot verdict survive when traded prices are swapped
 *  for bid/ask midpoints? Compared on markets that traded that day and had a
 *  tight book, where both prices exist. */
export function robustness(calibration: Calibration, minMarkets = 500): Robustness | null {
  const check = calibration.midpoint_check;
  if (!check || check.tight_quotes < minMarkets) return null;
  const trade = check.by_trade.longshots;
  const mid = check.by_mid.longshots;
  const overallVerdict = verdict(calibration.overall.longshots);
  const tradeVerdict = verdict(trade);
  const midVerdict = verdict(mid);
  const tradeRows = gapRows(check.by_trade.buckets);
  const midRows = gapRows(check.by_mid.buckets);
  const belowTrade = tradeRows.filter((r) => r.gap < 0).length;
  const belowMid = midRows.filter((r) => r.gap < 0).length;
  const holds = midVerdict === overallVerdict;
  const pct = (x: number | null) => (x == null ? "--" : `${(x * 100).toFixed(1)}%`);
  const premium =
    check.mean_premium == null
      ? "--"
      : `${Math.abs(check.mean_premium * 100).toFixed(1)} pts ${check.mean_premium >= 0 ? "above" : "below"}`;
  const describe = (v: Verdict) =>
    v === "overpriced" ? "happened less often than priced" : v === "underpriced" ? "happened more often than priced" : v === "in_line" ? "were in line with their price" : "were too few to judge";
  const summary =
    `On ${check.tight_quotes.toLocaleString()} markets that traded that day and had a tight book, traded prices sat ${premium} ` +
    `the bid/ask midpoint on average. Priced at midpoints, longshots averaged ${pct(mid.mean_price)} and ${pct(mid.rate)} happened, ` +
    `so they ${describe(midVerdict)}` +
    (holds ? ", consistent with the headline." : `, while across all markets they ${describe(overallVerdict)}: a small gap that partly reflects where trades happen.`) +
    ` Price groups below the zero line: ${belowTrade} of ${tradeRows.length} on traded prices, ${belowMid} of ${midRows.length} on midpoints.`;
  return {
    markets: check.tight_quotes,
    events: check.by_mid.events,
    premium: check.mean_premium,
    trade,
    mid,
    tradeVerdict,
    midVerdict,
    belowTrade,
    belowMid,
    groupsTrade: tradeRows.length,
    groupsMid: midRows.length,
    holds,
    summary,
  };
}
