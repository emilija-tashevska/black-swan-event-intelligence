"use client";

import { useState } from "react";
import type { Structure } from "@/lib/api";
import { STRUCTURE_LABEL, linearScale } from "@/lib/calibration";
import { formatPct } from "@/lib/format";
import type { GapRow, GapStatus, StructureFinding } from "@/lib/story";

// Diverging encoding, validated against the dark card surface (#18181b):
// rose = happened more than priced, blue = less, gray hollow = in line.
export const STATUS_COLOR: Record<GapStatus, string> = {
  more: "#f43f5e",
  less: "#3b82f6",
  in_line: "#71717a",
};

export function StatusLegend() {
  const item = (status: GapStatus, label: string) => (
    <span className="inline-flex items-center gap-1.5">
      <svg width="12" height="12" aria-hidden="true">
        <circle
          cx="6" cy="6" r="4.5"
          fill={status === "in_line" ? "none" : STATUS_COLOR[status]}
          stroke={STATUS_COLOR[status]} strokeWidth="2"
        />
      </svg>
      {label}
    </span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {item("less", "Happened less often than priced")}
      {item("in_line", "In line (range includes the price)")}
      {item("more", "Happened more often than priced")}
    </div>
  );
}

function Marker({ cx, cy, status, r = 5 }: { cx: number; cy: number; status: GapStatus; r?: number }) {
  return (
    <circle
      cx={cx} cy={cy} r={r}
      fill={status === "in_line" ? "#18181b" : STATUS_COLOR[status]}
      stroke={STATUS_COLOR[status]} strokeWidth={2}
    />
  );
}

function Tooltip({ text }: { text: string | null }) {
  return (
    <p className="min-h-[1.25rem] text-xs text-muted-foreground tabular-nums" aria-live="polite">
      {text ?? "Hover or focus a point for details."}
    </p>
  );
}

/** Happened − priced for each price bucket, with the event-adjusted 95% range. */
export function GapChart({ rows }: { rows: GapRow[] }) {
  const [active, setActive] = useState<number | null>(null);
  const W = 720;
  const H = 300;
  const M = { top: 12, right: 12, bottom: 52, left: 52 };
  const extent = Math.max(0.05, ...rows.flatMap((r) => [Math.abs(r.gapLow), Math.abs(r.gapHigh)]));
  const yLim = Math.ceil(extent * 50) / 50; // round up to 2-point steps
  const y = linearScale([-yLim, yLim], [H - M.bottom, M.top]);
  const step = (W - M.left - M.right) / Math.max(rows.length, 1);
  const x = (i: number) => M.left + step * (i + 0.5);
  const ticks = Array.from({ length: Math.round((2 * yLim) / 0.02) + 1 }, (_, i) => -yLim + i * 0.02);
  const describe = (r: GapRow) =>
    `Priced ${r.label}%: averaged ${formatPct(r.priced)}, happened ${formatPct(r.happened)} ` +
    `(95% range ${formatPct(r.priced + r.gapLow)}–${formatPct(r.priced + r.gapHigh)}) · ` +
    `${r.n.toLocaleString()} markets from ${r.events.toLocaleString()} events`;

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Gap between how often events happened and their price, by price bucket">
        {ticks.map((t) => (
          <g key={t.toFixed(2)}>
            <line
              x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)}
              className={Math.abs(t) < 1e-9 ? "stroke-muted-foreground" : "stroke-border"}
              strokeWidth={Math.abs(t) < 1e-9 ? 1.25 : 1}
            />
            <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px]">
              {t > 1e-9 ? "+" : ""}{Math.round(t * 100)}
            </text>
          </g>
        ))}
        <text transform={`translate(14 ${(M.top + H - M.bottom) / 2}) rotate(-90)`} textAnchor="middle" className="fill-muted-foreground text-[11px]">
          Happened − priced (pts)
        </text>
        <text x={(M.left + W - M.right) / 2} y={H - 6} textAnchor="middle" className="fill-muted-foreground text-[11px]">
          Price a week before close (%)
        </text>
        {rows.map((r, i) => (
          <g
            key={r.label}
            tabIndex={0}
            role="button"
            aria-label={describe(r)}
            onMouseEnter={() => setActive(i)}
            onFocus={() => setActive(i)}
            onMouseLeave={() => setActive(null)}
            onBlur={() => setActive(null)}
            className="cursor-default outline-none"
          >
            <rect x={x(i) - step / 2} y={M.top} width={step} height={H - M.top - M.bottom} fill={active === i ? "rgba(255,255,255,0.04)" : "transparent"} />
            <line
              x1={x(i)} x2={x(i)} y1={y(Math.max(r.gapLow, -yLim))} y2={y(Math.min(r.gapHigh, yLim))}
              stroke={STATUS_COLOR[r.status]} strokeOpacity={0.5} strokeWidth={3} strokeLinecap="round"
            />
            <Marker cx={x(i)} cy={y(r.gap)} status={r.status} />
            <text
              x={x(i)} y={H - M.bottom + 14} textAnchor="end"
              transform={`rotate(-40 ${x(i)} ${H - M.bottom + 14})`}
              className="fill-muted-foreground text-[10px]"
            >
              {r.label}
            </text>
          </g>
        ))}
      </svg>
      <Tooltip text={active == null ? null : describe(rows[active])} />
    </div>
  );
}

/** For each market type: the average longshot price (tick) against how often
 *  those longshots happened (dot + range). */
export function StructureLongshotChart({ findings }: { findings: StructureFinding[] }) {
  const [active, setActive] = useState<Structure | null>(null);
  const rows = findings.filter((f) => f.longshots.n > 0 && f.longshots.mean_price != null && f.longshots.rate != null);
  const W = 720;
  const rowH = 44;
  const M = { top: 8, right: 24, bottom: 34, left: 170 };
  const H = M.top + rows.length * rowH + M.bottom;
  // Scale to the estimates, not the widest range, so a small, uncertain group
  // doesn't squash the others; ranges beyond the axis are clipped and labelled.
  const estimates = rows.flatMap((f) => [f.longshots.mean_price ?? 0, f.longshots.rate ?? 0]);
  const xMax = Math.min(1, Math.ceil(Math.max(0.04, ...estimates) * 2 * 50) / 50);
  const x = linearScale([0, xMax], [M.left, W - M.right]);
  const ticks = Array.from({ length: Math.round(xMax / 0.02) + 1 }, (_, i) => i * 0.02);
  const statusOf = (f: StructureFinding): GapStatus =>
    f.verdict === "overpriced" ? "less" : f.verdict === "underpriced" ? "more" : "in_line";
  const describe = (f: StructureFinding) => {
    const ls = f.longshots;
    return `${STRUCTURE_LABEL[f.structure]}: ${ls.n.toLocaleString()} longshots from ${ls.events.toLocaleString()} events, ` +
      `priced ${formatPct(ls.mean_price)}, happened ${formatPct(ls.rate)} (95% range ${formatPct(ls.ci_low)}–${formatPct(ls.ci_high)})`;
  };
  const current = rows.find((f) => f.structure === active);

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Longshot price versus how often longshots happened, by market type">
        {ticks.map((t) => (
          <g key={t.toFixed(2)}>
            <line x1={x(t)} x2={x(t)} y1={M.top} y2={H - M.bottom} className="stroke-border" />
            <text x={x(t)} y={H - M.bottom + 16} textAnchor="middle" className="fill-muted-foreground text-[11px]">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {rows.map((f, i) => {
          const cy = M.top + rowH * (i + 0.5);
          const ls = f.longshots;
          const status = statusOf(f);
          return (
            <g
              key={f.structure}
              tabIndex={0}
              role="button"
              aria-label={describe(f)}
              onMouseEnter={() => setActive(f.structure)}
              onFocus={() => setActive(f.structure)}
              onMouseLeave={() => setActive(null)}
              onBlur={() => setActive(null)}
              className="outline-none"
            >
              <rect x={0} y={cy - rowH / 2} width={W} height={rowH} fill={active === f.structure ? "rgba(255,255,255,0.04)" : "transparent"} />
              <text x={M.left - 12} y={cy} dy="-0.15em" textAnchor="end" className="fill-foreground text-[13px]">
                {STRUCTURE_LABEL[f.structure]}
              </text>
              <text x={M.left - 12} y={cy} dy="1.1em" textAnchor="end" className="fill-muted-foreground text-[11px]">
                {ls.n.toLocaleString()} markets · {ls.events.toLocaleString()} events
              </text>
              <line
                x1={x(ls.ci_low ?? 0)} x2={x(Math.min(ls.ci_high ?? 0, xMax))} y1={cy} y2={cy}
                stroke={STATUS_COLOR[status]} strokeOpacity={0.5} strokeWidth={4} strokeLinecap="round"
              />
              {(ls.ci_high ?? 0) > xMax && (
                <text x={x(xMax) - 4} y={cy} dy="-0.6em" textAnchor="end" className="fill-muted-foreground text-[11px]">
                  range to {formatPct(ls.ci_high)} →
                </text>
              )}
              <line x1={x(ls.mean_price!)} x2={x(ls.mean_price!)} y1={cy - 10} y2={cy + 10} className="stroke-foreground" strokeWidth={2} />
              <Marker cx={x(ls.rate!)} cy={cy} status={status} r={6} />
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <svg width="4" height="14" aria-hidden="true"><line x1="2" x2="2" y1="0" y2="14" className="stroke-foreground" strokeWidth="2" /></svg>
          Average price
        </span>
        <span>Dot: how often they happened · bar: 95% range</span>
      </div>
      <Tooltip text={current ? describe(current) : null} />
    </div>
  );
}
