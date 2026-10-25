/**
 * Person Screen ('/people/[id]')
 *
 * A person, place, or thing from the user's memories: their name and other names, and
 * the memories that mention them. When Cooper got them wrong, the user renames them (the
 * old name keeps matching later messages) or merges in someone who is the same person.
 */

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { ScreenHeader } from '@/components/common/ScreenHeader';
import { MemoryRow } from '@/components/memories/MemoryRow';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { ApiError, getErrorMessage, isAbortError } from '@/lib/api/client';
import { getPerson, listPeople, mergePeople, renamePerson } from '@/lib/api/memories';
import type { Person, PersonDetail } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { formatRelativeTime } from '@/lib/formatTime';

const NAME_MAX_LENGTH = 200;

export default function PersonScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [person, setPerson] = useState<PersonDetail | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [sheet, setSheet] = useState<'rename' | 'merge' | null>(null);

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!id) return Promise.resolve();
      return getPerson(id, signal)
        .then((loaded) => {
          setPerson(loaded);
          setStatus('ready');
        })
        .catch((error) => {
          if (isAbortError(error, signal)) return;
          if (error instanceof ApiError && error.status === 404) {
            setStatus('missing');
            return;
          }
          setErrorMessage(getErrorMessage(error, 'Could not load this person'));
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

  if (!hasSession) {
    return <View style={styles.safeArea} />;
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right', 'bottom']}>
      <ScreenHeader title={person?.name ?? 'Person'} fallbackHref="/memories" />

      {status === 'loading' ? (
        <ActivityIndicator style={styles.spinner} color={Colors.primary} />
      ) : status === 'missing' ? (
        <View style={styles.centered}>
          <Text style={styles.emptyTitle}>Not found</Text>
          <Text style={styles.emptyText}>They may have been merged or deleted.</Text>
        </View>
      ) : status === 'error' || !person ? (
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
        <FlatList
          data={person.memories}
          keyExtractor={(memory) => memory.id}
          contentContainerStyle={styles.listContent}
          ListHeaderComponent={
            <View>
              <View style={styles.card}>
                <Text style={styles.name}>{person.name}</Text>
                <Text style={styles.meta}>
                  {person.memory_count === 1 ? '1 memory' : `${person.memory_count} memories`}
                  {person.last_seen_at
                    ? ` · last mentioned ${formatRelativeTime(person.last_seen_at)}`
                    : ''}
                </Text>
                {person.aliases.length ? (
                  <Text style={styles.meta}>Also called {person.aliases.join(', ')}</Text>
                ) : null}
                <View style={styles.actionRow}>
                  <TouchableOpacity
                    style={styles.actionButton}
                    onPress={() => setSheet('rename')}
                    activeOpacity={0.8}
                    accessibilityRole="button">
                    <Text style={styles.actionText}>Rename</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.actionButton}
                    onPress={() => setSheet('merge')}
                    activeOpacity={0.8}
                    accessibilityRole="button">
                    <Text style={styles.actionText}>Same person as…</Text>
                  </TouchableOpacity>
                </View>
              </View>
              <Text style={styles.sectionTitle}>Memories</Text>
            </View>
          }
          renderItem={({ item }) => (
            <MemoryRow
              memory={item}
              onPress={() => router.push({ pathname: '/memories/[id]', params: { id: item.id } })}
            />
          )}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          ListEmptyComponent={
            <Text style={styles.emptyText}>No current memories mention them.</Text>
          }
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => {
                setIsRefreshing(true);
                void load().finally(() => setIsRefreshing(false));
              }}
              tintColor={Colors.primary}
            />
          }
        />
      )}

      {person ? (
        <>
          <RenameSheet
            visible={sheet === 'rename'}
            name={person.name}
            onClose={() => setSheet(null)}
            onSave={async (name) => {
              setPerson(await renamePerson(person.id, name));
              setSheet(null);
              showToast('Renamed');
            }}
          />
          <MergeSheet
            visible={sheet === 'merge'}
            person={person}
            onClose={() => setSheet(null)}
            onMerge={async (other) => {
              const confirmed = await confirmAsync({
                title: `Merge ${other.name} into ${person.name}?`,
                message:
                  `Memories about ${other.name} will be about ${person.name}, and ` +
                  `"${other.name}" becomes another name for them.`,
                confirmText: 'Merge',
              });
              if (!confirmed) return;
              setPerson(await mergePeople(person.id, other.id));
              setSheet(null);
              showToast('Merged');
            }}
          />
        </>
      ) : null}
    </SafeAreaView>
  );
}

function Sheet({
  visible,
  title,
  onClose,
  children,
}: {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.overlay}>
          <TouchableWithoutFeedback onPress={onClose}>
            <View style={styles.backdrop} />
          </TouchableWithoutFeedback>
          <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]}>
            <Text style={styles.sheetTitle}>{title}</Text>
            {children}
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function RenameSheet({
  visible,
  name,
  onClose,
  onSave,
}: {
  visible: boolean;
  name: string;
  onClose: () => void;
  onSave: (name: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible) {
      setDraft(name);
      setError(null);
    }
  }

  const save = async () => {
    const text = draft.trim();
    if (!text) {
      setError('Enter a name.');
      return;
    }
    setIsSaving(true);
    try {
      await onSave(text);
    } catch (saveError) {
      setError(getErrorMessage(saveError, 'Could not rename'));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Sheet visible={visible} title="Rename" onClose={onClose}>
      <TextInput
        style={[styles.input, error && styles.inputError]}
        value={draft}
        onChangeText={(text) => {
          setDraft(text);
          setError(null);
        }}
        maxLength={NAME_MAX_LENGTH}
        autoFocus={Platform.OS !== 'web'}
        returnKeyType="done"
        onSubmitEditing={save}
        accessibilityLabel="Name"
      />
      <Text style={error ? styles.errorText : styles.hintText}>
        {error ?? 'The old name keeps working when you mention it in chat.'}
      </Text>
      <View style={styles.sheetActions}>
        <TouchableOpacity style={styles.cancelBtn} onPress={onClose} disabled={isSaving}>
          <Text style={styles.cancelText}>Cancel</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.saveBtn} onPress={save} disabled={isSaving}>
          {isSaving ? (
            <ActivityIndicator size="small" color={Colors.white} />
          ) : (
            <Text style={styles.saveText}>Save</Text>
          )}
        </TouchableOpacity>
      </View>
    </Sheet>
  );
}

function MergeSheet({
  visible,
  person,
  onClose,
  onMerge,
}: {
  visible: boolean;
  person: PersonDetail;
  onClose: () => void;
  onMerge: (other: Person) => Promise<void>;
}) {
  const [others, setOthers] = useState<Person[] | null>(null);
  const [isMerging, setIsMerging] = useState(false);

  // The people of the same kind to choose from, each time the sheet opens.
  useEffect(() => {
    if (!visible) return undefined;
    const controller = new AbortController();
    listPeople({ entity_type: person.entity_type, limit: 200, offset: 0 }, controller.signal)
      .then((page) => setOthers(page.items.filter((item) => item.id !== person.id)))
      .catch((error) => {
        if (isAbortError(error, controller.signal)) return;
        showToast(getErrorMessage(error, 'Could not load people'));
        setOthers([]);
      });
    return () => {
      controller.abort();
      setOthers(null);
    };
  }, [visible, person.id, person.entity_type]);

  return (
    <Sheet visible={visible} title={`Who else is ${person.name}?`} onClose={onClose}>
      {others === null || isMerging ? (
        <ActivityIndicator style={styles.spinner} color={Colors.primary} />
      ) : others.length === 0 ? (
        <Text style={styles.hintText}>There is nobody else to merge with.</Text>
      ) : (
        <FlatList
          style={styles.mergeList}
          data={others}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => (
            <TouchableOpacity
              style={styles.mergeRow}
              onPress={async () => {
                setIsMerging(true);
                try {
                  await onMerge(item);
                } catch (error) {
                  showToast(getErrorMessage(error, 'Could not merge'), 3500);
                } finally {
                  setIsMerging(false);
                }
              }}
              activeOpacity={0.7}
              accessibilityRole="button">
              <Text style={styles.mergeName}>{item.name}</Text>
              <Text style={styles.meta}>
                {item.memory_count === 1 ? '1 memory' : `${item.memory_count} memories`}
              </Text>
            </TouchableOpacity>
          )}
        />
      )}
      <TouchableOpacity style={[styles.cancelBtn, styles.closeFull]} onPress={onClose}>
        <Text style={styles.cancelText}>Close</Text>
      </TouchableOpacity>
    </Sheet>
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
    fontSize: 13.5,
    color: Colors.textSecondary,
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
  listContent: {
    padding: 16,
    paddingBottom: 40,
  },
  card: {
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  name: {
    fontSize: 20,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.3,
  },
  meta: {
    marginTop: 4,
    fontSize: 13,
    color: Colors.textSecondary,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 14,
  },
  actionButton: {
    height: 38,
    paddingHorizontal: 14,
    borderRadius: 19,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionText: {
    fontSize: 13.5,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  sectionTitle: {
    marginTop: 22,
    marginBottom: 4,
    fontSize: 12,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  separator: {
    height: 1,
    backgroundColor: Colors.borderLight,
  },
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: Colors.overlay,
  },
  sheet: {
    maxHeight: '80%',
    backgroundColor: Colors.white,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingTop: 18,
    paddingHorizontal: 20,
  },
  sheetTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: Colors.iconDark,
    marginBottom: 12,
  },
  input: {
    backgroundColor: Colors.surfaceInput,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    color: Colors.iconDark,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
  },
  inputError: {
    borderColor: Colors.error,
  },
  hintText: {
    marginTop: 6,
    fontSize: 12.5,
    lineHeight: 17,
    color: Colors.textSecondary,
  },
  errorText: {
    marginTop: 6,
    fontSize: 12.5,
    color: Colors.error,
  },
  sheetActions: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 16,
  },
  cancelBtn: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeFull: {
    flex: 0,
    marginTop: 12,
  },
  cancelText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  saveBtn: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.white,
  },
  mergeList: {
    maxHeight: 360,
  },
  mergeRow: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  mergeName: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
  },
});
