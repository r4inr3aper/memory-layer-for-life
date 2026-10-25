/**
 * MemorySourceToggle Component
 *
 * In a connected app's sheet (Google Calendar for now): whether its items become memories.
 * Turning it on syncs at once, so upcoming events show up as plans in the To do list; the
 * last sync and any problem with it are shown below the switch.
 */

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Switch, Text, View } from 'react-native';
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
    <View style={styles.box}>
      <View style={styles.row}>
        <View style={styles.text}>
          <Text style={styles.title}>Use for memories</Text>
          <Text style={styles.description}>
            Upcoming events become plans in your To do list, and Cooper knows about them.
          </Text>
        </View>
        {isSaving ? (
          <ActivityIndicator color={Colors.primary} />
        ) : (
          <Switch
            value={source.enabled}
            onValueChange={toggle}
            trackColor={{ false: Colors.border, true: Colors.primaryLight }}
            thumbColor={source.enabled ? Colors.primary : Colors.surfaceMuted}
            accessibilityLabel="Use for memories"
          />
        )}
      </View>
      {source.error ? (
        <Text style={styles.error}>{source.error}</Text>
      ) : source.enabled && source.last_synced_at ? (
        <Text style={styles.description}>
          Last synced {formatRelativeTime(source.last_synced_at)}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    marginTop: 12,
    padding: 12,
    borderRadius: 14,
    backgroundColor: Colors.surface,
    gap: 6,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  text: {
    flex: 1,
  },
  title: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  description: {
    marginTop: 2,
    fontSize: 12.5,
    lineHeight: 17,
    color: Colors.textSecondary,
  },
  error: {
    fontSize: 12.5,
    lineHeight: 17,
    color: Colors.error,
  },
});

export default MemorySourceToggle;
