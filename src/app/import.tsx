/**
 * Import a Chat Screen ('/import')
 *
 * Bring a WhatsApp chat in as memories, in two steps:
 * 1. Pick the export (in WhatsApp: More > Export chat > Without media). The backend reads it
 *    and lists who wrote in it; nothing is imported yet.
 * 2. Say which person is you, from when, and whether to keep only conversations you took
 *    part in. The estimate shows how many extractions that is and roughly what it costs.
 *    Start queues them; memories appear as the backend works through them.
 *
 * Earlier imports are listed with their progress, refreshed while one is running.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { useFocusEffect, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ScreenHeader } from '@/components/common/ScreenHeader';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { readBase64 } from '@/lib/attachmentPicker';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { listImports, previewImport, startImport } from '@/lib/api/sources';
import type { ChatImport } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { formatRelativeTime } from '@/lib/formatTime';
import {
  DEFAULT_IMPORT_CONVERSATIONS,
  importEstimate,
  importProgressText,
  plannedConversations,
  sinceChoices,
} from '@/lib/imports';
import { isoDate } from '@/lib/life';

const POLL_MS = 5000;
const MAX_FILE_BYTES = 10 * 1024 * 1024;

export default function ImportScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const [imports, setImports] = useState<ChatImport[]>([]);
  const [preview, setPreview] = useState<ChatImport | null>(null);
  const [me, setMe] = useState<string | null>(null);
  const [since, setSince] = useState<string | null>(null);
  const [onlyMine, setOnlyMine] = useState(true);
  const [isReading, setIsReading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);

  const load = useCallback((signal?: AbortSignal) => {
    return listImports(signal)
      .then(setImports)
      .catch((error) => {
        if (!isAbortError(error, signal)) {
          showToast(getErrorMessage(error, "Couldn't load your imports"));
        }
      });
  }, []);

  useFocusEffect(
    useCallback(() => {
      if (!hasSession) return undefined;
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [hasSession, load])
  );

  // While an import is being worked through, refresh its progress.
  const running = imports.some((item) => (item.progress?.waiting ?? 0) > 0);
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [running, load]);

  const pickFile = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ['text/plain', 'application/zip', 'application/x-zip-compressed', '*/*'],
      multiple: false,
      copyToCacheDirectory: true,
    });
    if (result.canceled) return;
    const [file] = result.assets;
    if ((file.size ?? 0) > MAX_FILE_BYTES) {
      showToast('That file is too large. Export the chat without media.', 3500);
      return;
    }
    setIsReading(true);
    try {
      const read = await previewImport(file.name, await readBase64(file));
      setPreview(read);
      setMe(null);
      setSince(null);
      setOnlyMine(true);
    } catch (error) {
      showToast(getErrorMessage(error, "Couldn't read that file"), 4000);
    } finally {
      setIsReading(false);
    }
  };

  const start = async () => {
    if (!preview || !me || isStarting) return;
    const conversations = plannedConversations(preview, me, onlyMine);
    const confirmed = await confirmAsync({
      title: 'Import this chat?',
      message:
        `${importEstimate(preview, conversations)}. Memories appear over the next few ` +
        'minutes, and you can review them in Memories.',
      confirmText: 'Import',
    });
    if (!confirmed) return;
    setIsStarting(true);
    try {
      await startImport(preview.id, {
        me,
        since,
        only_my_conversations: onlyMine,
        max_conversations: DEFAULT_IMPORT_CONVERSATIONS,
      });
      setPreview(null);
      showToast('Importing. This takes a few minutes.');
      await load();
    } catch (error) {
      showToast(getErrorMessage(error, "Couldn't start the import"), 4000);
    } finally {
      setIsStarting(false);
    }
  };

  if (!hasSession) {
    return <View style={styles.safeArea} />;
  }

  const planned = preview ? plannedConversations(preview, me, onlyMine) : 0;

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right', 'bottom']}>
      <ScreenHeader title="Import a chat" fallbackHref="/memories" />
      <ScrollView contentContainerStyle={styles.content}>
        {preview ? (
          <View style={styles.card}>
            <Text style={styles.title}>{preview.file_name}</Text>
            <Text style={styles.meta}>
              {preview.message_count.toLocaleString()} messages
              {preview.first_message_at
                ? ` since ${formatRelativeTime(preview.first_message_at)}`
                : ''}
            </Text>

            <Text style={styles.label}>Which one is you?</Text>
            {preview.participants.map((participant) => (
              <TouchableOpacity
                key={participant.name}
                style={[styles.option, me === participant.name && styles.optionSelected]}
                onPress={() => setMe(participant.name)}
                activeOpacity={0.75}
                accessibilityRole="radio"
                accessibilityState={{ selected: me === participant.name }}>
                <Text style={styles.optionText}>{participant.name}</Text>
                <Text style={styles.meta}>{participant.messages.toLocaleString()} messages</Text>
              </TouchableOpacity>
            ))}

            <Text style={styles.label}>From when</Text>
            <View style={styles.chipRow}>
              {sinceChoices(isoDate(new Date())).map((choice) => (
                <TouchableOpacity
                  key={choice.label}
                  style={[styles.chip, since === choice.value && styles.chipSelected]}
                  onPress={() => setSince(choice.value)}
                  accessibilityRole="button"
                  accessibilityState={{ selected: since === choice.value }}>
                  <Text
                    style={[styles.chipText, since === choice.value && styles.chipTextSelected]}>
                    {choice.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <View style={styles.switchRow}>
              <View style={styles.flex}>
                <Text style={styles.optionText}>Only conversations I was in</Text>
                <Text style={styles.meta}>Leaves out talk between the others.</Text>
              </View>
              <Switch
                value={onlyMine}
                onValueChange={setOnlyMine}
                trackColor={{ false: Colors.border, true: Colors.primaryLight }}
                thumbColor={onlyMine ? Colors.primary : Colors.surfaceMuted}
                accessibilityLabel="Only conversations I was in"
              />
            </View>

            {me ? (
              <Text style={styles.estimate}>
                {importEstimate(preview, planned)}. The most recent conversations come first.
              </Text>
            ) : null}

            <View style={styles.actions}>
              <TouchableOpacity style={styles.secondary} onPress={() => setPreview(null)}>
                <Text style={styles.secondaryText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.primary, (!me || isStarting) && styles.disabled]}
                onPress={start}
                disabled={!me || isStarting}
                accessibilityRole="button">
                {isStarting ? (
                  <ActivityIndicator color={Colors.white} />
                ) : (
                  <Text style={styles.primaryText}>Import</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        ) : (
          <View style={styles.card}>
            <Text style={styles.title}>Bring a WhatsApp chat in</Text>
            <Text style={styles.body}>
              In WhatsApp, open the chat, tap More &gt; Export chat &gt; Without media, and save the
              file. Then pick it here. You&apos;ll see who&apos;s in it and what it costs before
              anything is imported.
            </Text>
            <TouchableOpacity
              style={[styles.primary, isReading && styles.disabled]}
              onPress={pickFile}
              disabled={isReading}
              accessibilityRole="button">
              {isReading ? (
                <ActivityIndicator color={Colors.white} />
              ) : (
                <Text style={styles.primaryText}>Choose the export</Text>
              )}
            </TouchableOpacity>
          </View>
        )}

        {imports.filter((item) => item.status === 'queued').length ? (
          <Text style={styles.sectionTitle}>Your imports</Text>
        ) : null}
        {imports
          .filter((item) => item.status === 'queued')
          .map((item) => (
            <TouchableOpacity
              key={item.id}
              style={styles.importRow}
              onPress={() => router.push({ pathname: '/memories', params: { tab: 'review' } })}
              activeOpacity={0.75}>
              <Text style={styles.optionText}>{item.file_name}</Text>
              <Text style={styles.meta}>
                {importProgressText(item)} · {formatRelativeTime(item.created_at)}
              </Text>
            </TouchableOpacity>
          ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  flex: {
    flex: 1,
  },
  content: {
    padding: 16,
    paddingBottom: 40,
    gap: 12,
  },
  card: {
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    gap: 8,
  },
  title: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  body: {
    fontSize: 14,
    lineHeight: 20,
    color: Colors.textSecondary,
    marginBottom: 6,
  },
  meta: {
    fontSize: 12.5,
    color: Colors.textSecondary,
  },
  label: {
    marginTop: 10,
    fontSize: 11,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  option: {
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  optionSelected: {
    borderColor: Colors.primaryBorder,
    backgroundColor: Colors.primarySubtle,
  },
  optionText: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  chipSelected: {
    borderColor: Colors.primaryBorder,
    backgroundColor: Colors.primarySubtle,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.textSecondary,
  },
  chipTextSelected: {
    color: Colors.primary,
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 10,
  },
  estimate: {
    marginTop: 8,
    padding: 12,
    borderRadius: 12,
    backgroundColor: Colors.surface,
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.iconDark,
  },
  actions: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 10,
  },
  primary: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.white,
  },
  secondary: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  disabled: {
    opacity: 0.5,
  },
  sectionTitle: {
    marginTop: 8,
    fontSize: 12,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  importRow: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
    gap: 2,
  },
});
