/**
 * RootLayout Component
 *
 * App-wide navigation shell:
 * - ThemeProvider: light/dark system color scheme synchronization
 * - App state providers: toasts, the agent profile, and the open chat session
 * - Stack Navigator: headerless screen transitions
 * - Notifications: foreground banners, and tapping a result opens its chat
 * - StatusBar: dark icons on clean white surface
 * - Launch: the native splash stays up until the saved sign-in is restored, so the first
 *   screen drawn is the right one; a crash anywhere shows a recovery screen instead
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  DarkTheme,
  DefaultTheme,
  type ErrorBoundaryProps,
  Stack,
  ThemeProvider,
} from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, Text, TouchableOpacity, useColorScheme, View } from 'react-native';
import { Colors } from '@/constants/colors';
import { AgentProfileProvider } from '@/context/AgentProfileContext';
import { ChatSessionProvider } from '@/context/ChatSessionContext';
import { ToastProvider } from '@/context/ToastContext';
import { openChatThread } from '@/lib/navigation';
import {
  configureForegroundNotifications,
  useNotificationThreadTaps,
  usePushRegistration,
} from '@/lib/pushNotifications';
import { supabase } from '@/lib/supabase';

configureForegroundNotifications();

// Kept up until the saved session is known; see RootLayout.
SplashScreen.preventAutoHideAsync().catch(() => undefined);
SplashScreen.setOptions({ duration: 250, fade: true });

// The splash never stays longer than this, even if restoring the session hangs.
const MAX_SPLASH_MS = 3000;

/** A crash in any screen lands here instead of a blank app. */
export function ErrorBoundary({ error, retry }: ErrorBoundaryProps) {
  useEffect(() => {
    SplashScreen.hideAsync().catch(() => undefined);
  }, []);
  return (
    <View style={styles.errorScreen}>
      <Text style={styles.errorTitle}>Something went wrong</Text>
      <Text style={styles.errorText}>
        {__DEV__
          ? error.message
          : 'Zoop ran into a problem. Try again, and if it keeps happening, close and reopen the app.'}
      </Text>
      <TouchableOpacity
        style={styles.errorButton}
        onPress={retry}
        activeOpacity={0.8}
        accessibilityRole="button">
        <Text style={styles.errorButtonText}>Try again</Text>
      </TouchableOpacity>
    </View>
  );
}

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const [isReady, setIsReady] = useState(false);

  // Restoring the session reads local storage; once it is known, the first screen can
  // decide where to go without flashing the sign-in screen.
  useEffect(() => {
    const ready = () => setIsReady(true);
    supabase.auth.getSession().then(ready, ready);
    const timer = setTimeout(ready, MAX_SPLASH_MS);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (isReady) SplashScreen.hideAsync().catch(() => undefined);
  }, [isReady]);

  // A scheduled-task notification opens the chat its result was posted to. Waiting for the
  // session also lets the sign-in screen finish its own redirect on a cold start first.
  const openThreadFromNotification = useCallback((threadId: string) => {
    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (data.session) {
          openChatThread(threadId);
        }
      })
      .catch((error) => console.warn('[notifications] Could not open the chat:', error));
  }, []);
  useNotificationThreadTaps(openThreadFromNotification);
  // Registers this device for whoever signs in, so results reach the right person.
  usePushRegistration();

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <ToastProvider>
        <AgentProfileProvider>
          <ChatSessionProvider>
            <Stack screenOptions={{ headerShown: false, animation: 'fade' }}>
              <Stack.Screen name="index" options={{ headerShown: false }} />
              <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
              <Stack.Screen name="home" options={{ headerShown: false }} />
              <Stack.Screen
                name="tools"
                options={{ headerShown: false, animation: 'slide_from_right' }}
              />
              <Stack.Screen
                name="notifications"
                options={{ headerShown: false, animation: 'slide_from_right' }}
              />
              <Stack.Screen
                name="help"
                options={{ headerShown: false, animation: 'slide_from_right' }}
              />
              <Stack.Screen
                name="memories/index"
                options={{ headerShown: false, animation: 'slide_from_right' }}
              />
              <Stack.Screen
                name="memories/[id]"
                options={{ headerShown: false, animation: 'slide_from_right' }}
              />
              <Stack.Screen
                name="people/[id]"
                options={{ headerShown: false, animation: 'slide_from_right' }}
              />
              <Stack.Screen
                name="import"
                options={{ headerShown: false, animation: 'slide_from_right' }}
              />
              <Stack.Screen
                name="schedules/[id]"
                options={{ headerShown: false, animation: 'slide_from_right' }}
              />
              <Stack.Screen name="auth/callback" options={{ headerShown: false }} />
            </Stack>
            <StatusBar style="dark" />
          </ChatSessionProvider>
        </AgentProfileProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}

const styles = StyleSheet.create({
  errorScreen: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    backgroundColor: Colors.white,
    gap: 12,
  },
  errorTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  errorText: {
    fontSize: 14.5,
    lineHeight: 21,
    color: Colors.textSecondary,
    textAlign: 'center',
  },
  errorButton: {
    marginTop: 8,
    paddingHorizontal: 22,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  errorButtonText: {
    fontSize: 14.5,
    fontWeight: '700',
    color: Colors.white,
  },
});
