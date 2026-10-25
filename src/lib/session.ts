/**
 * Ending a session on purpose. Push is unregistered first, while the session can still call
 * the API; then the Supabase session ends. (A session the server rejects is ended by the API
 * client instead, when nothing can be called any more; the next sign-in on this phone takes
 * the push token over.)
 */

import { forgetPushRegistration, releasePushRegistration } from '@/lib/pushNotifications';
import { supabase } from '@/lib/supabase';

/** Signs the user out. Resolves with Supabase's error, if any. */
export async function signOut(): Promise<{ error: Error | null }> {
  await releasePushRegistration();
  const { error } = await supabase.auth.signOut();
  return { error };
}

/** Signs out after the account was deleted; the backend already removed its push tokens. */
export async function signOutDeletedAccount(): Promise<{ error: Error | null }> {
  await forgetPushRegistration();
  const { error } = await supabase.auth.signOut();
  return { error };
}
