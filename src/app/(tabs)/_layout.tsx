/**
 * TabLayout Component ('/(tabs)/_layout.tsx')
 *
 * Master Tab Layout containing:
 * 1. AppHeader: 3D mascot avatar, agent name capsule pill, sidebar drawer and 3-dots actions
 * 2. Expo Router Tabs viewport for 5 routes:
 *    - /chat
 *    - /feed
 *    - /ideas
 *    - /tasks
 *    - /settings
 * 3. Native Expo Router Tab Bar with active pill capsule. It stays put under the keyboard:
 *    hiding it would change the layout mid-animation; the chat input rides above it.
 * 4. Modals: SidebarDrawer, SettingsMenuModal, EditAgentModal
 *
 * Signed-in only: without a session it sends the user to the sign-in screen.
 */

import React, { useState } from 'react';
import { View, StyleSheet } from 'react-native';
import { Tabs, usePathname, useRouter } from 'expo-router';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  Comment01Icon,
  File01Icon,
  Idea01Icon,
  CheckmarkSquare02Icon,
  Settings02Icon,
} from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { AppHeader, SidebarDrawer, SettingsMenuModal, EditAgentModal } from '@/components/common';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { useChatSession } from '@/context/ChatSessionContext';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { getErrorMessage } from '@/lib/api/client';
import { clearMessages, deleteThread, ensureMainThread } from '@/lib/api/threads';
import { confirmAsync } from '@/lib/dialogs';
import { openChatThread } from '@/lib/navigation';
import { buildTranscript, listAllMessages, shareTranscript } from '@/lib/transcript';

const MAIN_CHAT_DELETE_MESSAGE = "The main chat can't be deleted — use Clear instead.";
// Deleting messages never deletes the memories made from them (the user's choice).
const MEMORIES_KEPT = ' Memories Cooper saved from it are kept; manage them in Memories.';

// The tab bar's own height, above whatever the system draws over the bottom of the screen.
const TAB_BAR_TOP_PADDING = 8;
const TAB_BAR_ITEMS_HEIGHT = 52;
const TAB_BAR_MIN_BOTTOM_PADDING = 10;

export default function TabLayout() {
  const router = useRouter();
  const hasSession = useRequireSession();
  const { profile } = useAgentProfile();
  const { activeThread, requestReload } = useChatSession();
  // The header is shared by every tab, but its chat actions act on the chat tab's thread,
  // which stays loaded while other tabs are shown. Offer them only while Chat is open.
  const isChatOpen = usePathname() === '/chat';
  const openChat = isChatOpen ? activeThread : null;
  // The app is drawn edge-to-edge: Android's navigation bar and the iPhone home indicator
  // sit over its bottom edge. The tab bar reaches under them and keeps its icons above.
  const insets = useSafeAreaInsets();
  const tabBarBottomPadding = Math.max(insets.bottom, TAB_BAR_MIN_BOTTOM_PADDING);
  const tabBarSize = {
    height: TAB_BAR_TOP_PADDING + TAB_BAR_ITEMS_HEIGHT + tabBarBottomPadding,
    paddingBottom: tabBarBottomPadding,
  };

  // Modals state
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isSettingsMenuOpen, setIsSettingsMenuOpen] = useState(false);
  const [isEditAgentOpen, setIsEditAgentOpen] = useState(false);

  const handleClearChat = async () => {
    const thread = openChat;
    if (!thread) {
      showToast('Open a chat first.');
      return;
    }

    const confirmed = await confirmAsync({
      title: 'Clear this chat?',
      message: "Every message in this chat will be deleted. This can't be undone." + MEMORIES_KEPT,
      confirmText: 'Clear',
      destructive: true,
    });
    if (!confirmed) return;

    try {
      await clearMessages(thread.id);
      requestReload();
      showToast('Chat cleared');
    } catch (error) {
      console.error('Failed to clear chat:', error);
      showToast(getErrorMessage(error, 'Could not clear the chat'));
    }
  };

  const handleDeleteChat = async () => {
    const thread = openChat;
    if (!thread) {
      showToast('Open a chat first.');
      return;
    }
    if (thread.kind === 'main') {
      showToast(MAIN_CHAT_DELETE_MESSAGE, 3000);
      return;
    }

    const confirmed = await confirmAsync({
      title: 'Delete this chat?',
      message:
        "This side chat and all of its messages will be deleted. This can't be undone." +
        MEMORIES_KEPT,
      confirmText: 'Delete',
      destructive: true,
    });
    if (!confirmed) return;

    try {
      await deleteThread(thread.id);
    } catch (error) {
      console.error('Failed to delete chat:', error);
      showToast(getErrorMessage(error, 'Could not delete the chat'));
      return;
    }

    showToast('Chat deleted');
    try {
      const mainThread = await ensureMainThread();
      openChatThread(mainThread.id);
    } catch (error) {
      console.error('Failed to open the main chat:', error);
      showToast(getErrorMessage(error, 'Could not open the main chat'));
    }
  };

  const handleShareChat = async () => {
    const thread = openChat;
    if (!thread) {
      showToast('Open a chat first.');
      return;
    }

    try {
      const transcript = buildTranscript(await listAllMessages(thread.id), profile.name);
      if (!transcript) {
        showToast("There's nothing to share yet.");
        return;
      }
      const outcome = await shareTranscript(transcript, `Chat with ${profile.name}`);
      if (outcome === 'copied') {
        showToast('Transcript copied to the clipboard');
      }
    } catch (error) {
      console.error('Failed to share chat:', error);
      showToast(getErrorMessage(error, 'Could not share the chat'));
    }
  };

  if (!hasSession) {
    // Nothing that calls the API renders before the session is confirmed.
    return <View style={styles.safeArea} />;
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      {/* 1. Persistent App Header */}
      <AppHeader
        onOpenSidebar={() => setIsSidebarOpen(true)}
        onOpenSettings={() => setIsSettingsMenuOpen(true)}
        onMascotPress={() => setIsEditAgentOpen(true)}
      />

      {/* 2. Expo Router Tabs Viewport */}
      <View style={styles.contentContainer}>
        <Tabs
          screenOptions={{
            headerShown: false,
            tabBarShowLabel: false,
            tabBarStyle: [styles.tabBar, tabBarSize],
            tabBarItemStyle: styles.tabBarItem,
          }}>
          <Tabs.Screen
            name="index"
            options={{
              href: null,
            }}
          />
          <Tabs.Screen
            name="chat"
            options={{
              title: 'Chat',
              tabBarIcon: ({ focused }) => (
                <View style={[styles.iconPill, focused && styles.activeIconPill]}>
                  <HugeiconsIcon
                    icon={Comment01Icon}
                    size={23}
                    color={Colors.iconDark}
                    strokeWidth={2}
                  />
                </View>
              ),
            }}
          />
          <Tabs.Screen
            name="feed"
            options={{
              title: 'Feed',
              tabBarIcon: ({ focused }) => (
                <View style={[styles.iconPill, focused && styles.activeIconPill]}>
                  <HugeiconsIcon
                    icon={File01Icon}
                    size={23}
                    color={Colors.iconDark}
                    strokeWidth={2}
                  />
                </View>
              ),
            }}
          />
          <Tabs.Screen
            name="ideas"
            options={{
              title: 'Ideas',
              tabBarIcon: ({ focused }) => (
                <View style={[styles.iconPill, focused && styles.activeIconPill]}>
                  <HugeiconsIcon
                    icon={Idea01Icon}
                    size={23}
                    color={Colors.iconDark}
                    strokeWidth={2}
                  />
                </View>
              ),
            }}
          />
          <Tabs.Screen
            name="tasks"
            options={{
              title: 'Task / Goal',
              tabBarIcon: ({ focused }) => (
                <View style={[styles.iconPill, focused && styles.activeIconPill]}>
                  <HugeiconsIcon
                    icon={CheckmarkSquare02Icon}
                    size={23}
                    color={Colors.iconDark}
                    strokeWidth={2}
                  />
                </View>
              ),
            }}
          />
          <Tabs.Screen
            name="settings"
            options={{
              title: 'Settings',
              tabBarIcon: ({ focused }) => (
                <View style={[styles.iconPill, focused && styles.activeIconPill]}>
                  <HugeiconsIcon
                    icon={Settings02Icon}
                    size={23}
                    color={Colors.iconDark}
                    strokeWidth={2}
                  />
                </View>
              ),
            }}
          />
        </Tabs>
      </View>

      {/* 3. Left Sliding Sidebar Drawer */}
      <SidebarDrawer
        visible={isSidebarOpen}
        agentName={profile.name}
        onClose={() => setIsSidebarOpen(false)}
        onSelectChat={() => {
          setIsSidebarOpen(false);
          router.replace('/(tabs)/chat');
        }}
        onNewChat={() => {
          setIsSidebarOpen(false);
          router.replace('/(tabs)/chat');
        }}
        onOpenSettings={() => {
          setIsSidebarOpen(false);
          router.replace('/(tabs)/settings');
        }}
        onClearSideChats={() => {
          showToast('Side chat deleted');
        }}
      />

      {/* 4. Right 3-Dots Action Sheet */}
      <SettingsMenuModal
        visible={isSettingsMenuOpen}
        showChatActions={openChat !== null}
        canDeleteChat={openChat?.kind === 'side'}
        onClose={() => setIsSettingsMenuOpen(false)}
        onEditAvatar={() => setIsEditAgentOpen(true)}
        onRename={() => setIsEditAgentOpen(true)}
        onClearChat={handleClearChat}
        onDeleteChat={handleDeleteChat}
        onShareChat={handleShareChat}
      />

      {/* 5. Edit Mascot Avatar & Name Modal */}
      <EditAgentModal visible={isEditAgentOpen} onClose={() => setIsEditAgentOpen(false)} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  contentContainer: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  tabBar: {
    backgroundColor: Colors.white,
    borderTopWidth: 1,
    borderTopColor: '#F0F0F2',
    paddingTop: TAB_BAR_TOP_PADDING,
    paddingHorizontal: 12,
    elevation: 0,
    shadowOpacity: 0,
  },
  tabBarItem: {
    alignItems: 'center',
    justifyContent: 'center',
    height: 48,
  },
  iconPill: {
    width: 58,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
  },
  activeIconPill: {
    backgroundColor: Colors.tabActiveBg, // Soft #E6E8EA capsule
  },
});
