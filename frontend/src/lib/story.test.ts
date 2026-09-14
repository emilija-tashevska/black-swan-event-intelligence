import { describe, expect, it } from "vitest";
import type { BlackSwan, Calibration, CalibrationBucket, CalibrationCurve, GroupStats, Watchlist, WatchlistMarket } from "./api";
import {
  formatScope,
  gapRows,
  longshotHeadline,
  negativeShare,
  notableSegments,
  structureFindings,
  topBlackSwans,
  watchlistExamples,
} from "./story";

function stats(overrides: Partial<GroupStats> = {}): GroupStats {
  return { n: 500, events: 200, yes: 25, mean_price: 0.05, rate: 0.05, ci_low: 0.035, ci_high: 0.07, n_effective: 450, ...overrides };
}

function bucket(lo: number, hi: number, price: number, rate: number, ci: [number, number]): CalibrationBucket {
  return { lo, hi, n: 100, events: 50, yes: Math.round(rate * 100), mean_price: price, rate, ci_low: ci[0], ci_high: ci[1], n_effective: 80 };
}

function curve(longshots: GroupStats, buckets: CalibrationBucket[] = []): CalibrationCurve {
  return { n: 1000, events: 300, brier: 0.1, longshots, buckets };
}

function calibration(overrides: Partial<Calibration> = {}): Calibration {
  return {
    bucket_edges: [], longshot_max_price: 0.1, min_group_markets: 100,
    overall: curve(stats()), categories: [], structures: [], segments: [], ...overrides,
  };
}

describe("gapRows", () => {
  it("computes gaps and status from each bucket's own price and range", () => {
    const [less, fair, more] = gapRows([
      bucket(0, 0.02, 0.009, 0.005, [0.003, 0.008]),
      bucket(0.02, 0.05, 0.028, 0.027, [0.02, 0.037]),
      bucket(0.1, 0.15, 0.118, 0.162, [0.124, 0.208]),
    ]);
    expect(less.status).toBe("less");
    expect(less.label).toBe("0–2");
    expect(less.gap).toBeCloseTo(-0.004);
    expect(fair.status).toBe("in_line");
    expect(more.status).toBe("more");
    expect(more.gapLow).toBeCloseTo(0.006);
    expect(negativeShare([less, fair, more])).toBeCloseTo(2 / 3);
  });
});

describe("longshotHeadline", () => {
  it("says longshots happened less often when the range sits below the price", () => {
    const h = longshotHeadline(calibration({ overall: curve(stats({ mean_price: 0.028, rate: 0.022, ci_low: 0.018, ci_high: 0.027, yes: 151, n: 6732 })) }));
    expect(h.verdict).toBe("overpriced");
    expect(h.title).toMatch(/less often/);
    expect(h.detail).toContain("151 of 6,732");
    expect(h.ratio).toBeCloseTo(0.786, 2);
  });

  it("adapts the story when the data changes", () => {
    expect(longshotHeadline(calibration()).title).toMatch(/about as often/);
    expect(longshotHeadline(calibration({ overall: curve(stats({ rate: 0.09, ci_low: 0.07, ci_high: 0.11 })) })).title).toMatch(/more often/);
    expect(longshotHeadline(calibration({ overall: curve(stats({ n: 5 })) })).title).toMatch(/Not enough/);
  });
});

describe("structureFindings and notableSegments", () => {
  const cal = calibration({
    structures: [
      { ...curve(stats()), category: null, structure: "standalone" },
      { ...curve(stats({ rate: 0.02, ci_low: 0.01, ci_high: 0.03 })), category: null, structure: "pick_one" },
      { ...curve(stats()), category: null, structure: "unknown" },
    ],
    segments: [
      { ...curve(stats({ n: 300, rate: 0.02, ci_low: 0.01, ci_high: 0.03 })), category: "Elections", structure: "pick_one" },
      { ...curve(stats({ n: 900, rate: 0.12, ci_low: 0.08, ci_high: 0.16 })), category: "Crypto", structure: "ladder" },
      { ...curve(stats({ n: 2000 })), category: "Mentions", structure: "bundle" },
    ],
  });

  it("orders types consistently and drops unclassified events", () => {
    expect(structureFindings(cal).map((f) => [f.structure, f.verdict])).toEqual([
      ["pick_one", "overpriced"],
      ["standalone", "in_line"],
    ]);
  });

  it("keeps only clearly mispriced segments, largest first", () => {
    expect(notableSegments(cal).map((g) => g.category)).toEqual(["Crypto", "Elections"]);
  });
});

describe("topBlackSwans", () => {
  it("sorts by volume, keeps one market per event, and doesn't mutate the input", () => {
    const rows = [
      { ticker: "A", event_ticker: "E1", volume: 5 },
      { ticker: "B", event_ticker: "E2", volume: 50 },
      { ticker: "B2", event_ticker: "E2", volume: 40 },
      { ticker: "C", event_ticker: "E3", volume: 20 },
    ] as BlackSwan[];
    expect(topBlackSwans(rows, 3).map((r) => r.ticker)).toEqual(["B", "C", "A"]);
    expect(rows[0].ticker).toBe("A");
  });
});

describe("watchlistExamples and formatScope", () => {
  it("alternates directions with one market per event", () => {
    const m = (ticker: string, event_ticker: string, assessment: string, volume: number) =>
      ({ ticker, event_ticker, assessment, volume }) as unknown as WatchlistMarket;
    const watchlist = {
      markets: [
        m("btc1", "BTC", "happens_more_often", 90), m("btc2", "BTC", "happens_more_often", 80),
        m("eth", "ETH", "happens_more_often", 10), m("swe", "SWE", "happens_less_often", 50),
        m("fair", "X", "in_line", 999),
      ],
    } as Watchlist;
    expect(watchlistExamples(watchlist).map((x) => x.ticker)).toEqual(["btc1", "swe", "eth"]);
  });

  it("uses readable market-type names", () => {
    expect(formatScope("Crypto · ladder")).toBe("Crypto · Threshold ladder");
    expect(formatScope("All categories · pick_one")).toBe("All categories · Pick one of many");
    expect(formatScope("Politics")).toBe("Politics");
  });
});
