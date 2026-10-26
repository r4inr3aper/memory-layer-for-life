/**
 * AppText: text in one of the iOS text styles (Typography), in a label color.
 *
 *   <AppText variant="headline">Title</AppText>
 *   <AppText variant="footnote" color="secondary">Detail</AppText>
 *
 * `weight` emphasizes without changing size, as iOS's bold variants do.
 */

import React from 'react';
import { Text, type TextProps, type TextStyle } from 'react-native';
import { Colors } from '@/constants/colors';
import { Typography, type TypographyVariant } from '@/constants/theme';

const TONES = {
  primary: Colors.label,
  secondary: Colors.secondaryLabel,
  tertiary: Colors.tertiaryLabel,
  tint: Colors.tint,
  destructive: Colors.systemRed,
  success: Colors.systemGreen,
  inverse: Colors.white,
} as const;

export type TextTone = keyof typeof TONES;

export interface AppTextProps extends TextProps {
  variant?: TypographyVariant;
  /** A label tone, or any color. */
  color?: TextTone | (string & {});
  weight?: TextStyle['fontWeight'];
  align?: TextStyle['textAlign'];
}

export function AppText({
  variant = 'body',
  color = 'primary',
  weight,
  align,
  style,
  ...props
}: AppTextProps) {
  const tone = color in TONES ? TONES[color as TextTone] : color;
  return (
    <Text
      {...props}
      style={[
        Typography[variant],
        { color: tone },
        weight !== undefined && { fontWeight: weight },
        align !== undefined && { textAlign: align },
        style,
      ]}
    />
  );
}

export default AppText;
