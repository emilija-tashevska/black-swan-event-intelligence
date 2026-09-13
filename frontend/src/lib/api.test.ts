import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BlackSwan, applyQuery, nearestThreshold } from "./api";

function swan(ticker: string, overrides: Partial<BlackSwan> = {}): BlackSwan {
  return {
    ticker,
    event_ticker: ticker,
    series_ticker: "KX",
    category: "Crypto",
    title: ticker,
    yes_sub_title: "",
    rules_primary: "",
    open_time: null,
    close_time: "2026-05-01T00:00:00Z",
    settlement_ts: null,
    last_price: 0.99,
    volume: 1000,
    open_interest: 0,
    prediction_price: 0.05,
    prediction_source: "trade",
    prediction_ts: null,
    prediction_volume: null,
    volume_at_price: null,
    ai_summary: "",
    ...overrides,
  };
}

describe("nearestThreshold", () => {
  it.each([
    [0.01, 0.05],
    [0.07, 0.05],
    [0.08, 0.1],
    [0.1, 0.1],
    [0.9, 0.25],
  ])("%s -> %s", (input, expected) => {
    expect(nearestThreshold(input)).toBe(expected);
  });
});

describe("applyQuery", () => {
  const items = [
    swan("A", { volume: 300, prediction_price: 0.08, volume_at_price: 5, category: "Politics" }),
    swan("B", { volume: 100, prediction_price: 0.02 }),
    swan("C", { volume: 200, prediction_price: 0.05, volume_at_price: 50 }),
  ];
  const tickers = (rows: BlackSwan[]) => rows.map((r) => r.ticker);

  it("sorts numbers in both directions", () => {
    expect(tickers(applyQuery(items, { sort: "volume", order: "desc", category: null }))).toEqual(["A", "C", "B"]);
    expect(tickers(applyQuery(items, { sort: "prediction_price", order: "asc", category: null }))).toEqual(["B", "C", "A"]);
  });

  it("keeps missing values last regardless of direction", () => {
    for (const order of ["asc", "desc"] as const) {
      const rows = applyQuery(items, { sort: "volume_at_price", order, category: null });
      expect(rows.at(-1)?.ticker).toBe("B");
    }
  });

  it("sorts ISO dates chronologically", () => {
    const dated = [
      swan("late", { close_time: "2026-08-01T00:00:00Z" }),
      swan("early", { close_time: "2026-03-01T00:00:00Z" }),
    ];
    expect(tickers(applyQuery(dated, { sort: "close_time", order: "asc", category: null }))).toEqual(["early", "late"]);
  });

  it("filters by category without mutating the input", () => {
    const before = tickers(items);
    expect(tickers(applyQuery(items, { sort: "volume", order: "desc", category: "Crypto" }))).toEqual(["C", "B"]);
    expect(tickers(items)).toEqual(before);
  });
});

describe("static mode fetching", () => {
  // IS_STATIC is read at import time, so each test needs a fresh module.
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("loads the nearest pre-computed threshold file and applies the query locally", async () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC", "true");
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/repo");
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ black_swans: [swan("X", { volume: 1 }), swan("Y", { volume: 9 })] })),
    );
    vi.stubGlobal("fetch", fetchMock);

    const api = await import("./api");
    const rows = await api.fetchBlackSwans({ threshold: 0.12, sort: "volume", order: "desc", category: null });

    expect(fetchMock).toHaveBeenCalledWith("/repo/data/black-swans-10.json");
    expect(rows.map((r) => r.ticker)).toEqual(["Y", "X"]);
  });

  it("surfaces HTTP errors instead of silently falling back", async () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC", "true");
    const fetchMock = vi.fn(async () => new Response("nope", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    const api = await import("./api");
    expect(api.IS_STATIC).toBe(true);
    await expect(api.fetchStats(0.1)).rejects.toThrow("404");
    expect(fetchMock).toHaveBeenCalledWith("/data/stats-10.json");
    expect(await api.fetchMeta()).toBeNull();
  });
});
