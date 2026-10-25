import {
  axisLabelIndexes,
  columnPath,
  formatCost,
  formatTick,
  niceTicks,
  periodLabel,
  rangeCaption,
  toAmount,
} from '@/lib/usageChart';

describe('formatCost', () => {
  it('shows two decimals from one unit up, and down to four below', () => {
    expect(formatCost('12.345', 'INR')).toBe('₹12.35');
    expect(formatCost('2.6', 'INR')).toBe('₹2.60');
    expect(formatCost('0.53', 'INR')).toBe('₹0.53');
    expect(formatCost('0.176', 'INR')).toBe('₹0.176');
    expect(formatCost('0.0031', 'USD')).toBe('$0.0031');
  });

  it('handles zero, tiny, and missing amounts', () => {
    expect(formatCost('0', 'INR')).toBe('₹0.00');
    expect(formatCost(null, 'INR')).toBe('₹0.00');
    expect(formatCost('not a number', 'INR')).toBe('₹0.00');
    expect(formatCost('0.00004', 'INR')).toBe('<₹0.0001');
  });

  it('falls back to the currency code without a known symbol', () => {
    expect(formatCost('5', 'JPY')).toBe('JPY 5.00');
  });
});

describe('toAmount', () => {
  it('reads decimal strings and never goes negative', () => {
    expect(toAmount('0.25')).toBe(0.25);
    expect(toAmount(3)).toBe(3);
    expect(toAmount('-1')).toBe(0);
    expect(toAmount(undefined)).toBe(0);
  });
});

describe('niceTicks', () => {
  it('steps by 1, 2, or 5 times a power of ten and reaches the maximum', () => {
    expect(niceTicks(0.53)).toEqual({ ticks: [0, 0.2, 0.4, 0.6], top: 0.6, step: 0.2 });
    expect(niceTicks(0.03)).toEqual({ ticks: [0, 0.01, 0.02, 0.03], top: 0.03, step: 0.01 });
    expect(niceTicks(1.53)).toEqual({ ticks: [0, 0.5, 1, 1.5, 2], top: 2, step: 0.5 });
  });

  it('gives an empty chart a one-cent scale', () => {
    expect(niceTicks(0)).toEqual({ ticks: [0, 0.01], top: 0.01, step: 0.01 });
  });
});

describe('formatTick', () => {
  it('uses the decimals the step needs, with cents below a dollar', () => {
    expect(formatTick(0, 0.2, 'INR')).toBe('₹0');
    expect(formatTick(0.4, 0.2, 'INR')).toBe('₹0.40');
    expect(formatTick(0.015, 0.005, 'INR')).toBe('₹0.015');
    expect(formatTick(4, 2, 'USD')).toBe('$4');
  });
});

describe('periodLabel', () => {
  it('labels days, weeks, and months from the UTC date parts', () => {
    expect(periodLabel('2026-10-01', 'day', 'short')).toBe('Oct 1');
    expect(periodLabel('2026-10-01', 'day', 'long')).toBe('Oct 1');
    expect(periodLabel('2026-09-28', 'week', 'short')).toBe('Sep 28');
    expect(periodLabel('2026-09-28', 'week', 'long')).toBe('Week of Sep 28');
    expect(periodLabel('2026-10-01', 'month', 'short')).toBe('Oct');
    expect(periodLabel('2026-10-01', 'month', 'long')).toBe('October 2026');
  });

  it('returns anything it cannot read unchanged', () => {
    expect(periodLabel('soon', 'day', 'short')).toBe('soon');
  });
});

describe('axisLabelIndexes', () => {
  it('labels the first, middle, and last periods only', () => {
    expect(axisLabelIndexes(14)).toEqual([0, 6, 13]);
    expect(axisLabelIndexes(12)).toEqual([0, 5, 11]);
    expect(axisLabelIndexes(2)).toEqual([0, 1]);
    expect(axisLabelIndexes(0)).toEqual([]);
  });
});

describe('rangeCaption', () => {
  it('names the range the backend returns', () => {
    expect(rangeCaption('day')).toBe('Last 14 days');
    expect(rangeCaption('week')).toBe('Last 12 weeks');
    expect(rangeCaption('month')).toBe('Last 12 months');
  });
});

describe('columnPath', () => {
  it('rounds the top corners by 4 and keeps the base square', () => {
    expect(columnPath(10, 20, 12, 100)).toBe(
      'M10,100 L10,24 Q10,20 14,20 L18,20 Q22,20 22,24 L22,100 Z'
    );
  });

  it('shrinks the radius for short columns and draws nothing for empty ones', () => {
    expect(columnPath(0, 98, 12, 100)).toContain('L0,100');
    expect(columnPath(0, 100, 12, 100)).toBe('');
  });
});
