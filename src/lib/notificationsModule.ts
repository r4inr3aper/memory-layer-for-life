/**
 * The one place `expo-notifications` is imported, lazily. Evaluating the package where its
 * native side is missing (Expo Go) throws, so nothing imports it at module level; see
 * `pushNotifications.ts` for when this is called. Kept in its own module so tests can
 * replace it: Jest cannot run a dynamic `import()` without experimental flags.
 */

import type * as ExpoNotifications from 'expo-notifications';

export function importNotifications(): Promise<typeof ExpoNotifications> {
  return import('expo-notifications');
}
