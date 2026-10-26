/**
 * SegmentedControl: iOS's segmented control. A white thumb slides between equal segments
 * on a gray track.
 *
 * The thumb is absolutely positioned with no children, so animating its position is free;
 * it moves on an ease-in-out (it travels across the screen) in 250 ms, and the selection
 * tick fires on the press, not when the thumb lands. Segments are measured once, not per
 * frame.
 */

import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, View, type LayoutChangeEvent, type StyleProp, type ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated';
import { Colors } from '@/constants/colors';
import { Elevation, Motion, Typography, continuous } from '@/constants/theme';
import { haptic } from '@/lib/haptics';
import { AppText } from './AppText';

export interface SegmentedControlProps<Value extends string> {
  segments: readonly { value: Value; label: string; badge?: number }[];
  value: Value;
  onChange: (value: Value) => void;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}

const TRACK_PADDING = 2;
const HEIGHT = 34;

export function SegmentedControl<Value extends string>({
  segments,
  value,
  onChange,
  style,
  testID,
}: SegmentedControlProps<Value>) {
  const [trackWidth, setTrackWidth] = useState(0);
  const reducedMotion = useReducedMotion();
  const index = Math.max(
    0,
    segments.findIndex((segment) => segment.value === value)
  );
  const segmentWidth = trackWidth > 0 ? (trackWidth - TRACK_PADDING * 2) / segments.length : 0;
  const x = useSharedValue(0);

  useEffect(() => {
    const target = index * segmentWidth;
    x.set(reducedMotion ? target : withTiming(target, { duration: 250, easing: Motion.easeInOut }));
  }, [index, segmentWidth, reducedMotion, x]);

  const thumbStyle = useAnimatedStyle(() => ({ transform: [{ translateX: x.get() }] }));

  return (
    <View
      testID={testID}
      accessibilityRole="tablist"
      style={[styles.track, continuous, style]}
      onLayout={(event: LayoutChangeEvent) => setTrackWidth(event.nativeEvent.layout.width)}>
      {segmentWidth > 0 ? (
        <Animated.View style={[styles.thumb, continuous, { width: segmentWidth }, thumbStyle]} />
      ) : null}
      {segments.map((segment) => {
        const selected = segment.value === value;
        return (
          <Pressable
            key={segment.value}
            style={styles.segment}
            hitSlop={{ top: 6, bottom: 6 }}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            accessibilityLabel={segment.badge ? `${segment.label}, ${segment.badge}` : segment.label}
            onPress={() => {
              if (selected) return;
              haptic.selection();
              onChange(segment.value);
            }}>
            <AppText
              numberOfLines={1}
              style={[Typography.footnote, styles.label, selected && styles.labelSelected]}>
              {segment.label}
            </AppText>
            {segment.badge ? (
              <View style={styles.badge}>
                <AppText variant="caption2" color="inverse" weight="700">
                  {segment.badge > 99 ? '99+' : segment.badge}
                </AppText>
              </View>
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    height: HEIGHT,
    flexDirection: 'row',
    padding: TRACK_PADDING,
    borderRadius: 9,
    backgroundColor: Colors.tertiaryFill,
  },
  thumb: {
    position: 'absolute',
    top: TRACK_PADDING,
    left: TRACK_PADDING,
    bottom: TRACK_PADDING,
    borderRadius: 7,
    backgroundColor: Colors.white,
    ...Elevation.raised,
  },
  segment: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 5,
    paddingHorizontal: 6,
  },
  label: {
    fontWeight: '500',
    color: Colors.label,
  },
  labelSelected: {
    fontWeight: '600',
  },
  badge: {
    minWidth: 17,
    height: 17,
    borderRadius: 8.5,
    paddingHorizontal: 4,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.systemRed,
  },
});

export default SegmentedControl;
