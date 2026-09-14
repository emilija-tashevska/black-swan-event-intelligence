import { describe, expect, it } from "vitest";
import type { BlackSwan, Calibration, CalibrationBucket, CalibrationCurve, GroupStats, Watchlist, WatchlistMarket } from "./api";
import {
  formatScope,
  gapRows,
  longshotHeadline,
  negativeShare,
  notableSegments,
  robustness,
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

  it("always includes the largest segment in each direction", () => {
    const over = (category: string, n: number) =>
      ({ ...curve(stats({ n, rate: 0.02, ci_low: 0.01, ci_high: 0.03 })), category, structure: "pick_one" as const });
    const many = calibration({
      segments: [over("A", 1400), over("B", 900), over("C", 600),
        { ...curve(stats({ n: 300, rate: 0.12, ci_low: 0.08, ci_high: 0.16 })), category: "Crypto", structure: "ladder" }],
    });
    expect(notableSegments(many, 3).map((g) => g.category)).toEqual(["A", "B", "Crypto"]);
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

describe("robustness", () => {
  const check = (tradeLs: Partial<GroupStats>, midLs: Partial<GroupStats>, tight = 5000, premium = 0.005) => ({
    max_spread: 0.1, markets: 9000, with_quotes: 8000, tight_quotes: tight, mean_premium: premium,
    premium_by_bucket: [],
    by_trade: curve(stats(tradeLs), [bucket(0, 0.02, 0.01, 0.005, [0.003, 0.02]), bucket(0.5, 0.6, 0.55, 0.52, [0.45, 0.6])]),
    by_mid: curve(stats(midLs), [bucket(0, 0.02, 0.01, 0.012, [0.005, 0.02]), bucket(0.5, 0.6, 0.54, 0.52, [0.45, 0.6])]),
  });
  const overpricedOverall = curve(stats({ mean_price: 0.025, rate: 0.02, ci_low: 0.016, ci_high: 0.024 }));

  it("holds when midpoints give the same verdict as the headline", () => {
    const cal = calibration({
      overall: overpricedOverall,
      midpoint_check: check({}, { mean_price: 0.045, rate: 0.02, ci_low: 0.015, ci_high: 0.03 }),
    });
    const r = robustness(cal)!;
    expect(r.holds).toBe(true);
    expect(r.summary).toContain("0.5 pts above");
    expect(r.summary).toContain("consistent with the headline");
    expect(longshotHeadline(cal)).toMatchObject({ robust: true, title: expect.stringMatching(/less often than the price says/) });
  });

  it("softens the headline when the gap disappears on midpoints", () => {
    const cal = calibration({
      overall: overpricedOverall,
      midpoint_check: check({ rate: 0.02, ci_low: 0.015, ci_high: 0.03 }, { mean_price: 0.029, rate: 0.025, ci_low: 0.019, ci_high: 0.033 }),
    });
    const r = robustness(cal)!;
    expect(r.holds).toBe(false);
    expect(r.summary).toMatch(/while across all markets they happened less often than priced/);
    expect([r.belowTrade, r.groupsTrade, r.belowMid, r.groupsMid]).toEqual([2, 2, 1, 2]);
    const h = longshotHeadline(cal);
    expect(h.robust).toBe(false);
    expect(h.title).toMatch(/about as often as the price says, if slightly less/);
  });

  it("describes a negative premium and stays silent without enough quoted markets", () => {
    const r = robustness(calibration({ midpoint_check: check({}, {}, 5000, -0.003) }))!;
    expect(r.summary).toContain("0.3 pts below");
    expect(robustness(calibration())).toBeNull();
    expect(robustness(calibration({ midpoint_check: check({}, {}, 100) }))).toBeNull();
  });
});
