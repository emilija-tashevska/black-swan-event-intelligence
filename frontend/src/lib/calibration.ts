import type { Calibration, CalibrationCurve, GroupStats, Structure } from "./api";

export type Verdict = "underpriced" | "overpriced" | "in_line" | "too_few";

/** Compare what happened with what was priced, using the 95% interval so
 *  noise in small groups isn't reported as a finding. */
export function verdict(group: GroupStats, minN = 30, minEvents = 10): Verdict {
  if (
    group.n < minN ||
    group.events < minEvents ||
    group.mean_price == null ||
    group.ci_low == null ||
    group.ci_high == null
  ) {
    return "too_few";
  }
  if (group.ci_low > group.mean_price) return "underpriced";
  if (group.ci_high < group.mean_price) return "overpriced";
  return "in_line";
}

export const VERDICT_LABEL: Record<Verdict, string> = {
  underpriced: "Happened more than priced",
  overpriced: "Happened less than priced",
  in_line: "In line with price",
  too_few: "Too few markets",
};

export const VERDICT_CLASS: Record<Verdict, string> = {
  underpriced: "bg-accent/15 text-accent",
  overpriced: "bg-blue-500/15 text-blue-300",
  in_line: "bg-emerald-500/15 text-emerald-300",
  too_few: "bg-zinc-500/15 text-zinc-400",
};

/** "Happened X times as often as priced", rounded for display. */
export function ratio(group: GroupStats): number | null {
  if (group.rate == null || !group.mean_price) return null;
  return group.rate / group.mean_price;
}

export function linearScale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  return (v: number) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
}

export function daysUntil(iso: string | null, now: Date = new Date()): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return (t - now.getTime()) / 86_400_000;
}

export const STRUCTURE_LABEL: Record<Structure, string> = {
  standalone: "Standalone yes/no",
  pick_one: "Pick one of many",
  ladder: "Threshold ladder",
  bundle: "Bundle",
  unknown: "Unclassified",
};

export const STRUCTURE_HELP: Record<Structure, string> = {
  standalone: "A single market on its own, e.g. “Will Trump apologize before 2027?”",
  pick_one: "Exactly one outcome wins, e.g. award nominees or price ranges. Most low-priced markets here are the also-rans.",
  ladder: "Nested thresholds on one number, e.g. CPI above 4.4% / 4.5% / 4.6%. Rungs resolve together.",
  bundle: "Several separate markets on one occasion, e.g. words said in a speech.",
  unknown: "Event not classified yet.",
};

/** The curve for a category and/or structure filter, or null if that
 *  combination doesn't have enough markets for its own curve. */
export function findCurve(
  calibration: Calibration,
  category: string | null,
  structure: Structure | null,
): CalibrationCurve | null {
  if (!category && !structure) return calibration.overall;
  const pool = category && structure ? calibration.segments : category ? calibration.categories : calibration.structures;
  return pool.find((g) => g.category === category && g.structure === structure) ?? null;
}
