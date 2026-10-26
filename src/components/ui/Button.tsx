/**
 * Button: iOS button styles.
 *
 * - `filled`: the tint behind white text, for the one primary action on a screen.
 * - `tinted`: a tint wash behind tinted text, for secondary actions.
 * - `gray`: a gray fill behind label text, for neutral actions.
 * - `plain`: tinted text only, for actions inside content.
 * - `destructive`: red text on a red wash, for delete and sign out.
 *
 * Sizes follow iOS: `large` (50 pt, full width in forms), `medium` (44 pt), `small`
 * (a 32 pt capsule inside cards and rows). While `loading`, the label is replaced by a
 * spinner and presses are ignored.
 */

import React from 'react';
import { ActivityIndicator, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import { Colors } from '@/constants/colors';
import { Radius, Typography, continuous } from '@/constants/theme';
import type { haptic } from '@/lib/haptics';
import { AppText } from './AppText';
import { PressableScale } from './PressableScale';

export type ButtonVariant = 'filled' | 'tinted' | 'gray' | 'plain' | 'destructive';
export type ButtonSize = 'large' | 'medium' | 'small';

export interface ButtonProps {
  title: string;
  onPress?: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconSvgElement;
  loading?: boolean;
  disabled?: boolean;
  /** Stretch to the width of the parent. */
  block?: boolean;
  haptic?: keyof typeof haptic;
  style?: StyleProp<ViewStyle>;
  containerStyle?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
  testID?: string;
}

const PALETTE: Record<ButtonVariant, { background: string; foreground: string }> = {
  filled: { background: Colors.tint, foreground: Colors.white },
  tinted: { background: Colors.tintFill, foreground: Colors.tint },
  gray: { background: Colors.tertiaryFill, foreground: Colors.label },
  plain: { background: 'transparent', foreground: Colors.tint },
  destructive: { background: Colors.errorLight, foreground: Colors.systemRed },
};

const SIZES: Record<ButtonSize, { height: number; paddingHorizontal: number; radius: number; icon: number }> = {
  large: { height: 50, paddingHorizontal: 20, radius: Radius.md + 2, icon: 20 },
  medium: { height: 44, paddingHorizontal: 18, radius: Radius.md, icon: 18 },
  small: { height: 32, paddingHorizontal: 14, radius: Radius.pill, icon: 16 },
};

export function Button({
  title,
  onPress,
  variant = 'filled',
  size = 'medium',
  icon,
  loading = false,
  disabled = false,
  block = false,
  haptic: hapticKind,
  style,
  containerStyle,
  accessibilityLabel,
  testID,
}: ButtonProps) {
  const palette = PALETTE[variant];
  const metrics = SIZES[size];
  const textStyle = size === 'small' ? Typography.subheadline : Typography.headline;

  return (
    <PressableScale
      onPress={loading ? undefined : onPress}
      disabled={disabled}
      haptic={hapticKind}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? title}
      accessibilityState={{ disabled, busy: loading }}
      testID={testID}
      containerStyle={[block && styles.block, containerStyle]}
      style={[
        styles.button,
        continuous,
        {
          height: metrics.height,
          paddingHorizontal: variant === 'plain' ? 4 : metrics.paddingHorizontal,
          borderRadius: metrics.radius,
          backgroundColor: palette.background,
        },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator size="small" color={palette.foreground} />
      ) : (
        <View style={styles.content}>
          {icon ? (
            <HugeiconsIcon icon={icon} size={metrics.icon} color={palette.foreground} strokeWidth={2} />
          ) : null}
          <AppText
            numberOfLines={1}
            style={[textStyle, { color: palette.foreground }, size === 'small' && styles.smallLabel]}>
            {title}
          </AppText>
        </View>
      )}
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  block: {
    alignSelf: 'stretch',
  },
  button: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  smallLabel: {
    fontWeight: '600',
  },
});

export default Button;
