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
 *
 * A pushed screen with a large title. The choices are inset-grouped lists with
 * checkmarks, as iOS pickers are; Import is the one filled button.
 */

import { useCallback, useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated from 'react-native-reanimated';
import * as DocumentPicker from 'expo-document-picker';
import { useFocusEffect, useRouter } from 'expo-router';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { FileImportIcon, WhatsappIcon } from '@hugeicons/core-free-icons';
import {
  AppSwitch,
  AppText,
  Button,
  Card,
  EmptyState,
  IconTile,
  LargeTitle,
  ListRow,
  ListSection,
  ScreenHeader,
  useScrollY,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { ScreenMargin } from '@/constants/theme';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { readBase64 } from '@/lib/attachmentPicker';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { listImports, previewImport, startImport } from '@/lib/api/sources';
import type { ChatImport } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { formatRelativeTime } from '@/lib/formatTime';
import { haptic } from '@/lib/haptics';
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
  const insets = useSafeAreaInsets();
  const { scrollY, onScroll } = useScrollY();
  const [imports, setImports] = useState<ChatImport[]>([]);
  // Whether the list has loaded once, so "No imports yet" never flashes before it does.
  const [hasLoaded, setHasLoaded] = useState(false);
  const [preview, setPreview] = useState<ChatImport | null>(null);
  const [me, setMe] = useState<string | null>(null);
  const [since, setSince] = useState<string | null>(null);
  const [onlyMine, setOnlyMine] = useState(true);
  const [isReading, setIsReading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);

  const load = useCallback((signal?: AbortSignal) => {
    return listImports(signal)
      .then((list) => {
        setImports(list);
        setHasLoaded(true);
      })
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
      haptic.success();
      showToast('Importing. This takes a few minutes.');
      await load();
    } catch (error) {
      haptic.error();
      showToast(getErrorMessage(error, "Couldn't start the import"), 4000);
    } finally {
      setIsStarting(false);
    }
  };

  if (!hasSession) {
    return <View style={styles.safeArea} />;
  }

  const planned = preview ? plannedConversations(preview, me, onlyMine) : 0;
  const queued = imports.filter((item) => item.status === 'queued');

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      <ScreenHeader title="Import a chat" fallbackHref="/memories" scrollY={scrollY} />
      <Animated.ScrollView
        style={styles.flex}
        contentContainerStyle={{ paddingBottom: insets.bottom + 32 }}
        onScroll={onScroll}
        scrollEventThrottle={16}>
        <LargeTitle title="Import a chat" />

        {preview ? (
          <>
            <ListSection>
              <ListRow
                icon={WhatsappIcon}
                iconColor={Colors.systemGreen}
                title={preview.file_name}
                subtitle={`${preview.message_count.toLocaleString()} messages${
                  preview.first_message_at
                    ? ` since ${formatRelativeTime(preview.first_message_at)}`
                    : ''
                }`}
              />
            </ListSection>

            <ListSection header="Which one is you?">
              {preview.participants.map((participant) => {
                const selected = me === participant.name;
                return (
                  <ListRow
                    key={participant.name}
                    title={participant.name}
                    subtitle={`${participant.messages.toLocaleString()} messages`}
                    accessory={selected ? 'check' : 'none'}
                    onPress={() => setMe(participant.name)}
                    accessibilityLabel={selected ? `${participant.name}, selected` : participant.name}
                  />
                );
              })}
            </ListSection>

            <ListSection header="From when">
              {sinceChoices(isoDate(new Date())).map((choice) => {
                const selected = since === choice.value;
                return (
                  <ListRow
                    key={choice.label}
                    title={choice.label}
                    accessory={selected ? 'check' : 'none'}
                    onPress={() => setSince(choice.value)}
                    accessibilityLabel={selected ? `${choice.label}, selected` : choice.label}
                  />
                );
              })}
            </ListSection>

            <ListSection
              footer={
                me
                  ? `${importEstimate(preview, planned)}. The most recent conversations come first.`
                  : undefined
              }>
              <ListRow
                title="Only conversations I was in"
                subtitle="Leaves out talk between the others."
                accessory={
                  <AppSwitch
                    value={onlyMine}
                    onValueChange={setOnlyMine}
                    accessibilityLabel="Only conversations I was in"
                  />
                }
              />
            </ListSection>

            <View style={styles.actions}>
              <Button
                title="Cancel"
                variant="gray"
                size="large"
                block
                onPress={() => setPreview(null)}
                containerStyle={styles.flex}
              />
              <Button
                title="Import"
                variant="filled"
                size="large"
                block
                onPress={start}
                loading={isStarting}
                disabled={!me}
                containerStyle={styles.flex}
              />
            </View>
          </>
        ) : (
          <Card style={styles.intro}>
            <IconTile icon={WhatsappIcon} color={Colors.systemGreen} size={44} />
            <AppText variant="title3">Bring a WhatsApp chat in</AppText>
            <AppText variant="subheadline" color="secondary">
              In WhatsApp, open the chat, tap More &gt; Export chat &gt; Without media, and save the
              file. Then pick it here. You&apos;ll see who&apos;s in it and what it costs before
              anything is imported.
            </AppText>
            <Button
              title="Choose the export"
              variant="filled"
              size="large"
              block
              onPress={pickFile}
              loading={isReading}
              containerStyle={styles.introButton}
            />
          </Card>
        )}

        {queued.length ? (
          <ListSection header="Your imports">
            {queued.map((item) => (
              <ListRow
                key={item.id}
                title={item.file_name}
                subtitle={`${importProgressText(item)} · ${formatRelativeTime(item.created_at)}`}
                onPress={() => router.push({ pathname: '/memories', params: { tab: 'review' } })}
              />
            ))}
          </ListSection>
        ) : hasLoaded && !preview ? (
          <EmptyState
            compact
            icon={FileImportIcon}
            title="No imports yet"
            message="Chats you import show here while their memories are made."
          />
        ) : null}
      </Animated.ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  flex: {
    flex: 1,
  },
  intro: {
    marginHorizontal: ScreenMargin,
    marginBottom: 28,
    gap: 10,
  },
  introButton: {
    marginTop: 6,
  },
  actions: {
    flexDirection: 'row',
    gap: 12,
    marginHorizontal: ScreenMargin,
    marginBottom: 28,
  },
});
