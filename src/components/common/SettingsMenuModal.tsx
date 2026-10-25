/**
 * SettingsMenuModal Component
 *
 * Floating dropdown action sheet anchored to the top-right 3-dots header button.
 * Provides quick actions:
 * 1. Edit Mascot & Avatar
 * 2. Rename Agent
 * 3. Share Chat (transcript)
 * 4. Clear Messages
 * 5. Delete Chat (Destructive; side chats only, the main chat can only be cleared)
 *
 * The chat actions (3–5) appear only while a chat is open on screen: they act on that chat,
 * and the header is shared by every tab.
 */

import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  TouchableWithoutFeedback,
  Platform,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  Edit01Icon,
  Delete02Icon,
  Share01Icon,
  SparklesIcon,
  RefreshIcon,
} from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';

// iOS cannot present an alert, share sheet, or another modal while this one is still
// fading out, so actions start once it has closed.
const AFTER_CLOSE_DELAY_MS = Platform.OS === 'ios' ? 350 : 0;

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

/**
 * Top-Right 3-Dots Action Sheet Dropdown
 */
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
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <TouchableWithoutFeedback onPress={onClose}>
        <View
          style={[
            styles.overlay,
            { paddingTop: Math.max(insets.top, 12) + (Platform.OS === 'web' ? 54 : 50) },
          ]}>
          <TouchableWithoutFeedback>
            <View style={styles.dropdownCard}>
              {/* 1. Edit Mascot & Avatar */}
              <TouchableOpacity
                style={styles.menuItem}
                onPress={closeThen(onEditAvatar)}
                activeOpacity={0.7}>
                <HugeiconsIcon
                  icon={SparklesIcon}
                  size={18}
                  color={Colors.iconDark}
                  strokeWidth={1.8}
                />
                <Text style={styles.itemText}>Edit Mascot & Avatar</Text>
              </TouchableOpacity>

              {/* 2. Rename Agent / Chat */}
              <TouchableOpacity
                style={styles.menuItem}
                onPress={closeThen(onRename)}
                activeOpacity={0.7}>
                <HugeiconsIcon
                  icon={Edit01Icon}
                  size={18}
                  color={Colors.iconDark}
                  strokeWidth={1.8}
                />
                <Text style={styles.itemText}>Rename Agent</Text>
              </TouchableOpacity>

              {showChatActions ? (
                <>
                  {/* 3. Share Conversation */}
                  <TouchableOpacity
                    style={styles.menuItem}
                    onPress={closeThen(onShareChat)}
                    activeOpacity={0.7}>
                    <HugeiconsIcon
                      icon={Share01Icon}
                      size={18}
                      color={Colors.iconDark}
                      strokeWidth={1.8}
                    />
                    <Text style={styles.itemText}>Share Chat</Text>
                  </TouchableOpacity>

                  {/* 4. Clear Messages */}
                  <TouchableOpacity
                    style={styles.menuItem}
                    onPress={closeThen(onClearChat)}
                    activeOpacity={0.7}>
                    <HugeiconsIcon
                      icon={RefreshIcon}
                      size={18}
                      color={Colors.iconDark}
                      strokeWidth={1.8}
                    />
                    <Text style={styles.itemText}>Clear Messages</Text>
                  </TouchableOpacity>

                  {/* 5. Delete Chat (Destructive) */}
                  {canDeleteChat ? (
                    <>
                      <View style={styles.divider} />
                      <TouchableOpacity
                        style={[styles.menuItem, styles.dangerItem]}
                        onPress={closeThen(onDeleteChat)}
                        activeOpacity={0.7}>
                        <HugeiconsIcon
                          icon={Delete02Icon}
                          size={18}
                          color={Colors.error}
                          strokeWidth={1.8}
                        />
                        <Text style={[styles.itemText, styles.dangerText]}>Delete Chat</Text>
                      </TouchableOpacity>
                    </>
                  ) : null}
                </>
              ) : null}
            </View>
          </TouchableWithoutFeedback>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.08)',
    justifyContent: 'flex-start',
    alignItems: 'flex-end',
    paddingTop: Platform.OS === 'ios' ? 64 : 56,
    paddingRight: 16,
  },
  dropdownCard: {
    width: 200,
    backgroundColor: Colors.white,
    borderRadius: 14,
    paddingVertical: 6,
    paddingHorizontal: 5,
    borderWidth: 1,
    borderColor: Colors.border,
    ...Platform.select({
      ios: {
        shadowColor: Colors.black,
        shadowOffset: { width: 0, height: 6 },
        shadowOpacity: 0.12,
        shadowRadius: 16,
      },
      android: {
        elevation: 8,
      },
      web: {
        boxShadow: '0 8px 24px rgba(15, 23, 42, 0.12), 0 2px 6px rgba(15, 23, 42, 0.04)',
      },
    }),
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 9,
    paddingHorizontal: 10,
    borderRadius: 9,
    gap: 10,
  },
  dangerItem: {
    marginTop: 1,
  },
  itemText: {
    fontSize: 13.5,
    fontWeight: '500',
    color: Colors.textPrimary,
    letterSpacing: -0.2,
  },
  dangerText: {
    color: Colors.error,
    fontWeight: '500',
  },
  divider: {
    height: 1,
    backgroundColor: Colors.borderLight,
    marginVertical: 4,
    marginHorizontal: 6,
  },
});

export default SettingsMenuModal;
