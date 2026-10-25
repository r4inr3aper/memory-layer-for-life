/**
 * SidebarDrawer Component
 *
 * Fullscreen sliding drawer interface providing session management:
 * 1. Top bar: Agent title & right arrow dismissal button
 * 2. Main Chat: Quick jump capsule back to primary conversation
 * 3. Side Chats: Filterable list of parallel conversation threads with unread indicators
 * 4. Bottom Toolbar: Settings gear shortcut, search filter input, and compose new chat button
 */

import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage } from '@/lib/api/client';
import {
  createSideThread,
  deleteThread as deleteThreadApi,
  ensureMainThread,
  listThreads,
} from '@/lib/api/threads';
import type { Thread } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { SideChatItem } from '@/types';
import {
  ArrowRight01Icon,
  Delete02Icon,
  Edit02Icon,
  Search01Icon,
  Settings01Icon,
} from '@hugeicons/core-free-icons';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { useGlobalSearchParams, useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import {
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

const SIDE_CHAT_PAGE_LIMIT = 100;

export interface SidebarDrawerProps {
  /** Visibility state of the drawer modal */
  visible: boolean;
  /** Active chat session identifier */
  activeChatId?: string;
  /** Active agent name displayed in drawer header */
  agentName?: string;
  /** Callback fired to close the drawer */
  onClose: () => void;
  /** Callback fired when a conversation item is tapped */
  onSelectChat: (chatTitle: string) => void;
  /** Callback fired to initiate a clean chat session */
  onNewChat: () => void;
  /** Callback fired to navigate directly to settings */
  onOpenSettings?: () => void;
  /** Callback fired to clear all side chat topics */
  onClearSideChats?: () => void;
}

/**
 * Slide-in Session History Drawer
 */
export const SidebarDrawer: React.FC<SidebarDrawerProps> = ({
  visible,
  activeChatId,
  agentName = 'Cooper',
  onClose,
  onSelectChat,
  onNewChat,
  onOpenSettings,
  onClearSideChats,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const router = useRouter();
  const { thread_id: openThreadId } = useGlobalSearchParams<{ thread_id?: string }>();
  const [sideChatList, setSideChatList] = useState<SideChatItem[]>([]);
  const [mainChatThread, setMainChatThread] = useState<Thread | null>(null);
  // Filter side chat topics by active search query
  const filteredChats = sideChatList.filter((chat) =>
    chat.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Refresh every time the drawer opens: side chats get their titles from the server.
  useEffect(() => {
    if (!visible) return;

    let isCurrent = true;
    Promise.all([ensureMainThread(), listThreads({ kind: 'side', limit: SIDE_CHAT_PAGE_LIMIT })])
      .then(([mainChat, sidePage]) => {
        if (!isCurrent) return;
        setMainChatThread(mainChat);
        setSideChatList(
          sidePage.items.map((thread) => ({
            id: thread.id,
            title: thread.title,
          }))
        );
      })
      .catch((error) => {
        if (!isCurrent) return;
        console.error('Failed to load chats:', error);
        showToast(getErrorMessage(error, 'Could not load chats'));
      });

    return () => {
      isCurrent = false;
    };
  }, [visible]);

  const CreateNewSideChat = async () => {
    //Create a new side chat and close the drawer
    try {
      // No title: the server names the thread from its first message.
      const sideThread = await createSideThread();

      router.replace({
        pathname: '/(tabs)/chat',
        params: {
          thread_id: sideThread.id,
          chatType: 'side',
        },
      });
      onClose();
    } catch (error) {
      console.error('Failed to create side chat:', error);
      showToast(getErrorMessage(error, 'Could not start a new chat'));
    }
  };

  const deleteThread = async (threadId: string, title: string) => {
    const confirmed = await confirmAsync({
      title: 'Delete this chat?',
      message:
        `"${title}" and all of its messages will be deleted. This can't be undone. ` +
        'Memories Cooper saved from it are kept; manage them in Memories.',
      confirmText: 'Delete',
      destructive: true,
    });
    if (!confirmed) return;

    try {
      await deleteThreadApi(threadId);
      setSideChatList((prev) => prev.filter((chat) => chat.id !== threadId));
      onClearSideChats?.();

      // The open chat no longer exists: go back to the main chat.
      if (openThreadId === threadId) {
        router.replace({
          pathname: '/(tabs)/chat',
          params: {
            thread_id: mainChatThread?.id,
            chatType: 'main',
          },
        });
      }
    } catch (error) {
      console.error('Failed to delete side chat:', error);
      showToast(getErrorMessage(error, 'Could not delete the chat'));
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalContainer}>
        {/* Fullscreen white sidebar with safe area */}
        <SafeAreaView style={styles.safeContainer} edges={['top', 'bottom', 'left', 'right']}>
          {/* Top Bar: Center Name + Right Arrow Button */}
          <View style={styles.header}>
            <View style={styles.headerSideSpacer} />

            <Text style={styles.headerTitle}>{agentName}</Text>

            <TouchableOpacity
              style={styles.circleBtn}
              onPress={onClose}
              activeOpacity={0.7}
              accessibilityLabel="Close sidebar">
              <HugeiconsIcon
                icon={ArrowRight01Icon}
                size={22}
                color={Colors.iconDark}
                strokeWidth={2.2}
              />
            </TouchableOpacity>
          </View>

          {/* Main Chat Capsule Button */}
          <View style={styles.mainChatWrapper}>
            <TouchableOpacity
              style={styles.mainChatCapsule}
              onPress={() => {
                router.replace({
                  pathname: '/(tabs)/chat',
                  params: {
                    thread_id: mainChatThread?.id,
                    chatType: 'main',
                  },
                });
                // onSelectChat('Main chat');
                onClose();
              }}
              activeOpacity={0.8}>
              <Text style={styles.mainChatText}>Main chat</Text>
            </TouchableOpacity>
          </View>

          {/* Thin Divider Line */}
          <View style={styles.divider} />

          {/* Side Chats Section */}
          <ScrollView
            style={styles.scrollArea}
            contentContainerStyle={styles.scrollContent}
            showsVerticalScrollIndicator={false}>
            {/* Section Header */}
            <View style={styles.sectionHeaderRow}>
              <Text style={styles.sectionHeaderText}>Side chats</Text>
            </View>

            {/* Side Chats List */}
            {filteredChats.map((chat) => (
              <View key={chat.id}>
                <TouchableOpacity
                  style={styles.chatRow}
                  onPress={() => {
                    router.replace({
                      pathname: '/(tabs)/chat',
                      params: {
                        thread_id: chat.id,
                        chatType: 'side',
                      },
                    });
                    // onSelectChat(chat.title);
                    onClose();
                  }}
                  activeOpacity={0.7}>
                  <Text style={styles.chatRowText} numberOfLines={1}>
                    {chat.title}
                  </Text>
                  <View
                    style={{
                      display: 'flex',
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: 4,
                    }}>
                    {/* Blue Indicator Dot if unread */}
                    {chat.hasUnreadDot && <View style={styles.blueDot} />}
                    <TouchableOpacity
                      style={styles.trashBtn}
                      onPress={() => {
                        void deleteThread(chat.id, chat.title);
                      }}
                      activeOpacity={0.7}
                      accessibilityRole="button"
                      accessibilityLabel={`Delete ${chat.title}`}>
                      <HugeiconsIcon
                        icon={Delete02Icon}
                        size={20}
                        color={Colors.iconMuted}
                        strokeWidth={1.8}
                      />
                    </TouchableOpacity>
                  </View>
                </TouchableOpacity>
              </View>
            ))}
          </ScrollView>

          {/* Bottom Toolbar: Settings Gear (Left) + Search (Center) + Compose (Right) */}
          <View style={styles.bottomToolbar}>
            {/* Settings Gear Button */}
            <TouchableOpacity
              style={styles.circleBtn}
              onPress={() => {
                showToast('Settings');
                onClose();
                onOpenSettings?.();
              }}
              activeOpacity={0.7}
              accessibilityLabel="Settings">
              <HugeiconsIcon
                icon={Settings01Icon}
                size={22}
                color={Colors.iconDark}
                strokeWidth={2}
              />
            </TouchableOpacity>

            {/* Search Capsule Input */}
            <View style={styles.searchCapsule}>
              <HugeiconsIcon
                icon={Search01Icon}
                size={18}
                color={Colors.iconMuted}
                strokeWidth={2}
              />
              <TextInput
                style={styles.searchInput}
                placeholder="Search"
                placeholderTextColor={Colors.iconMuted}
                value={searchQuery}
                onChangeText={setSearchQuery}
              />
            </View>

            {/* New Chat Compose Button */}
            <TouchableOpacity
              style={styles.circleBtn}
              onPress={() => {
                CreateNewSideChat();
              }}
              activeOpacity={0.7}
              accessibilityLabel="New chat">
              <HugeiconsIcon icon={Edit02Icon} size={20} color={Colors.iconDark} strokeWidth={2} />
            </TouchableOpacity>
          </View>
        </SafeAreaView>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  modalContainer: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  safeContainer: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 12,
  },
  headerSideSpacer: {
    width: 48,
  },
  headerTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.2,
  },
  circleBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: Colors.white,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#F0F0F2',
    ...Platform.select({
      ios: {
        shadowColor: Colors.black,
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.06,
        shadowRadius: 6,
      },
      android: {
        elevation: 2,
      },
      web: {
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.06)',
      },
    }),
  },
  mainChatWrapper: {
    paddingHorizontal: 20,
    marginTop: 8,
    marginBottom: 16,
  },
  mainChatCapsule: {
    width: '100%',
    height: 54,
    backgroundColor: Colors.tabActiveBg, // #E6E8EA
    borderRadius: 27,
    justifyContent: 'center',
    paddingHorizontal: 20,
  },
  mainChatText: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  divider: {
    height: 1,
    backgroundColor: '#F0F0F2',
    width: '100%',
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 16,
  },
  sectionHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 10,
  },
  sectionHeaderText: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconMuted, // #8E8E93 / #9E9E9E
  },
  trashBtn: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chatRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 14,
  },
  chatRowText: {
    fontSize: 16,
    fontWeight: '400',
    color: Colors.iconDark,
    flex: 1,
    paddingRight: 10,
  },
  blueDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#0066FF',
  },
  bottomToolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: Platform.OS === 'ios' ? 12 : 16,
    backgroundColor: Colors.white,
  },
  searchCapsule: {
    flex: 1,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#F5F6F8',
    borderWidth: 1,
    borderColor: '#ECECEC',
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    marginHorizontal: 10,
    gap: 8,
  },
  searchInput: {
    flex: 1,
    fontSize: 15,
    color: Colors.iconDark,
    paddingVertical: 0,
  },
});

export default SidebarDrawer;
