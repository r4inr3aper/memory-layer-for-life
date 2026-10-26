/**
 * MemorySourceToggle Component
 *
 * In a connected app's sheet (Google Calendar for now): whether its items become memories,
 * as a switch row in its own inset-grouped section. Turning it on syncs at once, so upcoming
 * events show up as plans in the To do list; the section's footer explains it and shows the
 * last sync or any problem with it.
 */

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { AppSwitch, AppText, ListRow, ListSection } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { listSources, setSourceEnabled } from '@/lib/api/sources';
import type { SourceApp } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';

export const MEMORY_SOURCE_APPS: readonly string[] = ['googlecalendar'];

export function MemorySourceToggle({ app }: { app: string }) {
  const [source, setSource] = useState<SourceApp | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listSources(controller.signal)
      .then((sources) => setSource(sources.find((item) => item.app === app) ?? null))
      .catch((error) => {
        if (!isAbortError(error, controller.signal)) {
          console.warn('Failed to load memory sources:', error);
        }
      });
    return () => controller.abort();
  }, [app]);

  const toggle = async (enabled: boolean) => {
    if (!source || isSaving) return;
    setIsSaving(true);
    setSource({ ...source, enabled });
    try {
      const saved = await setSourceEnabled(app, enabled);
      setSource(saved);
      showToast(enabled ? 'Upcoming events are now in your To do list' : 'Stopped');
    } catch (error) {
      showToast(getErrorMessage(error, 'Could not sync your calendar'), 4000);
      // The backend records why a sync failed; show the source as it now is.
      const sources = await listSources().catch(() => null);
      setSource(sources?.find((item) => item.app === app) ?? { ...source, enabled: false });
    } finally {
      setIsSaving(false);
    }
  };

  if (!source) return null;

  return (
    <ListSection
      header="Memories"
      footer={
        <View style={styles.footer}>
          <AppText variant="footnote" color="secondary">
            Upcoming events become plans in your To do list, and Cooper knows about them.
          </AppText>
          {source.error ? (
            <AppText variant="footnote" color="destructive">
              {source.error}
            </AppText>
          ) : source.enabled && source.last_synced_at ? (
            <AppText variant="footnote" color="secondary">
              Last synced {formatRelativeTime(source.last_synced_at)}
            </AppText>
          ) : null}
        </View>
      }>
      <ListRow
        title="Use for memories"
        accessory={
          isSaving ? (
            <ActivityIndicator color={Colors.secondaryLabel} />
          ) : (
            <AppSwitch
              value={source.enabled}
              onValueChange={toggle}
              accessibilityLabel="Use for memories"
            />
          )
        }
      />
    </ListSection>
  );
}

const styles = StyleSheet.create({
  footer: {
    gap: 4,
  },
});

export default MemorySourceToggle;
