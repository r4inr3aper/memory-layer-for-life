/**
 * Client Environment Configuration
 *
 * The only environment values the app reads. Expo inlines `EXPO_PUBLIC_*` variables at
 * build time, so each one must be read as a literal `process.env.EXPO_PUBLIC_...`.
 */

import Constants from 'expo-constants';
import { Platform } from 'react-native';

const DEV_API_PORT = 8000;

const supabaseUrl = clean(process.env.EXPO_PUBLIC_SUPABASE_URL);
const supabasePublishableKey = clean(process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY);
const apiUrl = resolveApiUrl(clean(process.env.EXPO_PUBLIC_API_URL));

export const env = {
  /** Supabase project URL, used only for Supabase Auth. */
  supabaseUrl,
  /** Supabase publishable key (`sb_publishable_...`), used only for Supabase Auth. */
  supabasePublishableKey,
  /** Origin of the backend API without a trailing slash, e.g. `http://192.168.1.20:8000`. */
  apiUrl,
} as const;

/** Whether Supabase Auth has real (non-placeholder) configuration. */
export const isSupabaseConfigured = Boolean(
  supabaseUrl && supabasePublishableKey && !supabaseUrl.includes('placeholder')
);

/** Whether a backend API origin is known. */
export const isApiConfigured = Boolean(apiUrl);

/**
 * Uses `EXPO_PUBLIC_API_URL` when set. In development it falls back to the Expo dev
 * server's host on the API port, so a phone on the same network reaches the backend.
 */
function resolveApiUrl(configured: string): string {
  if (configured) {
    return configured.replace(/\/+$/, '');
  }

  if (!__DEV__) {
    return '';
  }

  const devHost = Constants.expoConfig?.hostUri?.split(':')[0];
  if (devHost) {
    return `http://${devHost}:${DEV_API_PORT}`;
  }

  return Platform.OS === 'web' ? `http://localhost:${DEV_API_PORT}` : '';
}

function clean(value: string | undefined): string {
  return value?.trim() ?? '';
}
