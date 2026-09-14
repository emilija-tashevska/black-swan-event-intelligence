"use client";

import type { CalibrationBucket } from "@/lib/api";
import { linearScale } from "@/lib/calibration";
import { formatPct } from "@/lib/format";

interface CalibrationChartProps {
  buckets: CalibrationBucket[];
  maxPrice: number; // 1 for the full range, e.g. 0.3 to zoom into longshots
}

const W = 560;
const H = 380;
const M = { top: 16, right: 16, bottom: 48, left: 56 };

export default function CalibrationChart({ buckets, maxPrice }: CalibrationChartProps) {
  const visible = buckets.filter((b) => b.mean_price <= maxPrice);
  const yMax = Math.min(1, Math.max(maxPrice, ...visible.map((b) => b.ci_high)) * 1.05);
  const x = linearScale([0, maxPrice], [M.left, W - M.right]);
  const y = linearScale([0, yMax], [H - M.bottom, M.top]);
  const maxN = Math.max(1, ...visible.map((b) => b.n));
  const radius = (n: number) => 3 + 6 * Math.sqrt(n / maxN);
  const ticks = maxPrice <= 0.3 ? [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3] : [0, 0.25, 0.5, 0.75, 1];
  const yStep = yMax > 0.5 ? 0.25 : yMax > 0.3 ? 0.1 : 0.05;
  const yTicks = Array.from({ length: Math.floor(yMax / yStep + 1e-9) + 1 }, (_, i) => i * yStep);
  const diagEnd = Math.min(maxPrice, yMax);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="mx-auto h-auto w-full max-w-2xl"
      role="img"
      aria-label="Calibration chart: market price a week before close against the share of markets that resolved YES"
    >
      {yTicks.map((t) => (
        <g key={`y${t}`}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className="stroke-border" strokeWidth={1} />
          <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px]">
            {formatPct(t, 0)}
          </text>
        </g>
      ))}
      {ticks.map((t) => (
        <text key={`x${t}`} x={x(t)} y={H - M.bottom + 18} textAnchor="middle" className="fill-muted-foreground text-[11px]">
          {formatPct(t, 0)}
        </text>
      ))}
      <text x={(M.left + W - M.right) / 2} y={H - 8} textAnchor="middle" className="fill-muted-foreground text-[12px]">
        Market price 7 days before close
      </text>
      <text
        transform={`translate(14 ${(M.top + H - M.bottom) / 2}) rotate(-90)`}
        textAnchor="middle"
        className="fill-muted-foreground text-[12px]"
      >
        Share that resolved YES
      </text>

      <line
        x1={x(0)} y1={y(0)} x2={x(diagEnd)} y2={y(diagEnd)}
        className="stroke-muted-foreground" strokeDasharray="5 5" strokeWidth={1.25}
      />
      <text x={x(diagEnd)} y={y(diagEnd)} dx={-6} dy={-6} textAnchor="end" className="fill-muted-foreground text-[11px]">
        perfectly calibrated
      </text>

      {visible.map((b) => (
        <g key={b.lo}>
          <title>
            {`Priced ${formatPct(b.lo, 0)}–${formatPct(b.hi, 0)} (avg ${formatPct(b.mean_price)}): ` +
              `${b.yes.toLocaleString()} of ${b.n.toLocaleString()} happened = ${formatPct(b.rate)} ` +
              `(95% range ${formatPct(b.ci_low)}–${formatPct(b.ci_high)})`}
          </title>
          <line
            x1={x(b.mean_price)} x2={x(b.mean_price)} y1={y(b.ci_low)} y2={y(Math.min(b.ci_high, yMax))}
            className="stroke-accent/60" strokeWidth={2}
          />
          <circle cx={x(b.mean_price)} cy={y(b.rate)} r={radius(b.n)} className="fill-accent stroke-background" strokeWidth={1.5} />
        </g>
      ))}
    </svg>
  );
}
