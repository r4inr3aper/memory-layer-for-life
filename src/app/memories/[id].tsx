/**
 * Memory Detail Screen ('/memories/[id]')
 *
 * One memory and why Cooper believes it: the messages it rests on (with the words quoted
 * and a link to the chat while it exists), the people and things it mentions, older
 * versions it replaced, and everything the user did to it. From here the user accepts it,
 * corrects or edits it, marks it as wrong (or restores it), or deletes it.
 *
 * Correcting the text makes a new version, so the screen moves to the new memory.
 */

import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { LockIcon } from '@hugeicons/core-free-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ScreenHeader } from '@/components/common/ScreenHeader';
import { MemoryEditorModal, type MemoryDraft } from '@/components/memories/MemoryEditorModal';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { ApiError, getErrorMessage, isAbortError } from '@/lib/api/client';
import { changeMemoryStatus, deleteMemory, getMemory, updateMemory } from '@/lib/api/memories';
import type { MemoryDetail, UpdateMemoryBody } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { formatRelativeTime } from '@/lib/formatTime';
import { historyText, memoryStatusLabel, memoryTypeLabel } from '@/lib/memories';
import { openChatThread } from '@/lib/navigation';

type Action = 'accept' | 'retract' | 'restore' | 'delete';

export default function MemoryDetailScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
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

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right', 'bottom']}>
      <ScreenHeader title="Memory" fallbackHref="/memories" />

      {status === 'loading' ? (
        <ActivityIndicator style={styles.spinner} color={Colors.primary} />
      ) : status === 'missing' ? (
        <View style={styles.centered}>
          <Text style={styles.emptyTitle}>This memory no longer exists</Text>
          <Text style={styles.emptyText}>It may have been deleted.</Text>
        </View>
      ) : status === 'error' || !memory ? (
        <View style={styles.centered}>
          <Text style={styles.emptyTitle}>{errorMessage}</Text>
          <TouchableOpacity
            style={styles.retryButton}
            onPress={() => {
              setStatus('loading');
              void load();
            }}
            activeOpacity={0.75}>
            <Text style={styles.retryText}>Try again</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => {
                setIsRefreshing(true);
                void load().finally(() => setIsRefreshing(false));
              }}
              tintColor={Colors.primary}
            />
          }>
          <MemorySummary
            memory={memory}
            busy={busy}
            onAccept={() => handleStatus('accept')}
            onRetract={() => handleStatus('retract')}
            onRestore={() => handleStatus('restore')}
            onEdit={() => setIsEditing(true)}
            onDelete={handleDelete}
            onOpenNewer={(newerId) =>
              router.replace({ pathname: '/memories/[id]', params: { id: newerId } })
            }
          />

          <Text style={styles.sectionTitle}>Where this came from</Text>
          {memory.sources.length === 0 ? (
            <Text style={styles.noteText}>
              {memory.created_by === 'user'
                ? 'You wrote this memory yourself.'
                : 'The message it came from is no longer available.'}
            </Text>
          ) : (
            memory.sources.map((source) => (
              <View key={source.raw_message_id} style={styles.sourceCard}>
                {source.evidence_text ? (
                  <Text style={styles.quote}>“{source.evidence_text}”</Text>
                ) : null}
                <Text style={styles.sourceText} numberOfLines={6}>
                  {source.content}
                </Text>
                <View style={styles.sourceFooter}>
                  <Text style={styles.sourceMeta}>
                    {source.sent_at ? `You said this ${formatRelativeTime(source.sent_at)}` : ''}
                  </Text>
                  {source.thread_id ? (
                    <TouchableOpacity
                      onPress={() => openChatThread(source.thread_id!)}
                      activeOpacity={0.7}>
                      <Text style={styles.linkText}>Open the chat</Text>
                    </TouchableOpacity>
                  ) : null}
                </View>
              </View>
            ))
          )}

          {memory.entities.length ? (
            <>
              <Text style={styles.sectionTitle}>Mentions</Text>
              <View style={styles.chipRow}>
                {memory.entities.map((entity) => (
                  <TouchableOpacity
                    key={entity.entity_id}
                    style={styles.chip}
                    onPress={() =>
                      router.push({ pathname: '/people/[id]', params: { id: entity.entity_id } })
                    }
                    activeOpacity={0.75}
                    accessibilityRole="button">
                    <Text style={styles.chipText}>{entity.canonical_name}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </>
          ) : null}

          {memory.replaced.length ? (
            <>
              <Text style={styles.sectionTitle}>Earlier versions</Text>
              {memory.replaced.map((version) => (
                <TouchableOpacity
                  key={version.id}
                  style={styles.versionRow}
                  onPress={() =>
                    router.push({ pathname: '/memories/[id]', params: { id: version.id } })
                  }
                  activeOpacity={0.7}
                  accessibilityRole="button">
                  <Text style={styles.versionText}>{version.content}</Text>
                  <Text style={styles.sourceMeta}>{formatRelativeTime(version.created_at)}</Text>
                </TouchableOpacity>
              ))}
            </>
          ) : null}

          <Text style={styles.sectionTitle}>History</Text>
          <View style={styles.historyRow}>
            <View style={styles.historyDot} />
            <Text style={styles.historyText}>
              {memory.created_by === 'user' ? 'Written' : 'Saved from your chat'}{' '}
              {formatRelativeTime(memory.created_at)}
            </Text>
          </View>
          {memory.history
            .filter((event) => event.action !== 'created')
            .map((event) => (
              <View key={event.id} style={styles.historyRow}>
                <View style={styles.historyDot} />
                <Text style={styles.historyText}>
                  {historyText(event)} · {formatRelativeTime(event.created_at)}
                </Text>
              </View>
            ))}
        </ScrollView>
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
  onRetract,
  onRestore,
  onEdit,
  onDelete,
  onOpenNewer,
}: {
  memory: MemoryDetail;
  busy: Action | null;
  onAccept: () => void;
  onRetract: () => void;
  onRestore: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onOpenNewer: (newerId: string) => void;
}) {
  const isLive = memory.status === 'proposed' || memory.status === 'active';
  return (
    <View style={styles.card}>
      <View style={styles.badgeRow}>
        <View style={[styles.statusPill, styles[`status_${memory.status}`]]}>
          <Text style={styles.statusText}>{memoryStatusLabel(memory.status)}</Text>
        </View>
        <Text style={styles.badgeText}>{memoryTypeLabel(memory.memory_type)}</Text>
        {memory.sensitive ? (
          <View style={styles.sensitiveBadge}>
            <HugeiconsIcon icon={LockIcon} size={12} color={Colors.iconDark} />
            <Text style={styles.badgeText}>Sensitive</Text>
          </View>
        ) : null}
      </View>
      <Text style={styles.memoryText}>{memory.content}</Text>
      {memory.sensitive ? (
        <Text style={styles.noteText}>
          Only you see this. Cooper never uses sensitive memories.
        </Text>
      ) : null}
      {memory.status === 'proposed' ? (
        <Text style={styles.noteText}>
          Cooper saved this from your chat. Accept it if it&apos;s right.
        </Text>
      ) : null}
      {memory.status === 'retracted' ? (
        <Text style={styles.noteText}>
          You marked this as wrong, so Cooper doesn&apos;t use it.
        </Text>
      ) : null}
      {memory.status === 'superseded' ? (
        <View>
          <Text style={styles.noteText}>A newer memory replaced this one.</Text>
          {memory.replaced_by_id ? (
            <TouchableOpacity
              onPress={() => onOpenNewer(memory.replaced_by_id!)}
              activeOpacity={0.7}>
              <Text style={styles.linkText}>See the current one</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      ) : null}

      <View style={styles.actionRow}>
        {memory.status === 'proposed' ? (
          <ActionButton
            label="Accept"
            primary
            busy={busy === 'accept'}
            disabled={busy !== null}
            onPress={onAccept}
          />
        ) : null}
        {isLive ? <ActionButton label="Edit" disabled={busy !== null} onPress={onEdit} /> : null}
        {isLive ? (
          <ActionButton
            label="Wrong"
            busy={busy === 'retract'}
            disabled={busy !== null}
            onPress={onRetract}
          />
        ) : null}
        {memory.status === 'retracted' ? (
          <ActionButton
            label="Restore"
            primary
            busy={busy === 'restore'}
            disabled={busy !== null}
            onPress={onRestore}
          />
        ) : null}
        <ActionButton
          label="Delete"
          danger
          busy={busy === 'delete'}
          disabled={busy !== null}
          onPress={onDelete}
        />
      </View>
    </View>
  );
}

function ActionButton({
  label,
  onPress,
  primary = false,
  danger = false,
  busy = false,
  disabled = false,
}: {
  label: string;
  onPress: () => void;
  primary?: boolean;
  danger?: boolean;
  busy?: boolean;
  disabled?: boolean;
}) {
  return (
    <TouchableOpacity
      style={[
        styles.actionButton,
        primary && styles.actionPrimary,
        danger && styles.actionDanger,
        disabled && !busy && styles.actionDisabled,
      ]}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.8}
      accessibilityRole="button"
      accessibilityState={{ disabled, busy }}>
      {busy ? (
        <ActivityIndicator size="small" color={primary ? Colors.white : Colors.iconDark} />
      ) : (
        <Text
          style={[
            styles.actionText,
            primary && styles.actionTextPrimary,
            danger && styles.actionTextDanger,
          ]}>
          {label}
        </Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  spinner: {
    marginVertical: 24,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  emptyTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
    textAlign: 'center',
  },
  emptyText: {
    marginTop: 6,
    fontSize: 13,
    color: Colors.textSecondary,
    textAlign: 'center',
  },
  retryButton: {
    marginTop: 14,
    paddingHorizontal: 18,
    paddingVertical: 9,
    borderRadius: 18,
    backgroundColor: Colors.primarySubtle,
  },
  retryText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.primary,
  },
  content: {
    padding: 16,
    paddingBottom: 40,
  },
  card: {
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.white,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
  },
  statusPill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
  },
  status_proposed: {
    backgroundColor: Colors.primarySubtle,
  },
  status_active: {
    backgroundColor: Colors.successLight,
  },
  status_superseded: {
    backgroundColor: Colors.surface,
  },
  status_retracted: {
    backgroundColor: Colors.errorLight,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  badgeText: {
    fontSize: 12.5,
    fontWeight: '600',
    color: Colors.textSecondary,
  },
  sensitiveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
    backgroundColor: Colors.warningLight,
  },
  memoryText: {
    marginTop: 12,
    fontSize: 18,
    lineHeight: 25,
    fontWeight: '600',
    color: Colors.iconDark,
    letterSpacing: -0.2,
  },
  noteText: {
    marginTop: 8,
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.textSecondary,
  },
  linkText: {
    marginTop: 6,
    fontSize: 13,
    fontWeight: '600',
    color: Colors.primary,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 16,
  },
  actionButton: {
    minWidth: 76,
    height: 38,
    paddingHorizontal: 14,
    borderRadius: 19,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionPrimary: {
    backgroundColor: Colors.primary,
  },
  actionDanger: {
    backgroundColor: Colors.errorLight,
  },
  actionDisabled: {
    opacity: 0.45,
  },
  actionText: {
    fontSize: 13.5,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  actionTextPrimary: {
    color: Colors.white,
  },
  actionTextDanger: {
    color: Colors.error,
  },
  sectionTitle: {
    marginTop: 22,
    marginBottom: 8,
    fontSize: 12,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  sourceCard: {
    padding: 12,
    borderRadius: 14,
    backgroundColor: Colors.surface,
    marginBottom: 8,
  },
  quote: {
    fontSize: 14.5,
    lineHeight: 20,
    fontWeight: '600',
    color: Colors.iconDark,
    marginBottom: 6,
  },
  sourceText: {
    fontSize: 14,
    lineHeight: 20,
    color: Colors.textPrimary,
  },
  sourceFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 6,
    gap: 8,
  },
  sourceMeta: {
    fontSize: 12,
    color: Colors.textSecondary,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 14,
    backgroundColor: Colors.primarySubtle,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.primary,
  },
  versionRow: {
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  versionText: {
    fontSize: 14,
    lineHeight: 20,
    color: Colors.textSecondary,
    textDecorationLine: 'line-through',
  },
  historyRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    paddingVertical: 6,
  },
  historyDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 6,
    backgroundColor: Colors.border,
  },
  historyText: {
    flex: 1,
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.iconDark,
  },
});
