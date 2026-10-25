/**
 * useRequireSession
 *
 * Route guard for signed-in screens: sends the user to the sign-in screen when there is no
 * Supabase session, at mount and whenever the session ends (sign-out, a refresh token that
 * stopped working, or a 401 from the API, which signs out).
 */

import { supabase } from '@/lib/supabase';
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';

/** Whether a session is confirmed. Render nothing that calls the API until it is. */
export function useRequireSession(): boolean {
  const router = useRouter();
  const [hasSession, setHasSession] = useState(false);

  useEffect(() => {
    let isActive = true;
    let hasRedirected = false;

    const handleSession = (signedIn: boolean) => {
      if (!isActive) return;
      setHasSession(signedIn);
      if (signedIn) {
        hasRedirected = false;
      } else if (!hasRedirected) {
        // The initial check and the initial auth event can both report no session.
        hasRedirected = true;
        router.replace('/');
      }
    };

    supabase.auth
      .getSession()
      .then(({ data }) => handleSession(Boolean(data.session)))
      .catch(() => handleSession(false));

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => handleSession(Boolean(session)));

    return () => {
      isActive = false;
      subscription.unsubscribe();
    };
  }, [router]);

  return hasSession;
}
