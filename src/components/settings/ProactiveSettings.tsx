/**
 * ProactiveSettings Component
 *
 * The Notifications screen's settings for what Cooper sends on its own, as inset-grouped
 * sections, each explained in its footer:
 *
 * - Daily brief: on or off, and at what time (local). Turning it on also saves the
 *   phone's timezone. "Preview" shows today's brief as it stands, in a sheet.
 * - Reminders: push for reminders the user set (they are posted in chat either way).
 * - Quiet hours: no brief notification between two times; the brief still appears in chat.
 *
 * Every change is saved at once; a failure puts the switch back and says why.
 */

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { MarkdownText } from '@/components/chat/MarkdownText';
import { TimeField } from '@/components/tasks/DateTimeFields';
import { AppSwitch, AppText, BottomSheet, Card, ListRow, ListSection } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { ScreenMargin } from '@/constants/theme';
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
    // The previous preview is cleared here rather than on close, so the sheet keeps its
    // content while it slides away.
    setPreview(null);
    setIsPreviewing(true);
    try {
      setPreview(await getBriefPreview());
    } catch (previewError) {
      setIsPreviewing(false);
      showToast(getErrorMessage(previewError, 'Could not load the brief'));
    }
  };

  if (error) {
    return (
      <AppText variant="footnote" color="destructive" style={styles.standalone}>
        {error}
      </AppText>
    );
  }
  if (!me) {
    return <ActivityIndicator color={Colors.secondaryLabel} style={styles.standalone} />;
  }

  const quiet = me.quiet_hours_start !== null && me.quiet_hours_end !== null;

  return (
    <>
      <ListSection footer="Each morning in chat: what's due, what's overdue, and yesterday's items to check off.">
        <ListRow
          title="Daily brief"
          accessory={
            <AppSwitch
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
              accessibilityLabel="Daily brief"
            />
          }
        />
        {me.brief_enabled ? (
          <TimeRow label="Time">
            <TimeField
              value={me.brief_time}
              onChange={(value) => save({ brief_time: value }, { brief_time: value })}
              accessibilityLabel="Brief time"
            />
          </TimeRow>
        ) : null}
        {me.brief_enabled ? <ListRow title="Preview" action onPress={openPreview} /> : null}
      </ListSection>

      <ListSection footer="Notify me when a reminder I set is due. It appears in chat either way.">
        <ListRow
          title="Reminders"
          accessory={
            <AppSwitch
              value={me.reminders_enabled}
              onValueChange={(value) =>
                save({ reminders_enabled: value }, { reminders_enabled: value })
              }
              disabled={isSaving}
              accessibilityLabel="Reminders"
            />
          }
        />
      </ListSection>

      <ListSection footer="No brief notification during these hours. Reminders you set still come through.">
        <ListRow
          title="Quiet hours"
          accessory={
            <AppSwitch
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
              accessibilityLabel="Quiet hours"
            />
          }
        />
        {quiet ? (
          <TimeRow label="From">
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
          </TimeRow>
        ) : null}
        {quiet ? (
          <TimeRow label="To">
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
          </TimeRow>
        ) : null}
      </ListSection>

      <BottomSheet
        visible={isPreviewing}
        onClose={() => setIsPreviewing(false)}
        title="Today's brief"
        rightAction={{ label: 'Done', onPress: () => setIsPreviewing(false) }}
        scrollable>
        {preview ? (
          <Card style={styles.previewCard}>
            <MarkdownText text={preview.text} />
          </Card>
        ) : (
          <ActivityIndicator color={Colors.secondaryLabel} style={styles.previewSpinner} />
        )}
      </BottomSheet>
    </>
  );
}

/**
 * A cell with a label at the left and a time field at the right. The field wraps to its
 * own line when it grows (iOS shows its spinner inline).
 */
function TimeRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.timeRow}>
      <AppText variant="body" style={styles.timeLabel}>
        {label}
      </AppText>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  standalone: {
    marginHorizontal: ScreenMargin * 2,
    marginBottom: 28,
  },
  timeRow: {
    minHeight: 48,
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: Colors.secondaryGroupedBackground,
  },
  timeLabel: {
    flexGrow: 1,
  },
  previewCard: {
    marginHorizontal: ScreenMargin,
    marginBottom: 8,
  },
  previewSpinner: {
    marginVertical: 32,
  },
});

export default ProactiveSettings;
