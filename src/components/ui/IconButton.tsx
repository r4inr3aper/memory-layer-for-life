/**
 * IconButton: a round glyph button, as in iOS navigation bars and toolbars.
 *
 * `filled` sits on a gray fill (bars over content); `plain` is the glyph alone in the tint
 * (inside rows and cards). The visual can be small; the touch target stays 44 pt.
 */

import React from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import { Colors } from '@/constants/colors';
import type { haptic } from '@/lib/haptics';
import { PressableScale } from './PressableScale';

export interface IconButtonProps {
  icon: IconSvgElement;
  onPress?: () => void;
  accessibilityLabel: string;
  variant?: 'filled' | 'plain' | 'tinted';
  /** Diameter of the visual. */
  size?: number;
  iconSize?: number;
  color?: string;
  disabled?: boolean;
  /** A small dot at the top right, for something new. */
  badge?: boolean;
  haptic?: keyof typeof haptic;
  /** For a toggle (a mic that is listening): announced as selected. */
  selected?: boolean;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}

const MIN_TARGET = 44;

export function IconButton({
  icon,
  onPress,
  accessibilityLabel,
  variant = 'filled',
  size = 36,
  iconSize,
  color,
  disabled,
  badge = false,
  haptic: hapticKind,
  selected,
  style,
  testID,
}: IconButtonProps) {
  const slop = Math.max(0, (MIN_TARGET - size) / 2);
  const background =
    variant === 'filled' ? Colors.tertiaryFill : variant === 'tinted' ? Colors.tintFill : 'transparent';
  const foreground = color ?? (variant === 'filled' ? Colors.label : Colors.tint);
  return (
    <PressableScale
      onPress={onPress}
      disabled={disabled}
      haptic={hapticKind}
      hitSlop={{ top: slop, bottom: slop, left: slop, right: slop }}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled, selected }}
      testID={testID}
      pressedScale={0.92}
      style={[
        styles.button,
        { width: size, height: size, borderRadius: size / 2, backgroundColor: background },
        style,
      ]}>
      <HugeiconsIcon
        icon={icon}
        size={iconSize ?? Math.round(size * 0.55)}
        color={foreground}
        strokeWidth={2}
      />
      {badge ? <View style={styles.badge} /> : null}
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  badge: {
    position: 'absolute',
    top: 1,
    right: 1,
    width: 9,
    height: 9,
    borderRadius: 4.5,
    backgroundColor: Colors.tint,
    borderWidth: 1.5,
    borderColor: Colors.white,
  },
});

export default IconButton;
