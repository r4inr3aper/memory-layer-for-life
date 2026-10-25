/**
 * Notifications Screen ('/notifications')
 *
 * Push notifications for this account: the main switch (`notifications_enabled`), which
 * also asks for permission and registers this device's Expo push token, and what Cooper
 * sends on its own (ProactiveSettings): the daily brief, reminders, and quiet hours.
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Linking,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { InformationCircleIcon } from '@hugeicons/core-free-icons';
import { ScreenHeader } from '@/components/common/ScreenHeader';
import { ProactiveSettings } from '@/components/settings/ProactiveSettings';
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
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right', 'bottom']}>
      <ScreenHeader title="Notifications" />

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <View style={styles.groupCard}>
          <View style={styles.settingRow}>
            <View style={styles.settingText}>
              <Text style={styles.settingTitle}>Notifications</Text>
              <Text style={styles.settingDescription}>
                Scheduled task results, reminders, and your daily brief on this device.
              </Text>
            </View>
            {isEnabled === null ? (
              loadError ? null : (
                <ActivityIndicator color={Colors.primary} />
              )
            ) : (
              <Switch
                value={isEnabled}
                onValueChange={handleToggle}
                disabled={isSaving}
                trackColor={{ false: Colors.border, true: Colors.primaryLight }}
                thumbColor={isEnabled ? Colors.primary : Colors.surfaceMuted}
                accessibilityLabel="Notifications"
              />
            )}
          </View>
        </View>

        <ProactiveSettings />

        {loadError ? (
          <TouchableOpacity
            style={styles.errorBox}
            onPress={() => {
              setLoadError(null);
              loadSetting();
            }}
            activeOpacity={0.75}
            accessibilityRole="button">
            <Text style={styles.errorText}>{loadError}</Text>
            <Text style={styles.linkText}>Try again</Text>
          </TouchableOpacity>
        ) : null}

        {visibleNotice ? (
          <View style={styles.noticeBox}>
            <HugeiconsIcon
              icon={InformationCircleIcon}
              size={18}
              color={Colors.primary}
              strokeWidth={2}
            />
            <View style={styles.noticeBody}>
              <Text style={styles.noticeText}>{visibleNotice.message}</Text>
              {visibleNotice.showSettingsLink ? (
                <TouchableOpacity
                  onPress={() => {
                    Linking.openSettings().catch(() =>
                      showToast('Open your device settings to allow notifications.')
                    );
                  }}
                  activeOpacity={0.7}
                  accessibilityRole="button">
                  <Text style={styles.linkText}>Open settings</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingBottom: 40,
    gap: 16,
  },
  groupCard: {
    backgroundColor: Colors.surface,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
    overflow: 'hidden',
  },
  settingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 15,
    paddingHorizontal: 16,
    gap: 12,
  },
  settingText: {
    flex: 1,
  },
  settingTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: Colors.iconDark,
    letterSpacing: -0.2,
  },
  settingDescription: {
    marginTop: 3,
    fontSize: 13,
    lineHeight: 18,
    color: Colors.textSecondary,
  },
  noticeBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.primaryBorder,
    backgroundColor: Colors.primarySubtle,
  },
  noticeBody: {
    flex: 1,
    gap: 8,
  },
  noticeText: {
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.textPrimary,
  },
  errorBox: {
    padding: 14,
    borderRadius: 14,
    backgroundColor: Colors.errorLight,
    gap: 6,
  },
  errorText: {
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.error,
  },
  linkText: {
    fontSize: 13.5,
    fontWeight: '700',
    color: Colors.primary,
  },
});
