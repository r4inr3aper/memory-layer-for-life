/**
 * AppHeader Component
 *
 * The navigation bar shared by the tabs, laid out like a conversation in Messages:
 * - Left: a round button that opens the chat list
 * - Center: the agent's avatar with its name under it; tapping it edits the agent
 * - Right: a round button with the "…" menu
 *
 * Over the chat it is the bar material (nearly opaque white) with a hairline under it; over
 * the grouped screens it takes their gray and no line, as an iOS bar does at the top of a
 * list.
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  ArrowRight01Icon,
  MoreHorizontalIcon,
  SidebarLeftIcon,
} from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { Hairline, ScreenMargin } from '@/constants/theme';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { AppText } from '@/components/ui/AppText';
import { IconButton } from '@/components/ui/IconButton';
import { PressableScale } from '@/components/ui/PressableScale';
import { MascotAvatar } from './MascotAvatar';

export interface AppHeaderProps {
  /** Callback to open the left sliding session drawer */
  onOpenSidebar: () => void;
  /** Callback to trigger the right 3-dots actions menu */
  onOpenSettings: () => void;
  /** Callback triggered when tapping the center mascot/name pill */
  onMascotPress?: () => void;
  /** The screen under it: the white chat, or a grouped (gray) screen. */
  background?: 'plain' | 'grouped';
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  onOpenSidebar,
  onOpenSettings,
  onMascotPress,
  background = 'plain',
}) => {
  const { profile } = useAgentProfile();
  // On gray, the round buttons are white, as iOS draws them over a grouped list.
  const buttonSurface = background === 'grouped' ? styles.buttonOnGrouped : undefined;

  return (
    <View style={[styles.headerContainer, background === 'grouped' && styles.headerGrouped]}>
      <View style={styles.sideCol}>
        <IconButton
          icon={SidebarLeftIcon}
          onPress={onOpenSidebar}
          accessibilityLabel="Open the chat list"
          size={38}
          style={buttonSurface}
          iconSize={21}
        />
      </View>

      <PressableScale
        onPress={onMascotPress || onOpenSettings}
        accessibilityRole="button"
        accessibilityLabel={`${profile.name}, edit name and avatar`}
        style={styles.centerCol}>
        <MascotAvatar size={38} icon={profile.icon} color={profile.color} />
        <View style={styles.nameRow}>
          <AppText variant="caption1" weight="600" numberOfLines={1} style={styles.agentName}>
            {profile.name}
          </AppText>
          <HugeiconsIcon icon={ArrowRight01Icon} size={11} color={Colors.tertiaryLabel} strokeWidth={2.6} />
        </View>
      </PressableScale>

      <View style={[styles.sideCol, styles.rightCol]}>
        <IconButton
          icon={MoreHorizontalIcon}
          onPress={onOpenSettings}
          accessibilityLabel="More options"
          size={38}
          style={buttonSurface}
          iconSize={22}
        />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  headerContainer: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: ScreenMargin,
    paddingTop: 4,
    paddingBottom: 6,
    backgroundColor: Colors.barBackground,
    borderBottomWidth: Hairline,
    borderBottomColor: Colors.separator,
    zIndex: 10,
  },
  headerGrouped: {
    backgroundColor: Colors.groupedBackground,
    borderBottomColor: 'transparent',
  },
  buttonOnGrouped: {
    backgroundColor: Colors.white,
  },
  sideCol: {
    width: 48,
    alignItems: 'flex-start',
  },
  rightCol: {
    alignItems: 'flex-end',
  },
  centerCol: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
  },
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 1,
    // Names can be up to 40 characters; keep them between the side buttons.
    maxWidth: 200,
  },
  agentName: {
    color: Colors.label,
  },
});

export default AppHeader;
