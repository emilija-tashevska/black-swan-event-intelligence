import { describe, expect, it } from "vitest";
import { formatCompact, formatDate, formatDollars, formatMoney, formatPct, formatUnixDate } from "./format";

describe("format helpers", () => {
  it("formats probabilities", () => {
    expect(formatPct(0.0442)).toBe("4.4%");
    expect(formatPct(0.333, 0)).toBe("33%");
    expect(formatPct(0)).toBe("0.0%");
    expect(formatPct(null)).toBe("--");
  });

  it("formats compact counts and money", () => {
    expect(formatCompact(999)).toBe("999");
    expect(formatCompact(1_545_448)).toBe("1.5M");
    expect(formatCompact(15_199)).toBe("15.2K");
    expect(formatCompact(undefined)).toBe("--");
    expect(formatMoney(74_864.61)).toBe("$74.9K");
    expect(formatDollars(0.9)).toBe("$0.90");
  });

  it("formats dates in UTC so a midnight close doesn't shift a day", () => {
    expect(formatDate("2026-01-31T00:30:00Z")).toBe("Jan 31, 2026");
    expect(formatDate("not a date")).toBe("--");
    expect(formatDate(null)).toBe("--");
    expect(formatUnixDate(1769230800)).toBe("Jan 24, 2026");
  });
});
