/**
 * Cost History (a row in the Settings "Today" section)
 *
 * A disclosure row that opens estimated cost per day, week, or month as columns, with the
 * prompts used. Nothing loads until it is first opened; while open, it refreshes whenever
 * Settings comes back into view.
 *
 * One series in the tint; the tapped column (by default the current period) is darker and
 * read out above the chart, so every value is reachable without the chart too. Axes are
 * minimal, as in Screen Time: hairline gridlines, values at the right, three dates below.
 * Each column's hit area is its whole slot, and screen readers get one labelled button per
 * period. While a new range loads, the previous chart stays, dimmed. Costs are in the
 * currency the backend reports (rupees by default). Periods are UTC, like the daily
 * prompt limit; weeks start on Monday.
 */

import { AppText, Button, SegmentedControl } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Hairline, Motion } from '@/constants/theme';
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
import { ArrowRight01Icon } from '@hugeicons/core-free-icons';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import Animated, { useReducedMotion } from 'react-native-reanimated';
import Svg, { Line, Path, Text as SvgText } from 'react-native-svg';

const GRANULARITIES: UsageGranularity[] = ['day', 'week', 'month'];
const SEGMENTS = GRANULARITIES.map((value) => ({ value, label: GRANULARITY_LABELS[value] }));
const PLOT_HEIGHT = 132;
const X_AXIS_BAND = 22;
// The value labels sit at the right of the plot, as in Screen Time.
const Y_AXIS_WIDTH = 46;
const Y_LABEL_GAP = 6;
const PLOT_TOP = 8;
const MAX_COLUMN_WIDTH = 24;
const AXIS_FONT_SIZE = 11;

export function CostHistory() {
  const [isOpen, setIsOpen] = useState(false);
  const [granularity, setGranularity] = useState<UsageGranularity>('day');
  const [history, setHistory] = useState<UsageHistory | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [chartWidth, setChartWidth] = useState(0);
  const [pressed, setPressed] = useState(false);
  const reducedMotion = useReducedMotion();

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
    <View>
      {/* A disclosure row: highlights while touched, like a list cell; the chevron turns
          down when open. */}
      <Pressable
        onPress={() => setIsOpen((open) => !open)}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        unstable_pressDelay={40}
        pressRetentionOffset={16}
        accessibilityRole="button"
        accessibilityState={{ expanded: isOpen }}
        accessibilityLabel="Cost history">
        <Animated.View style={[styles.toggleRow, pressed ? styles.rowPressed : styles.rowIdle]}>
          <AppText variant="body" style={styles.toggleText}>
            Cost history
          </AppText>
          <Animated.View
            style={[
              styles.chevron,
              isOpen && styles.chevronOpen,
              reducedMotion && styles.chevronStill,
            ]}>
            <HugeiconsIcon
              icon={ArrowRight01Icon}
              size={18}
              color={Colors.tertiaryLabel}
              strokeWidth={2.2}
            />
          </Animated.View>
        </Animated.View>
      </Pressable>

      {isOpen ? (
        <View style={styles.body}>
          <SegmentedControl segments={SEGMENTS} value={granularity} onChange={setGranularity} />

          {history === null ? (
            error ? (
              <View style={styles.errorBlock}>
                <AppText variant="footnote" color="destructive">
                  {error}
                </AppText>
                <Button
                  title="Try again"
                  variant="plain"
                  size="small"
                  onPress={() => load()}
                  containerStyle={styles.retry}
                />
              </View>
            ) : (
              <ActivityIndicator style={styles.spinner} color={Colors.secondaryLabel} />
            )
          ) : (
            <View style={isLoading && styles.refetching}>
              <AppText variant="title2">{formatCost(history.total_cost, currency)}</AppText>
              <AppText variant="footnote" color="secondary" style={styles.caption}>
                {rangeCaption(shownGranularity)} · {history.total_prompts.toLocaleString()}{' '}
                {history.total_prompts === 1 ? 'prompt' : 'prompts'} · UTC
              </AppText>

              {selectedPeriod ? (
                <View style={styles.readout}>
                  <AppText variant="subheadline" weight="600">
                    {formatCost(selectedPeriod.cost, currency)}
                  </AppText>
                  <AppText variant="footnote" color="secondary" style={styles.readoutLabel}>
                    {periodLabel(selectedPeriod.start, shownGranularity, 'long')} ·{' '}
                    {selectedPeriod.prompts.toLocaleString()}{' '}
                    {selectedPeriod.prompts === 1 ? 'prompt' : 'prompts'}
                  </AppText>
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
                        x1={0}
                        x2={plotWidth}
                        y1={yFor(tick)}
                        y2={yFor(tick)}
                        stroke={Colors.chartGrid}
                        strokeWidth={tick === 0 ? 1 : Hairline}
                        strokeDasharray={tick === 0 ? undefined : '3 3'}
                      />
                    ))}
                    {ticks.map((tick) => (
                      <SvgText
                        key={`tick-${tick}`}
                        x={plotWidth + Y_LABEL_GAP}
                        y={yFor(tick) + AXIS_FONT_SIZE / 3}
                        fontSize={AXIS_FONT_SIZE}
                        fill={Colors.chartAxisText}
                        textAnchor="start">
                        {formatTick(tick, step, currency)}
                      </SvgText>
                    ))}
                    {periods.map((period, index) => {
                      const x = index * slot + (slot - columnWidth) / 2;
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
                            ? 0
                            : position === all.length - 1
                              ? plotWidth
                              : (index + 0.5) * slot
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
                    style={[styles.hitArea, { left: index * slot, width: slot }]}
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
                <AppText variant="footnote" color="secondary" style={styles.caption}>
                  Chats and scheduled tasks will show here.
                </AppText>
              ) : null}
              {error ? (
                <AppText variant="footnote" color="destructive" style={styles.caption}>
                  {error}
                </AppText>
              ) : null}
            </View>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  toggleRow: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    paddingHorizontal: 16,
    paddingVertical: 10,
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  // Highlight at once on touch down; fade out after release (as ListRow does).
  rowPressed: {
    backgroundColor: Colors.cellPressed,
    transitionDuration: 0,
  },
  rowIdle: {
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionDuration: 350,
  },
  toggleText: {
    flex: 1,
  },
  chevron: {
    transform: [{ rotate: '0deg' }],
    transitionProperty: 'transform',
    transitionDuration: Motion.duration.small,
    transitionTimingFunction: Motion.css.easeOut,
  },
  chevronOpen: {
    transform: [{ rotate: '90deg' }],
  },
  chevronStill: {
    transitionDuration: 0,
  },
  body: {
    gap: 14,
    paddingHorizontal: 16,
    paddingTop: 4,
    paddingBottom: 16,
  },
  caption: {
    marginTop: 2,
  },
  readout: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 8,
    marginTop: 14,
    marginBottom: 6,
  },
  readoutLabel: {
    flexShrink: 1,
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
  errorBlock: {
    alignItems: 'flex-start',
    gap: 4,
  },
  retry: {
    marginLeft: -4,
  },
});
