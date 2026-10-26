/**
 * RootLayout Component
 *
 * App-wide navigation shell:
 * - ThemeProvider: light/dark system color scheme synchronization
 * - App state providers: toasts, the agent profile, and the open chat session
 * - Gestures: the gesture-handler root every drag in the app needs (the chat list, sheets)
 * - Stack Navigator: headerless screens pushed with the platform's own transition (on iOS
 *   with the back swipe from anywhere on the screen); a cross-fade with Reduce Motion on
 * - Notifications: foreground banners, and tapping a result opens its chat
 * - StatusBar: dark icons on clean white surface
 * - Launch: the native splash stays up until the saved sign-in is restored, so the first
 *   screen drawn is the right one; a crash anywhere shows a recovery screen instead
 */

import { Colors } from "@/constants/colors";
import { AgentProfileProvider } from "@/context/AgentProfileContext";
import { ChatSessionProvider } from "@/context/ChatSessionContext";
import { ToastProvider } from "@/context/ToastContext";
import { openChatThread } from "@/lib/navigation";
import {
    configureForegroundNotifications,
    useNotificationThreadTaps,
    usePushRegistration,
} from "@/lib/pushNotifications";
import { supabase } from "@/lib/supabase";
import {
    DarkTheme,
    DefaultTheme,
    type ErrorBoundaryProps,
    Stack,
    ThemeProvider,
} from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useCallback, useEffect, useState } from "react";
import { Platform, StyleSheet, useColorScheme, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { useReducedMotion } from "react-native-reanimated";
import type { NativeStackNavigationOptions } from "expo-router/native-stack";
import { AppText } from "@/components/ui/AppText";
import { Button } from "@/components/ui/Button";

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
      <AppText variant="title2" align="center">
        Something went wrong
      </AppText>
      <AppText variant="subheadline" color="secondary" align="center">
        {__DEV__
          ? error.message
          : "Zoop ran into a problem. Try again, and if it keeps happening, close and reopen the app."}
      </AppText>
      <Button title="Try again" onPress={retry} containerStyle={styles.errorButton} />
    </View>
  );
}

// Deeper into the app: the platform's push. Android's default is a fade, so it slides like iOS.
const PUSH: NativeStackNavigationOptions = {
  headerShown: false,
  animation: Platform.OS === "android" ? "slide_from_right" : "default",
  gestureEnabled: true,
  fullScreenGestureEnabled: true,
};

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const reducedMotion = useReducedMotion();
  const push: NativeStackNavigationOptions = reducedMotion
    ? { ...PUSH, animation: "fade" }
    : PUSH;
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
      .catch((error) =>
        console.warn("[notifications] Could not open the chat:", error),
      );
  }, []);
  useNotificationThreadTaps(openThreadFromNotification);
  // Registers this device for whoever signs in, so results reach the right person.
  usePushRegistration();

  return (
    <GestureHandlerRootView style={styles.root}>
    <ThemeProvider value={colorScheme === "dark" ? DarkTheme : DefaultTheme}>
      <ToastProvider>
        <AgentProfileProvider>
          <ChatSessionProvider>
            <Stack screenOptions={{ headerShown: false, animation: "fade" }}>
              <Stack.Screen name="index" options={{ headerShown: false }} />
              <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
              <Stack.Screen name="home" options={{ headerShown: false }} />
              <Stack.Screen
                name="tools"
                options={push}
              />
              <Stack.Screen
                name="notifications"
                options={push}
              />
              <Stack.Screen
                name="help"
                options={push}
              />
              <Stack.Screen
                name="memories/index"
                options={push}
              />
              <Stack.Screen
                name="memories/[id]"
                options={push}
              />
              <Stack.Screen
                name="people/[id]"
                options={push}
              />
              <Stack.Screen
                name="files/index"
                options={push}
              />
              <Stack.Screen
                name="files/[id]"
                options={push}
              />
              <Stack.Screen
                name="import"
                options={push}
              />
              <Stack.Screen
                name="schedules/[id]"
                options={push}
              />
              <Stack.Screen
                name="auth/callback"
                options={{ headerShown: false }}
              />
            </Stack>
            <StatusBar style="dark" />
          </ChatSessionProvider>
        </AgentProfileProvider>
      </ToastProvider>
    </ThemeProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  errorScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
    backgroundColor: Colors.systemBackground,
    gap: 10,
  },
  errorButton: {
    marginTop: 10,
  },
});
