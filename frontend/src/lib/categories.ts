// Kalshi's official series categories.
const CATEGORY_COLORS: Record<string, string> = {
  Crypto: "bg-orange-500/15 text-orange-300",
  Financials: "bg-blue-500/15 text-blue-300",
  Economics: "bg-sky-500/15 text-sky-300",
  Commodities: "bg-amber-500/15 text-amber-300",
  Companies: "bg-emerald-500/15 text-emerald-300",
  "Climate and Weather": "bg-cyan-500/15 text-cyan-300",
  Entertainment: "bg-purple-500/15 text-purple-300",
  Politics: "bg-red-500/15 text-red-300",
  Elections: "bg-rose-500/15 text-rose-300",
  World: "bg-indigo-500/15 text-indigo-300",
  Mentions: "bg-pink-500/15 text-pink-300",
  "Science and Technology": "bg-teal-500/15 text-teal-300",
  AI: "bg-violet-500/15 text-violet-300",
  Health: "bg-lime-500/15 text-lime-300",
};

const FALLBACK = "bg-zinc-500/15 text-zinc-300";

export function categoryClass(category: string): string {
  return CATEGORY_COLORS[category] ?? FALLBACK;
}
