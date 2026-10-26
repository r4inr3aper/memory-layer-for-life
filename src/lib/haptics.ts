/**
 * Haptics, used sparingly so they stay meaningful: a selection tick when a value steps (a
 * segmented control, a switch), a light tap when something commits or snaps home, and a
 * notification when an action the user waited on succeeds or fails. One per action, fired
 * in the same frame as the visual change, and never the only feedback (many people turn
 * haptics off, and most Android phones are silent).
 *
 * expo-haptics is a native module: a build that predates it has no such module, and
 * importing it there would crash at startup. It is loaded once, guarded, and every call
 * is a no-op without it (and on the web).
 */

import { Platform } from 'react-native';

type HapticsModule = typeof import('expo-haptics');

let loaded: HapticsModule | null | undefined;

function haptics(): HapticsModule | null {
  if (loaded === undefined) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      loaded = Platform.OS === 'web' ? null : (require('expo-haptics') as HapticsModule);
    } catch {
      loaded = null;
    }
  }
  return loaded;
}

function run(play: (module: HapticsModule) => Promise<void>): void {
  const module = haptics();
  if (module) {
    play(module).catch(() => undefined);
  }
}

export const haptic = {
  /** A value stepped: a segment, a switch, a picker detent. */
  selection: () => run((h) => h.selectionAsync()),
  /** Something committed or snapped home: a sheet settling, a row action. */
  light: () => run((h) => h.impactAsync(h.ImpactFeedbackStyle.Light)),
  /** A heavier commit: a destructive action confirmed. */
  medium: () => run((h) => h.impactAsync(h.ImpactFeedbackStyle.Medium)),
  success: () => run((h) => h.notificationAsync(h.NotificationFeedbackType.Success)),
  warning: () => run((h) => h.notificationAsync(h.NotificationFeedbackType.Warning)),
  error: () => run((h) => h.notificationAsync(h.NotificationFeedbackType.Error)),
};
