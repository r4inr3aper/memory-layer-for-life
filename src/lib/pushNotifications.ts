/**
 * Push Notifications
 *
 * The backend sends a push notification when a scheduled task finishes, to every Expo push
 * token the user registered. Its `data.thread_id` is the chat the result was posted to.
 *
 * Registration follows the signed-in user. After every sign-in, and at launch with a saved
 * session, this device's token is registered for that user: silently when permission was
 * granted before, and with one permission prompt when the user has notifications on. The
 * backend gives a token to whoever registered it last, so this also stops a shared phone from
 * receiving the previous user's results. Signing out unregisters the token first.
 *
 * `expo-notifications` does not work in Expo Go: Android dropped push notifications there
 * in SDK 53, and Expo Go's native module does not match the package ("Cannot find native
 * module 'ExpoTopicSubscriptionModule'"), so evaluating the package throws or leaves its
 * functions undefined. Imported at the top of a module, that stops the app from starting.
 * So the package is loaded only through `loadNotifications()`, never in Expo Go, and every
 * call into it is guarded: notifications must never break the app.
 */

import { getMe, registerPushToken, unregisterPushToken } from "@/lib/api/me";
import { importNotifications } from "@/lib/notificationsModule";
import { supabase } from "@/lib/supabase";
import { syncTimezone } from "@/lib/timezoneSync";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { isRunningInExpoGo } from "expo";
import Constants from "expo-constants";
import * as Device from "expo-device";
import type * as ExpoNotifications from "expo-notifications";
import { useEffect, useRef } from "react";
import { Platform } from "react-native";

const ANDROID_CHANNEL_ID = "default";
// The token this device registered last, so signing out can unregister it.
const TOKEN_STORAGE_KEY = "zoop.pushToken";
const UNREGISTER_TIMEOUT_MS = 5000;

type NotificationsModule = typeof ExpoNotifications;

let loadedModule: Promise<NotificationsModule | null> | null = null;

/**
 * Whether the app runs in Expo Go. Its own native module says so; `executionEnvironment`
 * cannot, since it reads the same in Expo Go and in a development build (where push works).
 */
function isExpoGo(): boolean {
  return isRunningInExpoGo();
}

/** Loads `expo-notifications`, or resolves to `null` where it cannot run. */
function loadNotifications(): Promise<NotificationsModule | null> {
  if (Platform.OS === "web" || isExpoGo()) {
    return Promise.resolve(null);
  }
  loadedModule ??= importNotifications()
    .then((module) => {
      // A package whose native side is missing can load with its functions undefined.
      if (typeof module.setNotificationHandler !== "function") {
        console.warn("[notifications] Not available in this build.");
        return null;
      }
      return module;
    })
    .catch((error: unknown) => {
      console.warn("[notifications] Not available in this build:", error);
      return null;
    });
  return loadedModule;
}

export const PUSH_NEEDS_BUILD_MESSAGE =
  "Push notifications need an installed build of the app and an Expo project (run `eas init`). " +
  "Your choice is saved and takes effect there.";

export type PushRegistrationResult =
  | { status: "registered"; token: string }
  | { status: "unavailable"; reason: string }
  | { status: "denied" };

function getProjectId(): string | null {
  const projectId: unknown =
    Constants.expoConfig?.extra?.eas?.projectId ??
    Constants.easConfig?.projectId;
  return typeof projectId === "string" && projectId ? projectId : null;
}

/** Why this app cannot receive push notifications, or `null` when it can. */
export function getPushUnavailableReason(): string | null {
  if (Platform.OS === "web") {
    return "Push notifications are available in the iOS and Android app.";
  }
  if (isExpoGo() || !getProjectId()) {
    return PUSH_NEEDS_BUILD_MESSAGE;
  }
  if (!Device.isDevice) {
    return "Push notifications need a physical device, not a simulator.";
  }
  return null;
}

/** The module and project when this build can register for push, else `null`. */
async function pushSetup(): Promise<{
  Notifications: NotificationsModule;
  projectId: string;
} | null> {
  const projectId = getProjectId();
  if (getPushUnavailableReason() || !projectId) return null;
  const Notifications = await loadNotifications();
  return Notifications ? { Notifications, projectId } : null;
}

/** Android 13+ shows the permission prompt, and shows notifications, only once a channel exists. */
async function ensureChannel(
  Notifications: NotificationsModule,
): Promise<void> {
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync(ANDROID_CHANNEL_ID, {
      name: "Scheduled task results",
      importance: Notifications.AndroidImportance.DEFAULT,
    });
  }
}

async function registerDevice(
  Notifications: NotificationsModule,
  projectId: string,
): Promise<string> {
  await ensureChannel(Notifications);
  const { data: token } = await Notifications.getExpoPushTokenAsync({
    projectId,
  });
  await registerPushToken({
    token,
    platform: Platform.OS === "ios" ? "ios" : "android",
  });
  await rememberToken(token);
  return token;
}

/**
 * Asks for notification permission and registers this device's Expo push token with the
 * backend. Throws when the token cannot be fetched or registered.
 */
export async function registerForPushNotifications(): Promise<PushRegistrationResult> {
  const setup = await pushSetup();
  if (!setup) {
    return {
      status: "unavailable",
      reason: getPushUnavailableReason() ?? PUSH_NEEDS_BUILD_MESSAGE,
    };
  }
  const { Notifications, projectId } = setup;

  await ensureChannel(Notifications);
  let { granted } = await Notifications.getPermissionsAsync();
  if (!granted) {
    ({ granted } = await Notifications.requestPermissionsAsync());
  }
  if (!granted) {
    return { status: "denied" };
  }
  return {
    status: "registered",
    token: await registerDevice(Notifications, projectId),
  };
}

/**
 * Registers this device for the signed-in user. Asks for permission only when it was never
 * asked and the user has notifications on. Never throws: notifications must not break sign-in.
 */
export async function syncPushRegistration(): Promise<void> {
  const setup = await pushSetup();
  if (!setup) return;
  const { Notifications, projectId } = setup;
  try {
    let { granted, canAskAgain } = await Notifications.getPermissionsAsync();
    if (!granted && canAskAgain) {
      const me = await getMe();
      if (!me.notifications_enabled) return;
      await ensureChannel(Notifications);
      ({ granted } = await Notifications.requestPermissionsAsync());
    }
    // Registered even when this user turned notifications off (the backend then sends
    // nothing): it takes the token away from whoever used this phone before.
    if (granted) {
      await registerDevice(Notifications, projectId);
    }
  } catch (error) {
    console.warn("[notifications] Could not register this device:", error);
  }
}

/**
 * Unregisters the token this device registered, while the session can still call the API,
 * so the next person using the phone does not get this user's results. Best effort: a
 * failure is logged, and the next sign-in on this phone takes the token over anyway.
 */
export async function releasePushRegistration(): Promise<void> {
  const token = await rememberedToken();
  if (!token) return;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UNREGISTER_TIMEOUT_MS);
  try {
    await unregisterPushToken(token, controller.signal);
  } catch (error) {
    console.warn("[notifications] Could not unregister this device:", error);
  } finally {
    clearTimeout(timer);
    await rememberToken(null);
  }
}

/** Forgets the token without telling the backend, for when the account itself is deleted. */
export function forgetPushRegistration(): Promise<void> {
  return rememberToken(null);
}

async function rememberToken(token: string | null): Promise<void> {
  try {
    if (token) {
      await AsyncStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      await AsyncStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch (error) {
    console.warn("[notifications] Could not save the push token:", error);
  }
}

async function rememberedToken(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * Registers this device (its push token and timezone) each time a user signs in, including
 * a saved session at launch.
 */
export function usePushRegistration() {
  useEffect(() => {
    let userId: string | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      const nextUserId = session?.user.id ?? null;
      if (nextUserId === userId) return;
      userId = nextUserId;
      if (timer) clearTimeout(timer);
      if (nextUserId) {
        // Supabase asks not to call its methods (the API client reads the session) from
        // inside this callback, so registration starts right after it returns.
        timer = setTimeout(() => {
          void syncPushRegistration();
          void syncTimezone();
        }, 0);
      }
    });

    return () => {
      subscription.unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, []);
}

/** Shows notifications that arrive while the app is open, as banners. Native only. */
export function configureForegroundNotifications() {
  void loadNotifications().then((Notifications) => {
    try {
      Notifications?.setNotificationHandler({
        handleNotification: async () => ({
          shouldShowBanner: true,
          shouldShowList: true,
          // Android shows no heads-up banner without sound.
          shouldPlaySound: true,
          shouldSetBadge: false,
        }),
      });
    } catch (error) {
      console.warn(
        "[notifications] Could not set the foreground handler:",
        error,
      );
    }
  });
}

/**
 * Calls `onOpenThread` when the user taps a notification that carries a `thread_id`,
 * including the tap that launched the app.
 */
export function useNotificationThreadTaps(
  onOpenThread: (threadId: string) => void,
) {
  const onOpenThreadRef = useRef(onOpenThread);
  useEffect(() => {
    onOpenThreadRef.current = onOpenThread;
  }, [onOpenThread]);

  useEffect(() => {
    let cancelled = false;
    let subscription: { remove: () => void } | null = null;

    const handleResponse = (
      response: ExpoNotifications.NotificationResponse,
    ) => {
      const threadId: unknown =
        response.notification.request.content.data?.thread_id;
      if (typeof threadId === "string" && threadId) {
        onOpenThreadRef.current(threadId);
      }
    };

    void loadNotifications().then((Notifications) => {
      if (!Notifications || cancelled) {
        return;
      }
      try {
        const launchResponse = Notifications.getLastNotificationResponse();
        if (launchResponse) {
          // Handle it once: the root layout can mount again within the same launch.
          Notifications.clearLastNotificationResponse();
          handleResponse(launchResponse);
        }
        subscription =
          Notifications.addNotificationResponseReceivedListener(handleResponse);
      } catch (error) {
        console.warn(
          "[notifications] Could not listen for notification taps:",
          error,
        );
      }
    });

    return () => {
      cancelled = true;
      subscription?.remove();
    };
  }, []);
}
