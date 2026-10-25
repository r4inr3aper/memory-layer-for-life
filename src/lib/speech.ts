/**
 * Speech Recognition Availability
 *
 * `expo-speech-recognition` is a native module that Expo Go does not include, and the
 * package throws as soon as it is evaluated when the module is missing. So this checks
 * for the native module first and loads the package only when it is there.
 */

import { requireOptionalNativeModule } from 'expo-modules-core';
import { Platform } from 'react-native';

export type SpeechRecognitionModule =
  (typeof import('expo-speech-recognition'))['ExpoSpeechRecognitionModule'];

export const VOICE_NEEDS_APP_MESSAGE =
  "Voice input needs the installed app. Use your keyboard's microphone for now.";

export const VOICE_UNSUPPORTED_BROWSER_MESSAGE =
  "Voice input isn't supported in this browser. Try Chrome or Safari.";

/** Whether speech recognition can run here, without loading the package. */
export function isSpeechRecognitionAvailable(): boolean {
  if (Platform.OS === 'web') {
    return (
      typeof window !== 'undefined' &&
      ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)
    );
  }
  return requireOptionalNativeModule('ExpoSpeechRecognition') != null;
}

/** The message to show when `isSpeechRecognitionAvailable()` is false. */
export function speechUnavailableMessage(): string {
  return Platform.OS === 'web' ? VOICE_UNSUPPORTED_BROWSER_MESSAGE : VOICE_NEEDS_APP_MESSAGE;
}

let loadedModule: Promise<SpeechRecognitionModule | null> | null = null;

/** Loads the speech recognition module, or resolves to `null` where it cannot run. */
export function loadSpeechRecognition(): Promise<SpeechRecognitionModule | null> {
  if (!isSpeechRecognitionAvailable()) {
    return Promise.resolve(null);
  }
  // A deferred import: the package is evaluated only after the check above passed.
  loadedModule ??= import('expo-speech-recognition')
    .then((speech) => speech.ExpoSpeechRecognitionModule)
    .catch((error: unknown) => {
      console.warn('[speech] Could not load speech recognition:', error);
      loadedModule = null;
      return null;
    });
  return loadedModule;
}

/** The device's language as a BCP-47 tag such as "en-US". */
export function getSpeechLocale(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().locale || 'en-US';
  } catch {
    return 'en-US';
  }
}
