/**
 * SidebarDrawer Component
 *
 * The chat list, drawn inside the tab layout's sliding drawer (opened from the header
 * button or a swipe right on Chat; the layout also handles Android's back button), laid
 * out like an iOS sidebar:
 * 1. A search field and the compose button (a new side chat)
 * 2. Main chat, then the side chats; the open one is highlighted. Touch and hold a side
 *    chat to delete it.
 * 3. Settings at the bottom
 */

import { Colors } from '@/constants/colors';
import { Radius, ScreenMargin, Typography, continuous } from '@/constants/theme';
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
import { haptic } from '@/lib/haptics';
import { SideChatItem } from '@/types';
import {
  Comment01Icon,
  Edit02Icon,
  Search01Icon,
  Settings02Icon,
} from '@hugeicons/core-free-icons';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import { useGlobalSearchParams, useRouter } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AppText } from '@/components/ui/AppText';
import { IconButton } from '@/components/ui/IconButton';

const SIDE_CHAT_PAGE_LIMIT = 100;

export interface SidebarDrawerProps {
  /** Whether the drawer is open; the chat list reloads each time it opens */
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
  agentName = 'Cooper',
  onClose,
  onOpenSettings,
  onClearSideChats,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const router = useRouter();
  const { thread_id: openThreadId } = useGlobalSearchParams<{ thread_id?: string }>();
  const [sideChatList, setSideChatList] = useState<SideChatItem[]>([]);
  const [mainChatThread, setMainChatThread] = useState<Thread | null>(null);
  const [loaded, setLoaded] = useState(false);
  // Filter side chat topics by active search query
  const filteredChats = sideChatList.filter((chat) =>
    chat.title.toLowerCase().includes(searchQuery.trim().toLowerCase())
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
        setLoaded(true);
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

  const openThread = (threadId: string | undefined, chatType: 'main' | 'side') => {
    router.replace({ pathname: '/(tabs)/chat', params: { thread_id: threadId, chatType } });
    onClose();
  };

  const createNewSideChat = async () => {
    try {
      // No title: the server names the thread from its first message.
      const sideThread = await createSideThread();
      haptic.light();
      openThread(sideThread.id, 'side');
    } catch (error) {
      console.error('Failed to create side chat:', error);
      showToast(getErrorMessage(error, 'Could not start a new chat'));
    }
  };

  const deleteThread = async (threadId: string, title: string) => {
    haptic.medium();
    const confirmed = await confirmAsync({
      title: 'Delete this chat?',
      message:
        `"${title}" and all of its messages will be deleted. This can't be undone. ` +
        `Memories ${agentName} saved from it are kept; manage them in Memories.`,
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
          params: { thread_id: mainChatThread?.id, chatType: 'main' },
        });
      }
    } catch (error) {
      console.error('Failed to delete side chat:', error);
      showToast(getErrorMessage(error, 'Could not delete the chat'));
    }
  };

  const mainIsOpen = !openThreadId || openThreadId === mainChatThread?.id;

  return (
    <SafeAreaView style={styles.safeContainer} edges={['top', 'bottom', 'left']}>
      {/* Search and compose */}
      <View style={styles.topBar}>
        <View style={[styles.searchField, continuous]}>
          <HugeiconsIcon icon={Search01Icon} size={17} color={Colors.secondaryLabel} strokeWidth={2} />
          <TextInput
            style={styles.searchInput}
            placeholder="Search"
            placeholderTextColor={Colors.placeholder}
            value={searchQuery}
            onChangeText={setSearchQuery}
            returnKeyType="search"
            clearButtonMode="while-editing"
            accessibilityLabel="Search chats"
          />
        </View>
        <IconButton
          icon={Edit02Icon}
          onPress={() => void createNewSideChat()}
          accessibilityLabel="New chat"
          variant="tinted"
          size={38}
          iconSize={19}
        />
      </View>

      <ScrollView
        style={styles.scrollArea}
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}>
        <ChatRow
          title="Main chat"
          icon={Comment01Icon}
          selected={mainIsOpen}
          onPress={() => openThread(mainChatThread?.id, 'main')}
        />

        <AppText variant="footnote" color="secondary" weight="600" style={styles.sectionHeader}>
          Side chats
        </AppText>

        {filteredChats.map((chat) => (
          <ChatRow
            key={chat.id}
            title={chat.title}
            selected={openThreadId === chat.id}
            onPress={() => openThread(chat.id, 'side')}
            onLongPress={() => void deleteThread(chat.id, chat.title)}
            accessibilityHint="Touch and hold to delete"
          />
        ))}

        {loaded && filteredChats.length === 0 ? (
          <AppText variant="footnote" color="tertiary" style={styles.emptyNote}>
            {searchQuery.trim()
              ? 'No chats match your search.'
              : 'No side chats yet. Start one with the compose button.'}
          </AppText>
        ) : null}
        {filteredChats.length > 0 ? (
          <AppText variant="caption1" color="tertiary" style={styles.emptyNote}>
            Touch and hold a chat to delete it.
          </AppText>
        ) : null}
      </ScrollView>

      {/* Settings */}
      <View style={styles.bottomBar}>
        <ChatRow
          title="Settings"
          icon={Settings02Icon}
          onPress={() => {
            onClose();
            onOpenSettings?.();
          }}
        />
      </View>
    </SafeAreaView>
  );
};

/** A row of the chat list: highlighted while open, and while a finger is on it. */
function ChatRow({
  title,
  icon,
  selected = false,
  onPress,
  onLongPress,
  accessibilityHint,
}: {
  title: string;
  icon?: IconSvgElement;
  selected?: boolean;
  onPress: () => void;
  onLongPress?: () => void;
  accessibilityHint?: string;
}) {
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      delayLongPress={350}
      unstable_pressDelay={30}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={title}
      accessibilityHint={accessibilityHint}
      accessibilityActions={onLongPress ? [{ name: 'delete', label: 'Delete' }] : undefined}
      onAccessibilityAction={(event) => {
        if (event.nativeEvent.actionName === 'delete') onLongPress?.();
      }}
      style={({ pressed }) => [
        styles.chatRow,
        continuous,
        selected ? styles.chatRowSelected : pressed ? styles.chatRowPressed : null,
      ]}>
      {icon ? (
        <HugeiconsIcon
          icon={icon}
          size={20}
          color={selected ? Colors.tint : Colors.label}
          strokeWidth={selected ? 2.2 : 1.9}
        />
      ) : null}
      <AppText
        variant="body"
        numberOfLines={1}
        weight={selected ? '600' : '400'}
        style={[styles.chatRowText, selected && styles.chatRowTextSelected]}>
        {title}
      </AppText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safeContainer: {
    flex: 1,
    backgroundColor: Colors.systemBackground,
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: ScreenMargin,
    paddingTop: 8,
    paddingBottom: 10,
  },
  searchField: {
    flex: 1,
    height: 38,
    borderRadius: 10,
    backgroundColor: Colors.tertiaryFill,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    gap: 6,
  },
  searchInput: {
    ...Typography.body,
    flex: 1,
    color: Colors.label,
    paddingVertical: 0,
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 10,
    paddingBottom: 16,
  },
  sectionHeader: {
    paddingHorizontal: 12,
    paddingTop: 22,
    paddingBottom: 6,
  },
  chatRow: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: Radius.md,
  },
  chatRowSelected: {
    backgroundColor: Colors.tintFill,
  },
  chatRowPressed: {
    backgroundColor: Colors.tertiaryFill,
  },
  chatRowText: {
    flex: 1,
    color: Colors.label,
  },
  chatRowTextSelected: {
    color: Colors.tint,
  },
  emptyNote: {
    paddingHorizontal: 12,
    paddingTop: 10,
  },
  bottomBar: {
    paddingHorizontal: 10,
    paddingTop: 6,
    paddingBottom: 6,
  },
});

export default SidebarDrawer;
