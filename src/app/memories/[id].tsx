/**
 * Memory Detail Screen ('/memories/[id]')
 *
 * One memory and why Cooper believes it: the messages it rests on (with the words quoted
 * and a link to the chat while it exists), the people and things it mentions, older
 * versions it replaced, and everything the user did to it. From here the user accepts it,
 * corrects or edits it, marks it as wrong (or restores it), or deletes it.
 *
 * Correcting the text makes a new version, so the screen moves to the new memory.
 *
 * Laid out as an iOS detail screen: a large title, the memory in a card with its actions,
 * then inset-grouped sections, and the destructive rows in a section of their own at the
 * end.
 */

import { useCallback, useState } from 'react';
import { ActivityIndicator, RefreshControl, StyleSheet, View } from 'react-native';
import Animated from 'react-native-reanimated';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  AlertCircleIcon,
  Brain01Icon,
  LockIcon,
  Message01Icon,
  PencilEdit02Icon,
} from '@hugeicons/core-free-icons';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import {
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
import { MemoryEditorModal, type MemoryDraft } from '@/components/memories/MemoryEditorModal';
import { CellPressable, EntityAvatar, memoryKind } from '@/components/memories/MemoryRow';
import { Colors } from '@/constants/colors';
import { Radius, ScreenMargin } from '@/constants/theme';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { ApiError, getErrorMessage, isAbortError } from '@/lib/api/client';
import { changeMemoryStatus, deleteMemory, getMemory, updateMemory } from '@/lib/api/memories';
import type { MemoryDetail, MemorySource, MemoryStatus, UpdateMemoryBody } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { formatRelativeTime } from '@/lib/formatTime';
import { haptic } from '@/lib/haptics';
import { historyText, memoryStatusLabel, memoryTypeLabel } from '@/lib/memories';
import { openChatThread } from '@/lib/navigation';

type Action = 'accept' | 'retract' | 'restore' | 'delete';

// The status tag: a soft wash of the status color behind its label.
const STATUS_COLORS: Record<MemoryStatus, { background: string; foreground: string }> = {
  proposed: { background: Colors.tintFill, foreground: Colors.tint },
  active: { background: Colors.successLight, foreground: Colors.systemGreen },
  superseded: { background: Colors.tertiaryFill, foreground: Colors.secondaryLabel },
  retracted: { background: Colors.errorLight, foreground: Colors.systemRed },
};

export default function MemoryDetailScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { scrollY, onScroll } = useScrollY();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [memory, setMemory] = useState<MemoryDetail | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [busy, setBusy] = useState<Action | null>(null);
  const [isEditing, setIsEditing] = useState(false);

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!id) return Promise.resolve();
      return getMemory(id, signal)
        .then((loaded) => {
          setMemory(loaded);
          setStatus('ready');
        })
        .catch((error) => {
          if (isAbortError(error, signal)) return;
          if (error instanceof ApiError && error.status === 404) {
            setStatus('missing');
            return;
          }
          console.error('Failed to load the memory:', error);
          setErrorMessage(getErrorMessage(error, 'Could not load this memory'));
          setStatus((current) => (current === 'ready' ? current : 'error'));
        });
    },
    [id]
  );

  useFocusEffect(
    useCallback(() => {
      if (!hasSession) return undefined;
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [hasSession, load])
  );

  const act = async (action: Action, work: () => Promise<void>) => {
    if (busy) return;
    setBusy(action);
    try {
      await work();
    } catch (error) {
      showToast(getErrorMessage(error, 'Something went wrong'), 3500);
    } finally {
      setBusy(null);
    }
  };

  const handleStatus = (action: 'accept' | 'retract' | 'restore') =>
    act(action, async () => {
      if (!memory) return;
      await changeMemoryStatus(memory.id, action);
      await load();
      showToast(
        action === 'accept' ? 'Accepted' : action === 'retract' ? 'Marked as wrong' : 'Restored'
      );
    });

  const handleDelete = () =>
    act('delete', async () => {
      if (!memory) return;
      const older = memory.replaced.length;
      const confirmed = await confirmAsync({
        title: 'Delete this memory?',
        message:
          (older
            ? `This memory and ${older === 1 ? 'the older version' : `${older} older versions`} ` +
              'it replaced will be deleted, with their history. '
            : 'This memory and its history will be deleted. ') +
          "Cooper won't use it again. Your chat messages stay. This can't be undone.",
        confirmText: 'Delete',
        destructive: true,
      });
      if (!confirmed) return;
      await deleteMemory(memory.id);
      showToast('Memory deleted');
      if (router.canGoBack()) router.back();
      else router.replace('/memories');
    });

  const handleEditSubmit = async (draft: MemoryDraft) => {
    if (!memory) return;
    const body: UpdateMemoryBody = {};
    if (draft.content !== memory.content) body.content = draft.content;
    if (draft.memory_type !== memory.memory_type) body.memory_type = draft.memory_type;
    if (draft.sensitive !== memory.sensitive) body.sensitive = draft.sensitive;
    if (Object.keys(body).length === 0) {
      setIsEditing(false);
      return;
    }
    const saved = await updateMemory(memory.id, body);
    setIsEditing(false);
    if (saved.id !== memory.id) {
      showToast('Corrected. The old version is kept in its history.');
      router.replace({ pathname: '/memories/[id]', params: { id: saved.id } });
      return;
    }
    showToast('Saved');
    await load();
  };

  if (!hasSession) {
    return <View style={styles.safeArea} />;
  }

  const isReady = status !== 'loading' && status !== 'missing' && status !== 'error' && memory;

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      {/* The bar shows its small title at once until there is a large one to scroll away. */}
      <ScreenHeader title="Memory" fallbackHref="/memories" scrollY={isReady ? scrollY : undefined} />

      {status === 'loading' ? (
        <ActivityIndicator style={styles.spinner} color={Colors.systemGray} />
      ) : status === 'missing' ? (
        <View style={styles.centered}>
          <EmptyState
            icon={Brain01Icon}
            title="This memory no longer exists"
            message="It may have been deleted."
          />
        </View>
      ) : status === 'error' || !memory ? (
        <View style={styles.centered}>
          <EmptyState
            icon={AlertCircleIcon}
            title={errorMessage}
            actionTitle="Try again"
            onAction={() => {
              setStatus('loading');
              void load();
            }}
          />
        </View>
      ) : (
        <Animated.ScrollView
          onScroll={onScroll}
          scrollEventThrottle={16}
          contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => {
                setIsRefreshing(true);
                void load().finally(() => setIsRefreshing(false));
              }}
              tintColor={Colors.systemGray}
            />
          }>
          <LargeTitle title="Memory" />

          <MemorySummary
            memory={memory}
            busy={busy}
            onAccept={() => handleStatus('accept')}
            onRestore={() => handleStatus('restore')}
            onEdit={() => setIsEditing(true)}
            onOpenNewer={(newerId) =>
              router.replace({ pathname: '/memories/[id]', params: { id: newerId } })
            }
          />

          <ListSection header="Where this came from">
            {memory.sources.length === 0 ? (
              <ListRow
                icon={memory.created_by === 'user' ? PencilEdit02Icon : Message01Icon}
                iconColor={Colors.systemGray}
                title={
                  memory.created_by === 'user'
                    ? 'You wrote this memory yourself.'
                    : 'The message it came from is no longer available.'
                }
                numberOfLines={3}
              />
            ) : (
              memory.sources.map((source) => <SourceCell key={source.raw_message_id} source={source} />)
            )}
          </ListSection>

          {memory.entities.length ? (
            <ListSection header="Mentions">
              {memory.entities.map((entity) => (
                <ListRow
                  key={entity.entity_id}
                  leading={<EntityAvatar type={entity.entity_type} name={entity.canonical_name} />}
                  title={entity.canonical_name}
                  onPress={() =>
                    router.push({ pathname: '/people/[id]', params: { id: entity.entity_id } })
                  }
                />
              ))}
            </ListSection>
          ) : null}

          {memory.replaced.length ? (
            <ListSection header="Earlier versions">
              {memory.replaced.map((version) => (
                <ListRow
                  key={version.id}
                  title={version.content}
                  subtitle={formatRelativeTime(version.created_at)}
                  numberOfLines={3}
                  onPress={() =>
                    router.push({ pathname: '/memories/[id]', params: { id: version.id } })
                  }
                />
              ))}
            </ListSection>
          ) : null}

          <ListSection header="History">
            <ListRow
              title={memory.created_by === 'user' ? 'Written' : 'Saved from your chat'}
              subtitle={formatRelativeTime(memory.created_at)}
            />
            {memory.history
              .filter((event) => event.action !== 'created')
              .map((event) => (
                <ListRow
                  key={event.id}
                  title={historyText(event)}
                  subtitle={formatRelativeTime(event.created_at)}
                  numberOfLines={2}
                />
              ))}
          </ListSection>

          <ListSection
            footer={
              memory.status === 'proposed' || memory.status === 'active'
                ? 'Cooper stops using a memory marked as wrong. You can restore it later.'
                : undefined
            }>
            {memory.status === 'proposed' || memory.status === 'active' ? (
              <ListRow
                title="Mark as wrong"
                destructive
                disabled={busy !== null && busy !== 'retract'}
                accessory={busy === 'retract' ? <ActivityIndicator color={Colors.systemGray} /> : 'none'}
                onPress={
                  busy === 'retract'
                    ? undefined
                    : () => {
                        haptic.light();
                        void handleStatus('retract');
                      }
                }
              />
            ) : null}
            <ListRow
              title="Delete memory"
              destructive
              disabled={busy !== null && busy !== 'delete'}
              accessory={busy === 'delete' ? <ActivityIndicator color={Colors.systemGray} /> : 'none'}
              onPress={busy === 'delete' ? undefined : handleDelete}
            />
          </ListSection>
        </Animated.ScrollView>
      )}

      {memory ? (
        <MemoryEditorModal
          visible={isEditing}
          title="Edit memory"
          confirmText="Save"
          initial={{
            content: memory.content,
            memory_type: memory.memory_type,
            sensitive: memory.sensitive,
          }}
          hint="Changing the words saves a new version; the old one stays in the history."
          onClose={() => setIsEditing(false)}
          onSubmit={handleEditSubmit}
        />
      ) : null}
    </SafeAreaView>
  );
}

function MemorySummary({
  memory,
  busy,
  onAccept,
  onRestore,
  onEdit,
  onOpenNewer,
}: {
  memory: MemoryDetail;
  busy: Action | null;
  onAccept: () => void;
  onRestore: () => void;
  onEdit: () => void;
  onOpenNewer: (newerId: string) => void;
}) {
  const isLive = memory.status === 'proposed' || memory.status === 'active';
  const kind = memoryKind(memory.memory_type);
  const tag = STATUS_COLORS[memory.status];
  const note =
    memory.status === 'proposed'
      ? "Cooper saved this from your chat. Accept it if it's right."
      : memory.status === 'retracted'
        ? "You marked this as wrong, so Cooper doesn't use it."
        : memory.status === 'superseded'
          ? 'A newer memory replaced this one.'
          : null;
  // Keep the pressed button showing its spinner at full strength; dim only the others.
  const dimmed = (action: Action) => busy !== null && busy !== action;

  return (
    <Card style={styles.summary}>
      <View style={styles.summaryTop}>
        <IconTile icon={kind.icon} color={kind.color} size={26} />
        <AppText variant="subheadline" weight="600" style={styles.flexShrink} numberOfLines={1}>
          {memoryTypeLabel(memory.memory_type)}
        </AppText>
        <View style={[styles.tag, { backgroundColor: tag.background }]}>
          <AppText variant="caption1" weight="600" color={tag.foreground}>
            {memoryStatusLabel(memory.status)}
          </AppText>
        </View>
        {memory.sensitive ? (
          <View style={styles.sensitive}>
            <HugeiconsIcon icon={LockIcon} size={12} color={Colors.secondaryLabel} strokeWidth={2} />
            <AppText variant="caption1" weight="600" color="secondary">
              Sensitive
            </AppText>
          </View>
        ) : null}
      </View>

      <AppText variant="title3" selectable style={styles.memoryText}>
        {memory.content}
      </AppText>

      {memory.sensitive ? (
        <AppText variant="footnote" color="secondary" style={styles.note}>
          Only you see this. Cooper never uses sensitive memories.
        </AppText>
      ) : null}
      {note ? (
        <AppText variant="footnote" color="secondary" style={styles.note}>
          {note}
        </AppText>
      ) : null}
      {memory.status === 'superseded' && memory.replaced_by_id ? (
        <Button
          title="See the current one"
          variant="plain"
          size="small"
          onPress={() => onOpenNewer(memory.replaced_by_id!)}
          containerStyle={styles.linkButton}
        />
      ) : null}

      {isLive || memory.status === 'retracted' ? (
        <View style={styles.actionRow}>
          {memory.status === 'proposed' ? (
            <Button
              title="Accept"
              variant="filled"
              size="small"
              haptic="success"
              loading={busy === 'accept'}
              disabled={dimmed('accept')}
              onPress={onAccept}
            />
          ) : null}
          {isLive ? (
            <Button title="Edit" variant="gray" size="small" disabled={busy !== null} onPress={onEdit} />
          ) : null}
          {memory.status === 'retracted' ? (
            <Button
              title="Restore"
              variant="tinted"
              size="small"
              loading={busy === 'restore'}
              disabled={dimmed('restore')}
              onPress={onRestore}
            />
          ) : null}
        </View>
      ) : null}
    </Card>
  );
}

/** A message the memory rests on: the words quoted, the message, and when it was said. */
function SourceCell({ source }: { source: MemorySource }) {
  const threadId = source.thread_id;
  const body = (
    <>
      {source.evidence_text ? (
        <AppText variant="body" weight="600">
          “{source.evidence_text}”
        </AppText>
      ) : null}
      <AppText
        variant="subheadline"
        color={source.evidence_text ? 'secondary' : 'primary'}
        numberOfLines={6}>
        {source.content}
      </AppText>
      <View style={styles.sourceFooter}>
        <AppText variant="footnote" color="secondary" style={styles.flexShrink}>
          {source.sent_at ? `You said this ${formatRelativeTime(source.sent_at)}` : ''}
        </AppText>
        {threadId ? (
          <AppText variant="footnote" weight="600" color="tint">
            Open the chat
          </AppText>
        ) : null}
      </View>
    </>
  );
  if (!threadId) {
    return <View style={styles.sourceCell}>{body}</View>;
  }
  return (
    <CellPressable onPress={() => openChatThread(threadId)} style={styles.sourceCell}>
      {body}
    </CellPressable>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  flexShrink: {
    flexShrink: 1,
  },
  spinner: {
    marginVertical: 24,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    paddingBottom: 60,
  },
  summary: {
    marginHorizontal: ScreenMargin,
    marginBottom: 28,
  },
  summaryTop: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
  },
  tag: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: Radius.pill,
  },
  sensitive: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  memoryText: {
    marginTop: 12,
  },
  note: {
    marginTop: 8,
  },
  linkButton: {
    alignSelf: 'flex-start',
    marginTop: 4,
    marginLeft: -4,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 16,
  },
  sourceCell: {
    gap: 4,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  sourceFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    marginTop: 2,
  },
});
