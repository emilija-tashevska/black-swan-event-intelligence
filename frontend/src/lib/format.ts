export function formatPct(price: number | null | undefined, digits = 1): string {
  if (price == null) return "--";
  return `${(price * 100).toFixed(digits)}%`;
}

export function formatDollars(amount: number | null | undefined): string {
  if (amount == null) return "--";
  return `$${amount.toFixed(2)}`;
}

export function formatCompact(value: number | null | undefined): string {
  if (value == null) return "--";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatMoney(amount: number | null | undefined): string {
  if (amount == null) return "--";
  return `$${formatCompact(amount)}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatUnixDate(ts: number | null | undefined): string {
  return ts == null ? "--" : formatDate(new Date(ts * 1000).toISOString());
}
