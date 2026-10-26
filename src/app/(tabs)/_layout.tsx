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
 * 3. Native Expo Router Tab Bar, iOS style: each tab a glyph and a label, the selected one
 *    in the tint on an oval pill. It stays put under the keyboard: hiding it would change
 *    the layout mid-animation; the chat input rides above it. Pressing a tab shows the same
 *    oval pill, not Android's circular ripple. Switching tabs never animates.
 * 4. The chat list (SidebarDrawer) slides in from the left: from the header button, or by
 *    swiping right anywhere on Chat, as in ChatGPT
 * 5. Modals: SettingsMenuModal, EditAgentModal
 *
 * Signed-in only: without a session it sends the user to the sign-in screen.
 */

import React, { createContext, useContext, useEffect, useState } from 'react';
import { BackHandler, StyleSheet, Text, View, useWindowDimensions, type ColorValue } from 'react-native';
import { Tabs, usePathname, useRouter } from 'expo-router';
import { PlatformPressable } from 'expo-router/react-navigation';
import type { BottomTabBarButtonProps } from 'expo-router/tabs';
import { Drawer } from 'react-native-drawer-layout';
import type { LegacyPanGesture } from 'react-native-gesture-handler';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import {
  Comment01Icon,
  File01Icon,
  Idea01Icon,
  CheckmarkSquare02Icon,
  Settings02Icon,
} from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { Hairline } from '@/constants/theme';
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
const TAB_BAR_TOP_PADDING = 6;
const TAB_BAR_ITEMS_HEIGHT = 50;
const TAB_BAR_MIN_BOTTOM_PADDING = 8;
// The oval pill behind a tab's glyph: on the selected tab, and on any tab while pressed.
const TAB_PILL_WIDTH = 56;
const TAB_PILL_HEIGHT = 30;

// The chat list covers most of the screen; the chat stays in view at its edge.
const CHAT_LIST_WIDTH = '85%';
// How far a swipe moves right before it opens the chat list. Past the platform's touch
// slop, so the horizontal lists in replies (code, tables) and the composer's file chips
// scroll first, and a mostly vertical move still scrolls the messages.
const SWIPE_OPEN_OFFSET = 12;

/**
 * While the chat list is closed, only a rightward swipe may start opening it. The drawer
 * hands over gesture-handler's classic `Gesture.Pan()` builder, but its types, written for
 * gesture-handler 2, name what version 3 calls the hooks API's `PanGesture`; hence the cast.
 */
function openOnRightSwipe<Gesture>(gesture: Gesture): Gesture {
  (gesture as unknown as LegacyPanGesture)
    .activeOffsetX([-Number.MAX_SAFE_INTEGER, SWIPE_OPEN_OFFSET])
    .failOffsetY([-SWIPE_OPEN_OFFSET, SWIPE_OPEN_OFFSET]);
  return gesture;
}

// Whether the tab around a glyph is being pressed, for its pill.
const TabPressedContext = createContext(false);

/**
 * A tab whose press feedback is the selected pill's shape. The tab bar's default button
 * draws Android's borderless ripple: a circle wider than the pill and spilling past it.
 */
function TabBarButton({
  children,
  style,
  onPressIn,
  onPressOut,
  ...props
}: BottomTabBarButtonProps) {
  const [isPressed, setIsPressed] = useState(false);
  return (
    <PlatformPressable
      {...props}
      style={[style, styles.tabButton]}
      // Keeps the native ripple invisible; the pill is the feedback instead.
      pressColor="transparent"
      pressOpacity={1}
      onPressIn={(event) => {
        setIsPressed(true);
        onPressIn?.(event);
      }}
      onPressOut={(event) => {
        setIsPressed(false);
        onPressOut?.(event);
      }}>
      <TabPressedContext.Provider value={isPressed}>{children}</TabPressedContext.Provider>
    </PlatformPressable>
  );
}

/** A tab's glyph on its oval pill, and its label. */
function TabIcon({
  icon,
  label,
  focused,
  color,
}: {
  icon: IconSvgElement;
  label: string;
  focused: boolean;
  color: ColorValue;
}) {
  const pressed = useContext(TabPressedContext);
  return (
    <View style={styles.tabItem}>
      <View
        style={[
          styles.tabPill,
          focused ? styles.tabPillSelected : pressed ? styles.tabPillPressed : styles.tabPillIdle,
        ]}>
        <HugeiconsIcon icon={icon} size={22} color={color} strokeWidth={focused ? 2.2 : 1.9} />
      </View>
      <Text style={[styles.tabLabel, { color }, focused && styles.tabLabelSelected]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

const TABS: { name: string; label: string; icon: IconSvgElement }[] = [
  { name: 'chat', label: 'Chat', icon: Comment01Icon },
  { name: 'feed', label: 'Today', icon: File01Icon },
  { name: 'ideas', label: 'Ideas', icon: Idea01Icon },
  { name: 'tasks', label: 'Tasks', icon: CheckmarkSquare02Icon },
  { name: 'settings', label: 'Settings', icon: Settings02Icon },
];

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

  // A swipe can start anywhere across the screen, not only at its edge (where Android's
  // own back gesture lives).
  const { width: windowWidth } = useWindowDimensions();

  // Modals state
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isSettingsMenuOpen, setIsSettingsMenuOpen] = useState(false);
  const [isEditAgentOpen, setIsEditAgentOpen] = useState(false);

  // Android's back button closes an open chat list before it leaves the screen.
  useEffect(() => {
    if (!isSidebarOpen) return;
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      setIsSidebarOpen(false);
      return true;
    });
    return () => subscription.remove();
  }, [isSidebarOpen]);

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
    <Drawer
      open={isSidebarOpen}
      onOpen={() => setIsSidebarOpen(true)}
      onClose={() => setIsSidebarOpen(false)}
      drawerType="slide"
      drawerStyle={styles.chatList}
      overlayStyle={styles.chatListOverlay}
      // Swiping opens it on Chat only; once open, a swipe left closes it from any tab.
      swipeEnabled={isChatOpen || isSidebarOpen}
      swipeEdgeWidth={windowWidth}
      configureGestureHandler={isSidebarOpen ? undefined : openOnRightSwipe}
      renderDrawerContent={() => (
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
      )}>
      <SafeAreaView
        style={[styles.safeArea, !isChatOpen && styles.safeAreaGrouped]}
        edges={['top', 'left', 'right']}>
        {/* 1. Persistent App Header */}
        <AppHeader
          background={isChatOpen ? 'plain' : 'grouped'}
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
              tabBarActiveTintColor: Colors.tint,
              tabBarInactiveTintColor: Colors.tabInactive,
              animation: 'none',
              tabBarStyle: [styles.tabBar, tabBarSize],
              tabBarItemStyle: styles.tabBarItem,
              tabBarButton: (props) => <TabBarButton {...props} />,
            }}>
            <Tabs.Screen
              name="index"
              options={{
                href: null,
              }}
            />
            {TABS.map((tab) => (
              <Tabs.Screen
                key={tab.name}
                name={tab.name}
                options={{
                  title: tab.label,
                  tabBarIcon: ({ focused, color }) => (
                    <TabIcon icon={tab.icon} label={tab.label} focused={focused} color={color} />
                  ),
                }}
              />
            ))}
          </Tabs>
        </View>

        {/* 3. Right 3-Dots Action Sheet */}
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

        {/* 4. Edit Mascot Avatar & Name Modal */}
        <EditAgentModal visible={isEditAgentOpen} onClose={() => setIsEditAgentOpen(false)} />
      </SafeAreaView>
    </Drawer>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  // The tabs other than Chat are grouped screens; the status bar area matches them.
  safeAreaGrouped: {
    backgroundColor: Colors.groupedBackground,
  },
  contentContainer: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  tabBar: {
    backgroundColor: Colors.barBackground,
    borderTopWidth: Hairline,
    borderTopColor: Colors.separator,
    paddingTop: TAB_BAR_TOP_PADDING,
    paddingHorizontal: 8,
    elevation: 0,
    shadowOpacity: 0,
  },
  tabBarItem: {
    alignItems: 'center',
    justifyContent: 'center',
    height: TAB_BAR_ITEMS_HEIGHT,
  },
  // The whole cell is the touch target, with the glyph and label centred in it.
  tabButton: {
    alignSelf: 'stretch',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 0,
  },
  tabItem: {
    alignItems: 'center',
    gap: 2,
    width: 72,
  },
  tabPill: {
    width: TAB_PILL_WIDTH,
    height: TAB_PILL_HEIGHT,
    borderRadius: TAB_PILL_HEIGHT / 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabPillSelected: {
    backgroundColor: Colors.tabActiveBg,
  },
  tabPillPressed: {
    backgroundColor: Colors.tertiaryFill,
  },
  tabPillIdle: {
    backgroundColor: 'transparent',
  },
  tabLabel: {
    fontSize: 10.5,
    lineHeight: 13,
    fontWeight: '500',
    letterSpacing: 0.1,
  },
  tabLabelSelected: {
    fontWeight: '600',
  },
  chatList: {
    width: CHAT_LIST_WIDTH,
    backgroundColor: Colors.white,
  },
  chatListOverlay: {
    backgroundColor: Colors.scrim,
  },
});
