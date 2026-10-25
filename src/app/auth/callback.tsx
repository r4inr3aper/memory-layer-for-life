/**
 * OAuth Callback Screen ('/auth/callback')
 *
 * Google sign-in returns to the app through this deep link. The sign-in screen that started
 * the flow reads the tokens from the link and opens the chat; this route exists so the
 * link lands on a loading screen instead of Expo Router's "Unmatched Route" page.
 *
 * If the sign-in screen is no longer there to finish the flow (for example, the app was
 * restarted while the browser was open), this screen moves on by itself.
 */

import { Colors } from '@/constants/colors';
import { supabase } from '@/lib/supabase';
import { useRouter } from 'expo-router';
import React, { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

// Long enough for the sign-in screen to store the session and navigate first.
const FALLBACK_MS = 4000;

export default function AuthCallbackScreen() {
  const router = useRouter();

  useEffect(() => {
    const timer = setTimeout(async () => {
      const { data } = await supabase.auth.getSession();
      router.replace(data.session ? '/(tabs)/chat' : '/');
    }, FALLBACK_MS);

    return () => clearTimeout(timer);
  }, [router]);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color={Colors.primary} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.white,
  },
});
