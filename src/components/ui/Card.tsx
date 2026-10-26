/**
 * Card: a white rounded surface on the grouped background, for content that is not a list
 * row (a Today card, a preview). Contrast with the gray background separates it; it has
 * no border and no shadow. A card with `onPress` scales a little less than a button, as
 * larger surfaces should.
 */

import React from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { Colors } from '@/constants/colors';
import { Radius, continuous } from '@/constants/theme';
import { PressableScale } from './PressableScale';

export interface CardProps {
  children: React.ReactNode;
  onPress?: () => void;
  onLongPress?: () => void;
  style?: StyleProp<ViewStyle>;
  containerStyle?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  testID?: string;
}

export function Card({
  children,
  onPress,
  onLongPress,
  style,
  containerStyle,
  accessibilityLabel,
  accessibilityHint,
  testID,
}: CardProps) {
  if (!onPress && !onLongPress) {
    return (
      <View style={[styles.card, continuous, containerStyle, style]} testID={testID}>
        {children}
      </View>
    );
  }
  return (
    <PressableScale
      onPress={onPress}
      onLongPress={onLongPress}
      pressedScale={0.98}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      testID={testID}
      containerStyle={containerStyle}
      style={[styles.card, continuous, style]}>
      {children}
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.secondaryGroupedBackground,
    borderRadius: Radius.lg,
    padding: 16,
  },
});

export default Card;
