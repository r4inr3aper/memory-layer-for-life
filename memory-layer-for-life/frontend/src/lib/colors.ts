const SERIES = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

export function seriesColor(index: number): string {
  return SERIES[index % SERIES.length];
}

/** One colour per model family, so a model looks the same on every screen. */
export function modelColor(model: string | null | undefined): string {
  if (!model) return "var(--muted-foreground)";
  if (model.includes("sonnet")) return "var(--chart-1)";
  if (model.includes("haiku")) return "var(--chart-2)";
  if (model.includes("opus")) return "var(--chart-3)";
  return "var(--chart-4)";
}
