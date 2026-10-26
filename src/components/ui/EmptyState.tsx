/**
 * EmptyState: what a screen or section shows when it has nothing yet. A glyph in a soft
 * circle, a short title that names what is missing, one sentence on how it fills, and at
 * most one action.
 */

import React from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import { Colors } from '@/constants/colors';
import { AppText } from './AppText';
import { Button } from './Button';

export interface EmptyStateProps {
  icon?: IconSvgElement;
  title: string;
  message?: string;
  actionTitle?: string;
  onAction?: () => void;
  /** Smaller, for an empty section inside a screen. */
  compact?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function EmptyState({
  icon,
  title,
  message,
  actionTitle,
  onAction,
  compact = false,
  style,
}: EmptyStateProps) {
  return (
    <View style={[styles.container, compact && styles.compact, style]}>
      {icon ? (
        <View style={[styles.iconCircle, compact && styles.iconCircleCompact]}>
          <HugeiconsIcon
            icon={icon}
            size={compact ? 24 : 30}
            color={Colors.secondaryLabel}
            strokeWidth={1.8}
          />
        </View>
      ) : null}
      <AppText variant={compact ? 'headline' : 'title3'} align="center">
        {title}
      </AppText>
      {message ? (
        <AppText variant="subheadline" color="secondary" align="center" style={styles.message}>
          {message}
        </AppText>
      ) : null}
      {actionTitle && onAction ? (
        <Button title={actionTitle} onPress={onAction} variant="tinted" size="small" containerStyle={styles.action} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 36,
    paddingVertical: 48,
    gap: 8,
  },
  compact: {
    paddingVertical: 28,
    paddingHorizontal: 24,
  },
  iconCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.tertiaryFill,
    marginBottom: 8,
  },
  iconCircleCompact: {
    width: 48,
    height: 48,
    borderRadius: 24,
    marginBottom: 4,
  },
  message: {
    maxWidth: 320,
  },
  action: {
    marginTop: 10,
  },
});

export default EmptyState;
