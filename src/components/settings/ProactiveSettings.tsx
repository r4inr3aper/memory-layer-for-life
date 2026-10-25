/**
 * ProactiveSettings Component
 *
 * The Notifications screen's settings for what Cooper sends on its own:
 *
 * - Daily brief: on or off, and at what time (local). Turning it on also saves the
 *   phone's timezone. "Preview" shows today's brief as it stands.
 * - Reminders: push for reminders the user set (they are posted in chat either way).
 * - Quiet hours: no brief notification between two times; the brief still appears in chat.
 *
 * Every change is saved at once; a failure puts the switch back and says why.
 */

import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { MarkdownText } from '@/components/chat/MarkdownText';
import { TimeField } from '@/components/tasks/DateTimeFields';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { getBriefPreview } from '@/lib/api/life';
import { getMe, updateMe } from '@/lib/api/me';
import type { BriefPreview, Me, UpdateMeBody } from '@/lib/api/types';
import { deviceTimezone } from '@/lib/formatSchedule';

const DEFAULT_QUIET = { start: '22:00', end: '07:00' };

export function ProactiveSettings() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [preview, setPreview] = useState<BriefPreview | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getMe(controller.signal)
      .then(setMe)
      .catch((loadError) => {
        if (isAbortError(loadError, controller.signal)) return;
        setError(getErrorMessage(loadError, "Couldn't load your settings"));
      });
    return () => controller.abort();
  }, []);

  const save = async (changes: UpdateMeBody, optimistic: Partial<Me>) => {
    if (!me || isSaving) return;
    const previous = me;
    setMe({ ...me, ...optimistic });
    setIsSaving(true);
    try {
      setMe(await updateMe(changes));
    } catch (saveError) {
      setMe(previous);
      showToast(getErrorMessage(saveError, 'Could not save your choice'));
    } finally {
      setIsSaving(false);
    }
  };

  const openPreview = async () => {
    setIsPreviewing(true);
    try {
      setPreview(await getBriefPreview());
    } catch (previewError) {
      setIsPreviewing(false);
      showToast(getErrorMessage(previewError, 'Could not load the brief'));
    }
  };

  if (error) {
    return <Text style={styles.errorText}>{error}</Text>;
  }
  if (!me) {
    return <ActivityIndicator color={Colors.primary} />;
  }

  const quiet = me.quiet_hours_start !== null && me.quiet_hours_end !== null;

  return (
    <View style={styles.groupCard}>
      <View style={styles.settingRow}>
        <View style={styles.settingText}>
          <Text style={styles.settingTitle}>Daily brief</Text>
          <Text style={styles.settingDescription}>
            Each morning in chat: what&apos;s due, what&apos;s overdue, and yesterday&apos;s items
            to check off.
          </Text>
        </View>
        <Switch
          value={me.brief_enabled}
          onValueChange={(value) =>
            save(
              value
                ? { brief_enabled: true, timezone: deviceTimezone() }
                : { brief_enabled: false },
              { brief_enabled: value }
            )
          }
          disabled={isSaving}
          trackColor={{ false: Colors.border, true: Colors.primaryLight }}
          thumbColor={me.brief_enabled ? Colors.primary : Colors.surfaceMuted}
          accessibilityLabel="Daily brief"
        />
      </View>
      {me.brief_enabled ? (
        <View style={styles.subRow}>
          <Text style={styles.subLabel}>At</Text>
          <TimeField
            value={me.brief_time}
            onChange={(value) => save({ brief_time: value }, { brief_time: value })}
            accessibilityLabel="Brief time"
          />
          <TouchableOpacity onPress={openPreview} activeOpacity={0.7}>
            <Text style={styles.linkText}>Preview</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      <View style={styles.divider} />

      <View style={styles.settingRow}>
        <View style={styles.settingText}>
          <Text style={styles.settingTitle}>Reminders</Text>
          <Text style={styles.settingDescription}>
            Notify me when a reminder I set is due. It appears in chat either way.
          </Text>
        </View>
        <Switch
          value={me.reminders_enabled}
          onValueChange={(value) =>
            save({ reminders_enabled: value }, { reminders_enabled: value })
          }
          disabled={isSaving}
          trackColor={{ false: Colors.border, true: Colors.primaryLight }}
          thumbColor={me.reminders_enabled ? Colors.primary : Colors.surfaceMuted}
          accessibilityLabel="Reminders"
        />
      </View>

      <View style={styles.divider} />

      <View style={styles.settingRow}>
        <View style={styles.settingText}>
          <Text style={styles.settingTitle}>Quiet hours</Text>
          <Text style={styles.settingDescription}>
            No brief notification during these hours. Reminders you set still come through.
          </Text>
        </View>
        <Switch
          value={quiet}
          onValueChange={(value) =>
            save(
              value
                ? { quiet_hours_start: DEFAULT_QUIET.start, quiet_hours_end: DEFAULT_QUIET.end }
                : { quiet_hours_start: null, quiet_hours_end: null },
              value
                ? { quiet_hours_start: DEFAULT_QUIET.start, quiet_hours_end: DEFAULT_QUIET.end }
                : { quiet_hours_start: null, quiet_hours_end: null }
            )
          }
          disabled={isSaving}
          trackColor={{ false: Colors.border, true: Colors.primaryLight }}
          thumbColor={quiet ? Colors.primary : Colors.surfaceMuted}
          accessibilityLabel="Quiet hours"
        />
      </View>
      {quiet ? (
        <View style={styles.subRow}>
          <Text style={styles.subLabel}>From</Text>
          <TimeField
            value={me.quiet_hours_start ?? DEFAULT_QUIET.start}
            onChange={(value) =>
              save(
                { quiet_hours_start: value, quiet_hours_end: me.quiet_hours_end },
                { quiet_hours_start: value }
              )
            }
            accessibilityLabel="Quiet hours start"
          />
          <Text style={styles.subLabel}>to</Text>
          <TimeField
            value={me.quiet_hours_end ?? DEFAULT_QUIET.end}
            onChange={(value) =>
              save(
                { quiet_hours_start: me.quiet_hours_start, quiet_hours_end: value },
                { quiet_hours_end: value }
              )
            }
            accessibilityLabel="Quiet hours end"
          />
        </View>
      ) : null}

      <Modal
        visible={isPreviewing}
        transparent
        animationType="fade"
        onRequestClose={() => setIsPreviewing(false)}>
        <View style={styles.previewOverlay}>
          <View style={styles.previewCard}>
            <Text style={styles.previewTitle}>Today&apos;s brief</Text>
            {preview ? (
              <ScrollView style={styles.previewBody}>
                <MarkdownText text={preview.text} />
              </ScrollView>
            ) : (
              <ActivityIndicator color={Colors.primary} />
            )}
            <TouchableOpacity
              style={styles.closeButton}
              onPress={() => {
                setIsPreviewing(false);
                setPreview(null);
              }}
              activeOpacity={0.8}>
              <Text style={styles.closeText}>Close</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
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
  subRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 10,
    paddingHorizontal: 16,
    paddingBottom: 14,
  },
  subLabel: {
    fontSize: 13.5,
    color: Colors.textSecondary,
  },
  divider: {
    height: 1,
    backgroundColor: Colors.borderLight,
    marginHorizontal: 16,
  },
  linkText: {
    fontSize: 13.5,
    fontWeight: '700',
    color: Colors.primary,
  },
  errorText: {
    fontSize: 13.5,
    color: Colors.error,
  },
  previewOverlay: {
    flex: 1,
    backgroundColor: Colors.overlay,
    justifyContent: 'center',
    padding: 24,
  },
  previewCard: {
    maxHeight: '80%',
    backgroundColor: Colors.white,
    borderRadius: 20,
    padding: 18,
    gap: 12,
  },
  previewTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  previewBody: {
    flexGrow: 0,
  },
  closeButton: {
    height: 42,
    borderRadius: 21,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
});

export default ProactiveSettings;
