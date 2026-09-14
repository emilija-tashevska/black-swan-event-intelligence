import { describe, expect, it } from "vitest";
import type { Calibration, CalibrationCurve, GroupStats } from "./api";
import { daysUntil, findCurve, linearScale, ratio, verdict } from "./calibration";

function group(overrides: Partial<GroupStats>): GroupStats {
  return {
    n: 500, events: 200, yes: 25, mean_price: 0.05, rate: 0.05,
    ci_low: 0.033, ci_high: 0.073, n_effective: 480, ...overrides,
  };
}

describe("verdict", () => {
  it("is in line when the price falls inside the 95% range", () => {
    expect(verdict(group({}))).toBe("in_line");
  });

  it("flags overpriced longshots when even the top of the range is below the price", () => {
    expect(verdict(group({ rate: 0.02, ci_low: 0.011, ci_high: 0.036 }))).toBe("overpriced");
  });

  it("flags underpriced longshots when even the bottom of the range is above the price", () => {
    expect(verdict(group({ rate: 0.12, ci_low: 0.095, ci_high: 0.15 }))).toBe("underpriced");
  });

  it("refuses to judge small or empty groups", () => {
    expect(verdict(group({ n: 29, rate: 0.5, ci_low: 0.3, ci_high: 0.7 }))).toBe("too_few");
    // Plenty of markets but from too few events (e.g. one big ladder)
    expect(verdict(group({ n: 300, events: 9, rate: 0.2, ci_low: 0.15, ci_high: 0.25 }))).toBe("too_few");
    expect(verdict(group({ n: 0, mean_price: null, rate: null, ci_low: null, ci_high: null }))).toBe("too_few");
  });
});

describe("ratio", () => {
  it("compares outcome rate with average price", () => {
    expect(ratio(group({ rate: 0.1, mean_price: 0.05 }))).toBeCloseTo(2);
    expect(ratio(group({ mean_price: 0 }))).toBeNull();
    expect(ratio(group({ rate: null }))).toBeNull();
  });
});

describe("linearScale", () => {
  it("maps domain to range, including inverted ranges for SVG y axes", () => {
    const x = linearScale([0, 0.3], [50, 350]);
    expect(x(0)).toBe(50);
    expect(x(0.15)).toBeCloseTo(200);
    const y = linearScale([0, 1], [300, 20]);
    expect(y(1)).toBe(20);
  });
});

describe("daysUntil", () => {
  it("returns fractional days and handles bad input", () => {
    const now = new Date("2026-09-13T00:00:00Z");
    expect(daysUntil("2026-09-20T12:00:00Z", now)).toBeCloseTo(7.5);
    expect(daysUntil(null, now)).toBeNull();
    expect(daysUntil("nope", now)).toBeNull();
  });
});

describe("findCurve", () => {
  const curve = (n: number): CalibrationCurve => ({ n, events: n, brier: 0.1, longshots: group({}), buckets: [] });
  const cal: Calibration = {
    bucket_edges: [], longshot_max_price: 0.1, min_group_markets: 100,
    overall: curve(1000),
    categories: [{ ...curve(400), category: "Politics", structure: null }],
    structures: [{ ...curve(300), category: null, structure: "ladder" }],
    segments: [{ ...curve(150), category: "Politics", structure: "ladder" }],
  };

  it("picks overall, category, structure or the combined segment", () => {
    expect(findCurve(cal, null, null)?.n).toBe(1000);
    expect(findCurve(cal, "Politics", null)?.n).toBe(400);
    expect(findCurve(cal, null, "ladder")?.n).toBe(300);
    expect(findCurve(cal, "Politics", "ladder")?.n).toBe(150);
  });

  it("returns null for combinations without enough markets", () => {
    expect(findCurve(cal, "Politics", "pick_one")).toBeNull();
    expect(findCurve(cal, "Crypto", null)).toBeNull();
  });
});
