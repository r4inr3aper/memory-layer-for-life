import type { ReactNode } from "react";

import { seriesColor } from "@/lib/colors";

export interface BarItem {
  key: string;
  label: ReactNode;
  value: number;
  hint?: ReactNode;
  color?: string;
}

/** Horizontal bars, one per row. Dense, exact, and readable without a legend. */
export function BarList({
  items,
  format,
  max,
}: {
  items: BarItem[];
  format: (value: number) => string;
  max?: number;
}) {
  const top = max ?? Math.max(0, ...items.map((item) => item.value));
  if (items.length === 0) return <p className="text-sm text-muted-foreground">Nothing to show yet.</p>;
  return (
    <ul className="space-y-2.5">
      {items.map((item) => {
        const share = top > 0 ? (item.value / top) * 100 : 0;
        return (
          <li key={item.key}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">{item.label}</span>
              <span className="tabular shrink-0 text-xs text-muted-foreground">
                {item.hint && <span className="mr-2">{item.hint}</span>}
                <span className="text-sm text-foreground">{format(item.value)}</span>
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${item.value > 0 ? Math.max(share, 1.5) : 0}%`,
                  background: item.color ?? "var(--chart-1)",
                }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function Legend({ series, colors }: { series: string[]; colors?: string[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {series.map((name, index) => (
        <span key={name} className="inline-flex items-center gap-1.5">
          <span
            className="size-2 rounded-sm"
            style={{ background: colors?.[index] ?? seriesColor(index) }}
          />
          {name}
        </span>
      ))}
    </div>
  );
}

export interface ColumnDatum {
  label: string;
  values: Record<string, number>;
}

/** Stacked columns over time: one column per period, one colour per series. */
export function StackedColumns({
  data,
  series,
  colors,
  format,
  height = 132,
  label,
}: {
  data: ColumnDatum[];
  series: string[];
  colors?: string[];
  format: (value: number) => string;
  height?: number;
  label: string;
}) {
  const totals = data.map((datum) =>
    series.reduce((sum, name) => sum + (datum.values[name] ?? 0), 0),
  );
  const top = Math.max(0, ...totals);
  if (top === 0) return <p className="text-sm text-muted-foreground">Nothing to chart yet.</p>;
  return (
    <div>
      <div className="flex items-end gap-1" style={{ height }} role="img" aria-label={label}>
        {data.map((datum, index) => (
          <div
            key={datum.label}
            className="flex h-full min-w-0 max-w-12 flex-1 flex-col justify-end"
            title={`${datum.label}: ${format(totals[index])}`}
          >
            {series.map((name, position) => {
              const value = datum.values[name] ?? 0;
              if (value <= 0) return null;
              return (
                <div
                  key={name}
                  className="w-full first:rounded-t-sm"
                  style={{
                    height: `${(value / top) * 100}%`,
                    minHeight: 2,
                    background: colors?.[position] ?? seriesColor(position),
                  }}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-xs text-muted-foreground">
        <span>{data[0].label}</span>
        <span className="tabular">peak {format(top)}</span>
        {data.length > 1 && <span>{data[data.length - 1].label}</span>}
      </div>
      <Legend series={series} colors={colors} />
    </div>
  );
}
