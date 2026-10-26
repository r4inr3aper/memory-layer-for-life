/**
 * Notifications Screen ('/notifications')
 *
 * Push notifications for this account: the main switch (`notifications_enabled`), which
 * also asks for permission and registers this device's Expo push token, and what Cooper
 * sends on its own (ProactiveSettings): the daily brief, reminders, and quiet hours.
 *
 * A pushed screen with a large title over inset-grouped sections; anything that stops
 * notifications from reaching this device is explained right under the main switch.
 */

import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Linking, StyleSheet, View } from 'react-native';
import Animated from 'react-native-reanimated';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { InformationCircleIcon } from '@hugeicons/core-free-icons';
import { ProactiveSettings } from '@/components/settings/ProactiveSettings';
import {
  AppSwitch,
  AppText,
  LargeTitle,
  ListRow,
  ListSection,
  ScreenHeader,
  useScrollY,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { getMe, updateMe } from '@/lib/api/me';
import { getPushUnavailableReason, registerForPushNotifications } from '@/lib/pushNotifications';

const PERMISSION_DENIED_MESSAGE =
  'Notifications are turned off for this app in your device settings. Allow them there to get results on this device.';

interface Notice {
  message: string;
  /** Offer a shortcut to the app's system settings. */
  showSettingsLink?: boolean;
}

export default function NotificationsScreen() {
  const insets = useSafeAreaInsets();
  const { scrollY, onScroll } = useScrollY();
  const [isEnabled, setIsEnabled] = useState<boolean | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const loadSetting = useCallback((signal?: AbortSignal) => {
    getMe(signal)
      .then((me) => {
        setIsEnabled(me.notifications_enabled);
        setLoadError(null);
      })
      .catch((error) => {
        if (isAbortError(error, signal)) return;
        console.error('Failed to load notification setting:', error);
        setLoadError(getErrorMessage(error, "Couldn't load your notification setting"));
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadSetting(controller.signal);
    return () => controller.abort();
  }, [loadSetting]);

  const handleToggle = async (nextValue: boolean) => {
    if (isSaving || isEnabled === null) return;

    const previousValue = isEnabled;
    setIsEnabled(nextValue);
    setIsSaving(true);
    setNotice(null);

    try {
      const me = await updateMe({ notifications_enabled: nextValue });
      setIsEnabled(me.notifications_enabled);
    } catch (error) {
      console.error('Failed to save notification setting:', error);
      setIsEnabled(previousValue);
      showToast(getErrorMessage(error, 'Could not save your choice'));
      setIsSaving(false);
      return;
    }

    if (!nextValue) {
      showToast('Notifications are off');
      setIsSaving(false);
      return;
    }

    try {
      const result = await registerForPushNotifications();
      if (result.status === 'registered') {
        showToast('Notifications are on');
      } else if (result.status === 'denied') {
        setNotice({ message: PERMISSION_DENIED_MESSAGE, showSettingsLink: true });
      } else {
        setNotice({ message: result.reason });
      }
    } catch (error) {
      console.error('Failed to register for push notifications:', error);
      setNotice({
        message: getErrorMessage(error, 'Could not set up notifications on this device.'),
      });
    } finally {
      setIsSaving(false);
    }
  };

  // Where push cannot work at all, say so whenever the setting is on.
  const unavailableReason = isEnabled ? getPushUnavailableReason() : null;
  const visibleNotice = notice ?? (unavailableReason ? { message: unavailableReason } : null);

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      <ScreenHeader title="Notifications" scrollY={scrollY} />

      <Animated.ScrollView
        style={styles.scrollView}
        contentContainerStyle={{ paddingBottom: insets.bottom + 32 }}
        onScroll={onScroll}
        scrollEventThrottle={16}>
        <LargeTitle title="Notifications" />

        <ListSection footer="Scheduled task results, reminders, and your daily brief on this device.">
          <ListRow
            title="Notifications"
            accessory={
              isEnabled === null ? (
                loadError ? null : (
                  <ActivityIndicator color={Colors.secondaryLabel} />
                )
              ) : (
                <AppSwitch
                  value={isEnabled}
                  onValueChange={handleToggle}
                  disabled={isSaving}
                  accessibilityLabel="Notifications"
                />
              )
            }
          />
        </ListSection>

        {loadError ? (
          <ListSection>
            <View style={styles.messageCell}>
              <AppText variant="subheadline" color="destructive">
                {loadError}
              </AppText>
            </View>
            <ListRow
              title="Try again"
              action
              onPress={() => {
                setLoadError(null);
                loadSetting();
              }}
            />
          </ListSection>
        ) : null}

        {visibleNotice ? (
          <ListSection>
            <View style={styles.messageCell}>
              <HugeiconsIcon
                icon={InformationCircleIcon}
                size={20}
                color={Colors.tint}
                strokeWidth={2}
              />
              <AppText variant="subheadline" style={styles.messageText}>
                {visibleNotice.message}
              </AppText>
            </View>
            {visibleNotice.showSettingsLink ? (
              <ListRow
                title="Open settings"
                action
                onPress={() => {
                  Linking.openSettings().catch(() =>
                    showToast('Open your device settings to allow notifications.')
                  );
                }}
              />
            ) : null}
          </ListSection>
        ) : null}

        <ProactiveSettings />
      </Animated.ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  scrollView: {
    flex: 1,
  },
  messageCell: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: Colors.secondaryGroupedBackground,
  },
  messageText: {
    flex: 1,
  },
});
