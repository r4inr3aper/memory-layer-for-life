/**
 * SettingsMenuModal Component
 *
 * An iOS pull-down menu anchored to the header's "…" button. It grows out of the button
 * (scale from 95% at its top-right corner, with a fade) and lists, in groups:
 * 1. Edit Mascot & Avatar, Rename Agent
 * 2. Share Chat, Clear Messages
 * 3. Delete Chat (destructive; side chats only, the main chat can only be cleared)
 *
 * The chat actions appear only while a chat is open on screen: they act on that chat, and
 * the header is shared by every tab.
 */

import React from 'react';
import { Modal, Platform, Pressable, StyleSheet, View } from 'react-native';
import Animated, { Keyframe } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import {
  Edit01Icon,
  Delete02Icon,
  Share01Icon,
  SparklesIcon,
  RefreshIcon,
} from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { Elevation, Hairline, Motion, Radius, continuous } from '@/constants/theme';
import { AppText } from '@/components/ui/AppText';

// iOS cannot present an alert, share sheet, or another modal while this one is still
// fading out, so actions start once it has closed.
const AFTER_CLOSE_DELAY_MS = Platform.OS === 'ios' ? 350 : 0;

// Built once: the menu grows from its anchor, never from nothing.
const MENU_ENTER = new Keyframe({
  0: { opacity: 0, transform: [{ scale: 0.95 }] },
  100: { opacity: 1, transform: [{ scale: 1 }], easing: Motion.easeOut },
}).duration(200);

export interface SettingsMenuModalProps {
  /** Visibility state of the dropdown overlay */
  visible: boolean;
  /** Whether a chat is open on screen, so Share, Clear, and Delete have one to act on */
  showChatActions?: boolean;
  /** Whether the open chat can be deleted (side chats only) */
  canDeleteChat?: boolean;
  /** Callback fired to close the dropdown menu */
  onClose: () => void;
  /** Callback to launch the agent customization modal */
  onEditAvatar: () => void;
  /** Callback to launch agent rename */
  onRename: () => void;
  /** Callback to reset conversation messages */
  onClearChat: () => void;
  /** Destructive callback to wipe active session */
  onDeleteChat: () => void;
  /** Callback to export or share conversation transcript */
  onShareChat?: () => void;
}

export const SettingsMenuModal: React.FC<SettingsMenuModalProps> = ({
  visible,
  showChatActions = false,
  canDeleteChat = false,
  onClose,
  onEditAvatar,
  onRename,
  onClearChat,
  onDeleteChat,
  onShareChat,
}) => {
  const insets = useSafeAreaInsets();

  const closeThen = (action?: () => void) => () => {
    onClose();
    if (action) {
      setTimeout(action, AFTER_CLOSE_DELAY_MS);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      statusBarTranslucent
      onRequestClose={onClose}>
      <Pressable
        style={[styles.overlay, { paddingTop: Math.max(insets.top, 12) + 50 }]}
        onPress={onClose}
        accessibilityLabel="Close the menu">
        <Animated.View entering={MENU_ENTER} style={[styles.menu, continuous]}>
          <Pressable>
            <MenuItem label="Edit Mascot & Avatar" icon={SparklesIcon} onPress={closeThen(onEditAvatar)} />
            <MenuSeparator />
            <MenuItem label="Rename Agent" icon={Edit01Icon} onPress={closeThen(onRename)} />

            {showChatActions ? (
              <>
                <View style={styles.groupGap} />
                <MenuItem label="Share Chat" icon={Share01Icon} onPress={closeThen(onShareChat)} />
                <MenuSeparator />
                <MenuItem label="Clear Messages" icon={RefreshIcon} onPress={closeThen(onClearChat)} />
                {canDeleteChat ? (
                  <>
                    <View style={styles.groupGap} />
                    <MenuItem
                      label="Delete Chat"
                      icon={Delete02Icon}
                      destructive
                      onPress={closeThen(onDeleteChat)}
                    />
                  </>
                ) : null}
              </>
            ) : null}
          </Pressable>
        </Animated.View>
      </Pressable>
    </Modal>
  );
};

/** A menu item as iOS draws one: the label at the left, its glyph at the right. */
function MenuItem({
  label,
  icon,
  destructive = false,
  onPress,
}: {
  label: string;
  icon: IconSvgElement;
  destructive?: boolean;
  onPress: () => void;
}) {
  const color = destructive ? Colors.systemRed : Colors.label;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="menuitem"
      accessibilityLabel={label}
      style={({ pressed }) => [styles.item, pressed && styles.itemPressed]}>
      <AppText variant="body" style={{ color }} numberOfLines={1}>
        {label}
      </AppText>
      <HugeiconsIcon icon={icon} size={19} color={color} strokeWidth={1.9} />
    </Pressable>
  );
}

function MenuSeparator() {
  return <View style={styles.separator} />;
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'transparent',
    alignItems: 'flex-end',
    paddingRight: 12,
  },
  menu: {
    width: 250,
    borderRadius: Radius.md + 2,
    backgroundColor: Colors.white,
    overflow: 'hidden',
    transformOrigin: 'top right',
    ...Elevation.floating,
  },
  item: {
    minHeight: 46,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 11,
    backgroundColor: Colors.white,
  },
  itemPressed: {
    backgroundColor: Colors.cellPressed,
  },
  separator: {
    height: Hairline,
    backgroundColor: Colors.separator,
  },
  // iOS separates groups of a menu with a thick gray band.
  groupGap: {
    height: 8,
    backgroundColor: Colors.systemGray6,
  },
});

export default SettingsMenuModal;
