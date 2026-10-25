/**
 * Timezone Sync
 *
 * The backend sends the daily brief at the user's local time and works out what is due
 * "today" in their timezone, so the app reports the phone's timezone after each sign-in
 * (and at launch with a saved session). A failure is logged and retried next time.
 */

import { updateMe } from '@/lib/api/me';
import { deviceTimezone } from '@/lib/formatSchedule';

export async function syncTimezone(): Promise<void> {
  try {
    await updateMe({ timezone: deviceTimezone() });
  } catch (error) {
    console.warn('Could not save the timezone:', error);
  }
}
