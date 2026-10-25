/**
 * Usage Chart Helpers
 *
 * Formatting and scales for the cost chart in Settings. Periods come from the backend as
 * UTC dates ("YYYY-MM-DD"); they are labelled from their parts, never through a local
 * `Date`, so a period never shifts to the day before in timezones west of UTC.
 */

import type { UsageGranularity } from '@/lib/api/types';

const MONTHS_SHORT = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];
const MONTHS_LONG = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

const CURRENCY_SYMBOLS: Record<string, string> = { INR: '₹', USD: '$', EUR: '€', GBP: '£' };

/** "₹" for INR; the code itself, then a space, for currencies without a symbol here. */
export function currencySymbol(currency: string): string {
  return CURRENCY_SYMBOLS[currency] ?? `${currency} `;
}

/** How many periods the backend returns, for captions. */
export const PERIOD_COUNTS: Record<UsageGranularity, number> = { day: 14, week: 12, month: 12 };

export const GRANULARITY_LABELS: Record<UsageGranularity, string> = {
  day: 'Daily',
  week: 'Weekly',
  month: 'Monthly',
};

/** "Last 14 days", "Last 12 weeks", "Last 12 months". */
export function rangeCaption(granularity: UsageGranularity): string {
  return `Last ${PERIOD_COUNTS[granularity]} ${granularity}s`;
}

/** A decimal string or number from the API as a number; 0 when it is not one. */
export function toAmount(value: string | number | null | undefined): number {
  const amount = typeof value === 'number' ? value : Number(value ?? 0);
  return Number.isFinite(amount) && amount > 0 ? amount : 0;
}

/**
 * A cost for reading: two decimals from one unit up, and down to four below that, as a
 * single chat costs a fraction of a rupee or cent. "₹12.35", "₹0.18", "$0.0031".
 */
export function formatCost(value: string | number | null | undefined, currency: string): string {
  const symbol = currencySymbol(currency);
  const amount = toAmount(value);
  if (amount === 0) {
    return `${symbol}0.00`;
  }
  if (amount < 0.0001) {
    return `<${symbol}0.0001`;
  }
  const fixed = amount.toFixed(amount >= 1 ? 2 : 4);
  // Drop trailing zeros past two decimals: 0.5300 -> 0.53, 0.0310 -> 0.031.
  return `${symbol}${fixed.replace(/(\.\d\d\d*?)0+$/, '$1')}`;
}

/**
 * Clean y-axis ticks from 0 to at least `max`: steps of 1, 2, or 5 times a power of ten,
 * three to five ticks. With nothing to show, 0 to a cent.
 */
export function niceTicks(max: number): { ticks: number[]; top: number; step: number } {
  if (!(max > 0)) {
    return { ticks: [0, 0.01], top: 0.01, step: 0.01 };
  }
  const rough = max / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((factor) => factor * power).find((s) => s >= rough) ?? 10 * power;
  const count = Math.ceil(max / step - 1e-9);
  const ticks = Array.from({ length: count + 1 }, (_, index) => roundTo(index * step, step));
  return { ticks, top: ticks[ticks.length - 1], step };
}

/** A tick label with the decimals its step needs, two at least below one unit:
 * "₹0", "₹0.20", "₹0.005", "₹2". */
export function formatTick(value: number, step: number, currency: string): string {
  const symbol = currencySymbol(currency);
  if (value === 0) {
    return `${symbol}0`;
  }
  const needed = -Math.floor(Math.log10(step));
  const decimals = Math.min(4, Math.max(needed, step < 1 ? 2 : 0));
  return `${symbol}${value.toFixed(decimals)}`;
}

/**
 * A period's label. Short for the axis ("Oct 1", "Sep 28", "Oct"), long for the readout
 * ("Oct 1", "Week of Sep 28", "October 2026").
 */
export function periodLabel(
  start: string,
  granularity: UsageGranularity,
  length: 'short' | 'long'
): string {
  const [year, month, day] = start.split('-').map(Number);
  if (!year || !month || !day) {
    return start;
  }
  const monthShort = MONTHS_SHORT[month - 1];
  if (granularity === 'month') {
    return length === 'short' ? monthShort : `${MONTHS_LONG[month - 1]} ${year}`;
  }
  const dayLabel = `${monthShort} ${day}`;
  return granularity === 'week' && length === 'long' ? `Week of ${dayLabel}` : dayLabel;
}

/** Which periods get an axis label: the first, the middle, and the last. */
export function axisLabelIndexes(count: number): number[] {
  if (count <= 0) {
    return [];
  }
  return [...new Set([0, Math.floor((count - 1) / 2), count - 1])];
}

/**
 * A column with a 4px rounded top and a square base, as an SVG path. The radius shrinks
 * for columns shorter or narrower than it.
 */
export function columnPath(x: number, top: number, width: number, bottom: number): string {
  const height = bottom - top;
  if (height <= 0 || width <= 0) {
    return '';
  }
  const radius = Math.min(4, height, width / 2);
  return [
    `M${x},${bottom}`,
    `L${x},${top + radius}`,
    `Q${x},${top} ${x + radius},${top}`,
    `L${x + width - radius},${top}`,
    `Q${x + width},${top} ${x + width},${top + radius}`,
    `L${x + width},${bottom}`,
    'Z',
  ].join(' ');
}

function roundTo(value: number, step: number): number {
  const decimals = Math.max(0, -Math.floor(Math.log10(step)) + 1);
  return Number(value.toFixed(decimals));
}
