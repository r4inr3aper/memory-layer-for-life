/**
 * Person Screen ('/people/[id]')
 *
 * A person, place, or thing from the user's memories: their name and other names, and
 * the memories that mention them. When Cooper got them wrong, the user renames them (the
 * old name keeps matching later messages) or merges in someone who is the same person.
 *
 * Their name is the large title; Rename and "Same person as…" are rows above the memories,
 * and each opens a sheet.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  RefreshControl,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import Animated from 'react-native-reanimated';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import {
  AlertCircleIcon,
  Brain01Icon,
  PencilEdit02Icon,
  UserGroupIcon,
  UserSwitchIcon,
} from '@hugeicons/core-free-icons';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  AppText,
  BottomSheet,
  EmptyState,
  LargeTitle,
  ListRow,
  ListSection,
  ScreenHeader,
  useScrollY,
} from '@/components/ui';
import {
  EntityAvatar,
  InsetCell,
  InsetGroupHeader,
  LEADING_INSET,
  MemoryRow,
} from '@/components/memories/MemoryRow';
import { Colors } from '@/constants/colors';
import { Typography } from '@/constants/theme';
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
  const insets = useSafeAreaInsets();
  const { scrollY, onScroll } = useScrollY();
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

  const isReady = status !== 'loading' && status !== 'missing' && status !== 'error' && person;

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      {/* The bar shows its small title at once until there is a large one to scroll away. */}
      <ScreenHeader
        title={person?.name ?? 'Person'}
        fallbackHref="/memories"
        scrollY={isReady ? scrollY : undefined}
      />

      {status === 'loading' ? (
        <ActivityIndicator style={styles.spinner} color={Colors.systemGray} />
      ) : status === 'missing' ? (
        <View style={styles.centered}>
          <EmptyState
            icon={UserGroupIcon}
            title="Not found"
            message="They may have been merged or deleted."
          />
        </View>
      ) : status === 'error' || !person ? (
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
        <Animated.FlatList
          data={person.memories}
          keyExtractor={(memory) => memory.id}
          onScroll={onScroll}
          scrollEventThrottle={16}
          contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}
          ListHeaderComponent={
            <View>
              <LargeTitle
                title={person.name}
                subtitle={
                  (person.memory_count === 1 ? '1 memory' : `${person.memory_count} memories`) +
                  (person.last_seen_at
                    ? ` · last mentioned ${formatRelativeTime(person.last_seen_at)}`
                    : '')
                }
              />
              <ListSection
                footer={
                  person.aliases.length ? `Also called ${person.aliases.join(', ')}` : undefined
                }>
                <ListRow
                  icon={PencilEdit02Icon}
                  iconColor={Colors.systemBlue}
                  title="Rename"
                  onPress={() => setSheet('rename')}
                />
                <ListRow
                  icon={UserSwitchIcon}
                  iconColor={Colors.systemIndigo}
                  title="Same person as…"
                  onPress={() => setSheet('merge')}
                />
              </ListSection>
              <InsetGroupHeader title="Memories" />
            </View>
          }
          renderItem={({ item, index }) => (
            <InsetCell first={index === 0} last={index === person.memories.length - 1} inset={LEADING_INSET}>
              <MemoryRow
                memory={item}
                onPress={() => router.push({ pathname: '/memories/[id]', params: { id: item.id } })}
              />
            </InsetCell>
          )}
          ListEmptyComponent={
            <EmptyState compact icon={Brain01Icon} title="No memories" message="No current memories mention them." />
          }
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => {
                setIsRefreshing(true);
                void load().finally(() => setIsRefreshing(false));
              }}
              tintColor={Colors.systemGray}
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
    <BottomSheet
      visible={visible}
      onClose={onClose}
      title="Rename"
      leftAction={{ label: 'Cancel', onPress: onClose, disabled: isSaving }}
      rightAction={{ label: 'Save', onPress: save, loading: isSaving }}>
      <ListSection
        footer={
          error ? (
            <AppText variant="footnote" color="destructive">
              {error}
            </AppText>
          ) : (
            'The old name keeps working when you mention it in chat.'
          )
        }>
        <TextInput
          style={styles.input}
          value={draft}
          onChangeText={(text) => {
            setDraft(text);
            setError(null);
          }}
          placeholder="Name"
          placeholderTextColor={Colors.placeholder}
          selectionColor={Colors.tint}
          clearButtonMode="while-editing"
          maxLength={NAME_MAX_LENGTH}
          autoFocus={Platform.OS !== 'web'}
          returnKeyType="done"
          onSubmitEditing={save}
          accessibilityLabel="Name"
        />
      </ListSection>
    </BottomSheet>
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
    <BottomSheet
      visible={visible}
      onClose={onClose}
      title="Same person as…"
      leftAction={{ label: 'Cancel', onPress: onClose }}
      scrollable>
      {others === null || isMerging ? (
        <ActivityIndicator style={styles.spinner} color={Colors.systemGray} />
      ) : others.length === 0 ? (
        <EmptyState compact icon={UserGroupIcon} title="Nobody else to merge with" />
      ) : (
        <ListSection header={`Who else is ${person.name}?`}>
          {others.map((item) => (
            <ListRow
              key={item.id}
              leading={<EntityAvatar type={item.entity_type} name={item.name} />}
              title={item.name}
              subtitle={item.memory_count === 1 ? '1 memory' : `${item.memory_count} memories`}
              accessory="none"
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
            />
          ))}
        </ListSection>
      )}
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  spinner: {
    marginVertical: 24,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    paddingBottom: 60,
  },
  // A single-line field takes the body size without its line height, which would push the
  // text off center on iOS.
  input: {
    fontSize: Typography.body.fontSize,
    letterSpacing: Typography.body.letterSpacing,
    height: 48,
    paddingHorizontal: 16,
    paddingVertical: 0,
    color: Colors.label,
  },
});
