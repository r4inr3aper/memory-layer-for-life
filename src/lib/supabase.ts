/**
 * Supabase Auth Client
 *
 * Used only for Google sign-in, session persistence, and the access token sent to the
 * backend API. All app data goes through the API (`@/lib/api`), never through Supabase.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient } from '@supabase/supabase-js';
import { AppState, Platform } from 'react-native';
import { env, isSupabaseConfigured } from '@/lib/env';

export { isSupabaseConfigured };

/**
 * Single Supabase client instance, for authentication only.
 */
export const supabase = createClient(
  env.supabaseUrl || 'https://placeholder.supabase.co',
  env.supabasePublishableKey || 'placeholder-key',
  {
    auth: {
      // Native apps persist the session in AsyncStorage. On web, supabase-js picks
      // localStorage in the browser and memory during static rendering, where
      // AsyncStorage would touch `window` and crash.
      ...(Platform.OS === 'web' ? {} : { storage: AsyncStorage }),
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false,
    },
  }
);

// Native apps refresh the session only while in the foreground: timers do not run reliably
// in the background, so a token can expire there and must be refreshed on return.
// Supabase's documented React Native pattern; browsers manage this themselves.
if (Platform.OS !== 'web') {
  AppState.addEventListener('change', (state) => {
    if (state === 'active') {
      supabase.auth.startAutoRefresh();
    } else {
      supabase.auth.stopAutoRefresh();
    }
  });
}

/**
 * The signed-in user's access token, refreshed by Supabase when it has expired.
 */
export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
