/**
 * MascotAvatar Component
 *
 * Simple 3D character mascot avatar portrait.
 */

import React from 'react';
import { Image, StyleSheet, ImageStyle, StyleProp, Text, View } from 'react-native';
import { Colors } from '@/constants/colors';
import { agentIconEmoji, DEFAULT_AGENT_ICON } from '@/constants/agentIcons';

export interface MascotAvatarProps {
  /** Avatar diameter in pixels (defaults to 54) */
  size?: number;
  /** Avatar icon key (see `AGENT_ICONS`); 'cooper' renders the original mascot image */
  icon?: string;
  /** Accent color for emoji avatar backgrounds */
  color?: string;
  /** Optional custom image style */
  style?: StyleProp<ImageStyle>;
}

export const MascotAvatar: React.FC<MascotAvatarProps> = ({
  size = 54,
  icon = DEFAULT_AGENT_ICON,
  color = Colors.primary,
  style,
}) => {
  const emoji = agentIconEmoji(icon);
  if (emoji) {
    return (
      <View
        style={[
          styles.emojiAvatar,
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            backgroundColor: `${color}22`,
          },
          style as any,
        ]}>
        <Text style={[styles.emojiText, { fontSize: Math.round(size * 0.52) }]}>
          {emoji}
        </Text>
      </View>
    );
  }

  return (
    <Image
      source={require('../../../assets/images/cooper_mascot.jpg')}
      style={[
        styles.avatar,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
        },
        style,
      ]}
      resizeMode="cover"
    />
  );
};

const styles = StyleSheet.create({
  avatar: {
    backgroundColor: Colors.avatarPreviewBg,
  },
  emojiAvatar: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  emojiText: {
    textAlign: 'center',
    includeFontPadding: false,
    lineHeight: undefined,
  },
});

export default MascotAvatar;
