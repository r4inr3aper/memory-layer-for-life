/**
 * PressableScale: the press feedback of every tappable surface that is not a list row.
 *
 * It shrinks to 97% the moment a finger lands (not when it lifts), over 120 ms on a strong
 * ease-out, as a Reanimated CSS transition: a two-state change needs no worklet. The
 * label and icons scale with it, which is what makes it read as physical. With Reduce
 * Motion on, it dims instead of moving. A small control keeps a 44 pt touch target through
 * `hitSlop`, and a finger drifting a little does not cancel the press.
 */

import React, { useState } from 'react';
import {
  Pressable,
  StyleSheet,
  type GestureResponderEvent,
  type Insets,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import Animated, { useReducedMotion } from 'react-native-reanimated';
import { Motion } from '@/constants/theme';
import { haptic } from '@/lib/haptics';

export interface PressableScaleProps extends Omit<PressableProps, 'style' | 'children'> {
  children: React.ReactNode;
  /** Style of the surface that scales (background, radius, padding). */
  style?: StyleProp<ViewStyle>;
  /** Style of the touch area around it (margins, flex, alignment in the parent). */
  containerStyle?: StyleProp<ViewStyle>;
  /** How far it shrinks; large surfaces (cards) shrink less. */
  pressedScale?: number;
  /** A haptic fired with the press, for presses that commit something. */
  haptic?: keyof typeof haptic;
}

const DEFAULT_HIT_SLOP: Insets = { top: 6, bottom: 6, left: 6, right: 6 };

export function PressableScale({
  children,
  style,
  containerStyle,
  pressedScale = Motion.pressedScale,
  haptic: hapticKind,
  onPressIn,
  onPressOut,
  onPress,
  disabled,
  hitSlop = DEFAULT_HIT_SLOP,
  pressRetentionOffset = 16,
  ...props
}: PressableScaleProps) {
  const [pressed, setPressed] = useState(false);
  const reducedMotion = useReducedMotion();

  const pressedStyle: ViewStyle = reducedMotion
    ? { opacity: 0.6 }
    : { transform: [{ scale: pressedScale }] };

  return (
    <Pressable
      {...props}
      disabled={disabled}
      hitSlop={hitSlop}
      pressRetentionOffset={pressRetentionOffset}
      style={containerStyle}
      onPressIn={(event: GestureResponderEvent) => {
        setPressed(true);
        onPressIn?.(event);
      }}
      onPressOut={(event: GestureResponderEvent) => {
        setPressed(false);
        onPressOut?.(event);
      }}
      onPress={(event: GestureResponderEvent) => {
        // Only a press that does something (a loading button has no handler) is felt.
        if (!onPress) return;
        if (hapticKind) haptic[hapticKind]();
        onPress(event);
      }}>
      <Animated.View
        style={[styles.surface, style, pressed && !disabled && pressedStyle, disabled && styles.disabled]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  surface: {
    transform: [{ scale: 1 }],
    opacity: 1,
    transitionProperty: ['transform', 'opacity'],
    transitionDuration: Motion.duration.press,
    transitionTimingFunction: Motion.css.easeOut,
  },
  disabled: {
    opacity: 0.4,
  },
});

export default PressableScale;
