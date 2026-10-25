/**
 * Cost History (inside the Settings "Today" card)
 *
 * A collapsible section: a chevron row that opens estimated cost per day, week, or month
 * as columns, with the prompts used. Nothing loads until it is first opened; while open,
 * it refreshes whenever Settings comes back into view.
 *
 * One series in one hue; the tapped column (by default the current period) is darker and
 * read out above the chart, so every value is reachable without the chart too. Each
 * column's hit area is its whole slot, and screen readers get one labelled button per
 * period. While a new range loads, the previous chart stays, dimmed. Costs are in the
 * currency the backend reports (rupees by default). Periods are UTC, like the daily
 * prompt limit; weeks start on Monday.
 */

import { Colors } from '@/constants/colors';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { getUsageHistory } from '@/lib/api/me';
import type { UsageGranularity, UsageHistory } from '@/lib/api/types';
import {
  axisLabelIndexes,
  columnPath,
  formatCost,
  formatTick,
  GRANULARITY_LABELS,
  niceTicks,
  periodLabel,
  rangeCaption,
  toAmount,
} from '@/lib/usageChart';
import { ArrowDown01Icon } from '@hugeicons/core-free-icons';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  type LayoutChangeEvent,
} from 'react-native';
import Svg, { Line, Path, Text as SvgText } from 'react-native-svg';

const GRANULARITIES: UsageGranularity[] = ['day', 'week', 'month'];
const PLOT_HEIGHT = 132;
const X_AXIS_BAND = 22;
const Y_AXIS_WIDTH = 46;
const PLOT_TOP = 8;
const MAX_COLUMN_WIDTH = 24;
const AXIS_FONT_SIZE = 10.5;

export function CostHistory() {
  const [isOpen, setIsOpen] = useState(false);
  const [granularity, setGranularity] = useState<UsageGranularity>('day');
  const [history, setHistory] = useState<UsageHistory | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [chartWidth, setChartWidth] = useState(0);

  const load = useCallback(
    (signal?: AbortSignal) => {
      setIsLoading(true);
      getUsageHistory(granularity, signal)
        .then((next) => {
          setHistory(next);
          setSelected(null);
          setError(null);
        })
        .catch((loadError) => {
          if (isAbortError(loadError, signal)) return;
          setError(getErrorMessage(loadError, 'Could not load the cost history'));
        })
        .finally(() => {
          if (!signal?.aborted) setIsLoading(false);
        });
    },
    [granularity]
  );

  // Load when opened, when the range changes, and when Settings comes back into view.
  useFocusEffect(
    useCallback(() => {
      if (!isOpen) return;
      const controller = new AbortController();
      load(controller.signal);
      return () => controller.abort();
    }, [isOpen, load])
  );

  const periods = history?.periods ?? [];
  const currency = history?.currency ?? 'INR';
  const shownGranularity = history?.granularity ?? granularity;
  const selectedIndex = selected ?? periods.length - 1;
  const selectedPeriod = periods[selectedIndex];
  const costs = periods.map((period) => toAmount(period.cost));
  const { ticks, top, step } = niceTicks(Math.max(0, ...costs));
  const isEmpty =
    history !== null && history.total_prompts === 0 && toAmount(history.total_cost) === 0;

  const plotWidth = Math.max(0, chartWidth - Y_AXIS_WIDTH);
  const slot = periods.length > 0 ? plotWidth / periods.length : 0;
  const columnWidth = Math.min(MAX_COLUMN_WIDTH, slot * 0.6);
  const baseline = PLOT_TOP + PLOT_HEIGHT;
  const yFor = (value: number) => baseline - (value / top) * PLOT_HEIGHT;

  return (
    <View style={styles.section}>
      <TouchableOpacity
        style={styles.toggleRow}
        onPress={() => setIsOpen((open) => !open)}
        activeOpacity={0.7}
        accessibilityRole="button"
        accessibilityState={{ expanded: isOpen }}
        accessibilityLabel="Cost history">
        <Text style={styles.toggleText}>Cost history</Text>
        <View style={isOpen && styles.chevronOpen}>
          <HugeiconsIcon icon={ArrowDown01Icon} size={18} color={Colors.iconDark} strokeWidth={2} />
        </View>
      </TouchableOpacity>

      {isOpen ? (
        <View style={styles.body}>
          <View style={styles.segmented} accessibilityRole="tablist">
            {GRANULARITIES.map((option) => {
              const active = option === granularity;
              return (
                <TouchableOpacity
                  key={option}
                  style={[styles.segment, active && styles.segmentActive]}
                  onPress={() => setGranularity(option)}
                  activeOpacity={0.7}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: active }}>
                  <Text style={[styles.segmentText, active && styles.segmentTextActive]}>
                    {GRANULARITY_LABELS[option]}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {history === null ? (
            error ? (
              <TouchableOpacity
                onPress={() => load()}
                activeOpacity={0.7}
                accessibilityRole="button">
                <Text style={styles.errorText}>{error}</Text>
                <Text style={styles.retryText}>Try again</Text>
              </TouchableOpacity>
            ) : (
              <ActivityIndicator style={styles.spinner} color={Colors.primary} />
            )
          ) : (
            <View style={isLoading && styles.refetching}>
              <Text style={styles.total}>{formatCost(history.total_cost, currency)}</Text>
              <Text style={styles.caption}>
                {rangeCaption(shownGranularity)} · {history.total_prompts.toLocaleString()}{' '}
                {history.total_prompts === 1 ? 'prompt' : 'prompts'} · UTC
              </Text>

              {selectedPeriod ? (
                <View style={styles.readout}>
                  <Text style={styles.readoutValue}>
                    {formatCost(selectedPeriod.cost, currency)}
                  </Text>
                  <Text style={styles.readoutLabel}>
                    {periodLabel(selectedPeriod.start, shownGranularity, 'long')} ·{' '}
                    {selectedPeriod.prompts.toLocaleString()}{' '}
                    {selectedPeriod.prompts === 1 ? 'prompt' : 'prompts'}
                  </Text>
                </View>
              ) : null}

              <View
                style={styles.chart}
                onLayout={(event: LayoutChangeEvent) =>
                  setChartWidth(event.nativeEvent.layout.width)
                }>
                {chartWidth > 0 ? (
                  <Svg width={chartWidth} height={PLOT_TOP + PLOT_HEIGHT + X_AXIS_BAND}>
                    {ticks.map((tick) => (
                      <Line
                        key={`grid-${tick}`}
                        x1={Y_AXIS_WIDTH}
                        x2={chartWidth}
                        y1={yFor(tick)}
                        y2={yFor(tick)}
                        stroke={Colors.chartGrid}
                        strokeWidth={1}
                      />
                    ))}
                    {ticks.map((tick) => (
                      <SvgText
                        key={`tick-${tick}`}
                        x={Y_AXIS_WIDTH - 8}
                        y={yFor(tick) + AXIS_FONT_SIZE / 3}
                        fontSize={AXIS_FONT_SIZE}
                        fill={Colors.chartAxisText}
                        textAnchor="end">
                        {formatTick(tick, step, currency)}
                      </SvgText>
                    ))}
                    {periods.map((period, index) => {
                      const x = Y_AXIS_WIDTH + index * slot + (slot - columnWidth) / 2;
                      return (
                        <Path
                          key={period.start}
                          d={columnPath(x, yFor(costs[index]), columnWidth, baseline)}
                          fill={index === selectedIndex ? Colors.chartBarSelected : Colors.chartBar}
                        />
                      );
                    })}
                    {axisLabelIndexes(periods.length).map((index, position, all) => (
                      <SvgText
                        key={`label-${periods[index].start}`}
                        x={
                          position === 0
                            ? Y_AXIS_WIDTH
                            : position === all.length - 1
                              ? chartWidth
                              : Y_AXIS_WIDTH + (index + 0.5) * slot
                        }
                        y={baseline + X_AXIS_BAND - 6}
                        fontSize={AXIS_FONT_SIZE}
                        fill={Colors.chartAxisText}
                        textAnchor={
                          position === 0 ? 'start' : position === all.length - 1 ? 'end' : 'middle'
                        }>
                        {periodLabel(periods[index].start, shownGranularity, 'short')}
                      </SvgText>
                    ))}
                  </Svg>
                ) : null}

                {/* One hit area per period: its whole slot, not just the painted column. */}
                {periods.map((period, index) => (
                  <Pressable
                    key={`hit-${period.start}`}
                    style={[styles.hitArea, { left: Y_AXIS_WIDTH + index * slot, width: slot }]}
                    onPress={() => setSelected(index)}
                    accessibilityRole="button"
                    accessibilityState={{ selected: index === selectedIndex }}
                    accessibilityLabel={`${periodLabel(period.start, shownGranularity, 'long')}: ${formatCost(
                      period.cost,
                      currency
                    )}, ${period.prompts} ${period.prompts === 1 ? 'prompt' : 'prompts'}`}
                  />
                ))}
              </View>

              {isEmpty ? (
                <Text style={styles.caption}>Chats and scheduled tasks will show here.</Text>
              ) : null}
              {error ? <Text style={styles.errorText}>{error}</Text> : null}
            </View>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    marginTop: 14,
    borderTopWidth: 1,
    borderTopColor: Colors.cardBorder,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 12,
    minHeight: 36,
  },
  toggleText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  chevronOpen: {
    transform: [{ rotate: '180deg' }],
  },
  body: {
    marginTop: 10,
  },
  segmented: {
    flexDirection: 'row',
    alignSelf: 'flex-start',
    backgroundColor: Colors.white,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    padding: 2,
    marginBottom: 12,
  },
  segment: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
  },
  segmentActive: {
    backgroundColor: Colors.tabActiveBg,
  },
  segmentText: {
    fontSize: 12.5,
    fontWeight: '600',
    color: Colors.chartAxisText,
  },
  segmentTextActive: {
    color: Colors.iconDark,
  },
  total: {
    fontSize: 26,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.4,
  },
  caption: {
    fontSize: 12.5,
    color: Colors.chartAxisText,
    marginTop: 2,
  },
  readout: {
    flexDirection: 'row',
    alignItems: 'baseline',
    marginTop: 14,
    marginBottom: 6,
  },
  readoutValue: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.iconDark,
    marginRight: 8,
  },
  readoutLabel: {
    fontSize: 12.5,
    color: Colors.chartAxisText,
  },
  chart: {
    height: PLOT_TOP + PLOT_HEIGHT + X_AXIS_BAND,
  },
  hitArea: {
    position: 'absolute',
    top: 0,
    bottom: 0,
  },
  refetching: {
    opacity: 0.5,
  },
  spinner: {
    alignSelf: 'flex-start',
    marginVertical: 6,
  },
  errorText: {
    fontSize: 13,
    lineHeight: 18,
    color: Colors.error,
    marginTop: 6,
  },
  retryText: {
    marginTop: 6,
    fontSize: 13.5,
    fontWeight: '700',
    color: Colors.primary,
  },
});
