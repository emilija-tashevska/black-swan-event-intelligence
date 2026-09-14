"use client";

import { useState } from "react";
import CalibrationChart from "@/components/CalibrationChart";
import type { Calibration, CalibrationGroup, Structure } from "@/lib/api";
import { categoryClass } from "@/lib/categories";
import {
  STRUCTURE_HELP,
  STRUCTURE_LABEL,
  VERDICT_CLASS,
  VERDICT_LABEL,
  findCurve,
  ratio,
  verdict,
} from "@/lib/calibration";
import { formatPct } from "@/lib/format";

interface CalibrationSectionProps {
  calibration: Calibration | null;
  error: string | null;
}

function Notice({ children, tone = "border-border" }: { children: React.ReactNode; tone?: string }) {
  return <p className={`rounded-xl border ${tone} bg-card p-8 text-center text-sm text-muted-foreground`}>{children}</p>;
}

function LongshotTable({
  title,
  groups,
  label,
}: {
  title: string;
  groups: CalibrationGroup[];
  label: (g: CalibrationGroup) => React.ReactNode;
}) {
  if (groups.length === 0) return null;
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="px-4 pt-4 text-left text-sm font-semibold">{title}</caption>
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th scope="col" className="px-4 py-3 font-medium">Group</th>
              <th scope="col" className="px-4 py-3 font-medium text-right">Longshots</th>
              <th scope="col" className="px-4 py-3 font-medium text-right">Avg price</th>
              <th scope="col" className="px-4 py-3 font-medium text-right">Happened</th>
              <th scope="col" className="px-4 py-3 font-medium">Verdict</th>
              <th scope="col" className="px-4 py-3 font-medium text-right">Brier</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const ls = g.longshots;
              const v = verdict(ls);
              return (
                <tr key={`${g.category}-${g.structure}`} className="border-b border-border/50">
                  <td className="px-4 py-3">{label(g)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {ls.n.toLocaleString()}
                    <span className="block text-xs text-muted-foreground">{ls.events.toLocaleString()} events</span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatPct(ls.mean_price)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {formatPct(ls.rate)}
                    {ls.ci_low != null && (
                      <span className="block text-xs text-muted-foreground">
                        {formatPct(ls.ci_low)}–{formatPct(ls.ci_high)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs whitespace-nowrap ${VERDICT_CLASS[v]}`}>{VERDICT_LABEL[v]}</span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">{g.brier?.toFixed(3) ?? "--"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function CalibrationSection({ calibration, error }: CalibrationSectionProps) {
  const [category, setCategory] = useState<string | null>(null);
  const [structure, setStructure] = useState<Structure | null>(null);
  const [zoom, setZoom] = useState(true);

  if (error) return <Notice tone="border-accent/30">Couldn&apos;t load calibration: {error}</Notice>;
  if (!calibration) return <Notice>Loading calibration…</Notice>;
  const { overall, categories, structures } = calibration;
  if (overall.n === 0) return <Notice>No scored markets yet.</Notice>;

  const curve = findCurve(calibration, category, structure);
  const ls = overall.longshots;
  const lsVerdict = verdict(ls);
  const lsRatio = ratio(ls);
  const structureOptions = structures.map((s) => s.structure).filter((s): s is Structure => !!s);

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">
          Longshots, all markets
        </p>
        {ls.n > 0 && ls.rate != null && ls.mean_price != null ? (
          <p className="text-lg leading-relaxed">
            Markets priced under {formatPct(calibration.longshot_max_price, 0)} a week out averaged{" "}
            <span className="font-semibold tabular-nums">{formatPct(ls.mean_price)}</span>, and{" "}
            <span className="font-semibold tabular-nums text-accent">{formatPct(ls.rate)}</span> actually happened
            <span className="text-muted-foreground text-sm">
              {" "}({ls.yes.toLocaleString()} of {ls.n.toLocaleString()} markets across {ls.events.toLocaleString()} events,
              95% range {formatPct(ls.ci_low)}–{formatPct(ls.ci_high)})
            </span>
            .{" "}
            {lsVerdict === "overpriced" && lsRatio != null && (
              <>Longshots came true about <strong>{lsRatio.toFixed(1)}×</strong> as often as priced, so buyers overpaid.</>
            )}
            {lsVerdict === "underpriced" && lsRatio != null && (
              <>Longshots came true about <strong>{lsRatio.toFixed(1)}×</strong> as often as priced, so the crowd underrated surprises.</>
            )}
            {lsVerdict === "in_line" && <>That&apos;s in line with the prices.</>}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">No longshots scored yet.</p>
        )}
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div className="max-w-xl">
            <h3 className="font-semibold">Calibration curve</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Dots on the dashed line mean prices matched reality; below it, things happened less often than priced.
              Bars are 95% ranges, widened because markets in the same event move together. Bigger dots have more markets.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="cal-category" className="sr-only">Category</label>
            <select
              id="cal-category"
              value={category ?? ""}
              onChange={(e) => setCategory(e.target.value || null)}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            >
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c.category} value={c.category ?? ""}>
                  {c.category} ({c.n.toLocaleString()})
                </option>
              ))}
            </select>
            <label htmlFor="cal-structure" className="sr-only">Market type</label>
            <select
              id="cal-structure"
              value={structure ?? ""}
              onChange={(e) => setStructure((e.target.value || null) as Structure | null)}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            >
              <option value="">All market types</option>
              {structureOptions.map((s) => (
                <option key={s} value={s}>{STRUCTURE_LABEL[s]}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setZoom(!zoom)}
              aria-pressed={zoom}
              className="rounded-md border border-border px-2 py-1 text-sm text-muted-foreground hover:text-foreground"
            >
              {zoom ? "Show full range" : "Zoom to longshots"}
            </button>
          </div>
        </div>
        {structure && <p className="mb-3 text-xs text-muted-foreground">{STRUCTURE_HELP[structure]}</p>}
        {curve ? (
          <>
            <p className="mb-2 text-xs text-muted-foreground tabular-nums">
              {curve.n.toLocaleString()} markets from {curve.events.toLocaleString()} events
            </p>
            <CalibrationChart buckets={curve.buckets} maxPrice={zoom ? 0.3 : 1} />
          </>
        ) : (
          <p className="py-12 text-center text-sm text-muted-foreground">
            Fewer than {calibration.min_group_markets} scored markets for this combination. Try a broader filter.
          </p>
        )}
      </div>

      <LongshotTable
        title="Longshots by market type"
        groups={structures}
        label={(g) => (
          <span title={g.structure ? STRUCTURE_HELP[g.structure] : undefined} className="whitespace-nowrap">
            {g.structure ? STRUCTURE_LABEL[g.structure] : "--"}
          </span>
        )}
      />
      <LongshotTable
        title="Longshots by category"
        groups={categories}
        label={(g) => (
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${categoryClass(g.category ?? "")}`}>{g.category}</span>
        )}
      />
      <p className="text-xs text-muted-foreground">
        Groups need {calibration.min_group_markets}+ scored markets. Verdicts need 30+ longshots from 10+ events and a 95%
        range that excludes the average price. Brier score measures accuracy across all prices; lower is better.
      </p>
    </div>
  );
}
