/**
 * Memories Screen ('/memories')
 *
 * What Cooper remembers about the user, in three tabs:
 *
 * - All: memories that may still be true, newest first and grouped by when they were
 *   saved, with search (words, names, and meaning) and the switch for saving chats as
 *   memories.
 * - To review: memories waiting to be accepted, pairs that look like duplicates or
 *   conflicts, and messages Cooper held back.
 * - People: the people, places, and things the memories mention.
 *
 * "+" writes a memory by hand. Everything reloads when the screen is shown again, so
 * changes made on a memory's own screen appear here.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Modal,
  RefreshControl,
  SectionList,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { PlusSignIcon, Search01Icon } from '@hugeicons/core-free-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ScreenHeader } from '@/components/common/ScreenHeader';
import { MemoryEditorModal, type MemoryDraft } from '@/components/memories/MemoryEditorModal';
import { MemoryRow } from '@/components/memories/MemoryRow';
import {
  HeldBackCard,
  SuggestionCard,
  type SuggestionChoice,
} from '@/components/memories/ReviewCards';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { getMe, updateMe } from '@/lib/api/me';
import {
  acceptMemories,
  changeMemoryStatus,
  createMemory,
  dismissHeldBack,
  dismissSuggestion,
  getReviewInbox,
  keepMemory,
  listMyMemories,
  listPeople,
  MAX_MEMORY_SEARCH_RESULTS,
  saveHeldBack,
  searchMyMemories,
} from '@/lib/api/memories';
import type {
  HeldBack,
  MemoryItem,
  MemorySuggestion,
  MessageHit,
  Person,
  ReviewInbox,
} from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';
import { groupMemoriesByTime, heldBackDraft, memoryTypeLabel } from '@/lib/memories';
import { openChatThread } from '@/lib/navigation';
import { searchMessages } from '@/lib/api/life';
import { memoryFromFile } from '@/lib/api/sources';
import { pickAttachments } from '@/lib/attachmentPicker';
import { snippetParts } from '@/lib/life';

const PAGE_SIZE = 30;
const SEARCH_DELAY_MS = 350;
const ACCEPT_ALL_LIMIT = 100;

type Tab = 'all' | 'review' | 'people';

type Editor = { kind: 'create' } | { kind: 'held'; heldBack: HeldBack };

const ADD_OPTIONS = [
  { key: 'write', label: 'Write a memory', hint: 'Something for Cooper to know.' },
  { key: 'file', label: 'From a photo or PDF', hint: 'A receipt, a note, a document.' },
  { key: 'import', label: 'Import a WhatsApp chat', hint: 'Bring an exported chat in.' },
] as const;

const NEW_DRAFT: MemoryDraft = { content: '', memory_type: 'note', sensitive: false };

function suggestionKey(suggestion: MemorySuggestion): string {
  return `${suggestion.first.id}:${suggestion.second.id}`;
}

export default function MemoriesScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const params = useLocalSearchParams<{ tab?: string }>();
  const [tab, setTab] = useState<Tab>(
    params.tab === 'review' || params.tab === 'people' ? params.tab : 'all'
  );

  const [captureEnabled, setCaptureEnabled] = useState<boolean | null>(null);
  const [isSavingSetting, setIsSavingSetting] = useState(false);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [inbox, setInbox] = useState<ReviewInbox | null>(null);
  const [proposed, setProposed] = useState<MemoryItem[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  // Ids of memories, suggestions, and held-back messages with an action in flight.
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [isAcceptingAll, setIsAcceptingAll] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [isAddMenuOpen, setIsAddMenuOpen] = useState(false);
  const [isReadingFiles, setIsReadingFiles] = useState(false);

  const [query, setQuery] = useState('');
  const [search, setSearch] = useState<{ text: string; items: MemoryItem[] } | null>(null);
  // Search memories, or the chats themselves.
  const [searchIn, setSearchIn] = useState<'memories' | 'chats'>('memories');
  const [chatSearch, setChatSearch] = useState<{ text: string; items: MessageHit[] } | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    return Promise.all([
      getMe(signal),
      listMyMemories({ limit: PAGE_SIZE, offset: 0 }, signal),
      getReviewInbox(signal),
      listMyMemories({ status: ['proposed'], limit: PAGE_SIZE, offset: 0 }, signal),
      listPeople({ limit: 100, offset: 0 }, signal),
    ])
      .then(([me, page, review, toReview, found]) => {
        setCaptureEnabled(me.memory_capture_enabled);
        setMemories(page.items);
        setTotal(page.total);
        setInbox(review);
        setProposed(toReview.items);
        setPeople(found.items);
        setError(null);
        setHasLoaded(true);
      })
      .catch((loadError) => {
        if (isAbortError(loadError, signal)) return;
        console.error('Failed to load memories:', loadError);
        setError(getErrorMessage(loadError, "Couldn't load your memories"));
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

  // Search as the user types, a moment after they stop. Results belong to the text they
  // were found for, so typing more shows the spinner until the new results arrive.
  const searchText = query.trim();
  useEffect(() => {
    if (!searchText) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      if (searchIn === 'chats') {
        searchMessages(searchText, 30, controller.signal)
          .then((items) => setChatSearch({ text: searchText, items }))
          .catch((searchError) => {
            if (isAbortError(searchError, controller.signal)) return;
            showToast(getErrorMessage(searchError, 'Search failed'));
            setChatSearch({ text: searchText, items: [] });
          });
        return;
      }
      searchMyMemories(searchText, MAX_MEMORY_SEARCH_RESULTS, controller.signal)
        .then((result) =>
          setSearch({ text: searchText, items: result.items.map((hit) => hit.memory) })
        )
        .catch((searchError) => {
          if (isAbortError(searchError, controller.signal)) return;
          showToast(getErrorMessage(searchError, 'Search failed'));
          setSearch({ text: searchText, items: [] });
        });
    }, SEARCH_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [searchText, searchIn]);
  const results = searchText && search?.text === searchText ? search.items : null;
  const chatResults = searchText && chatSearch?.text === searchText ? chatSearch.items : null;
  const isSearching =
    Boolean(searchText) &&
    (searchIn === 'chats' ? chatSearch?.text !== searchText : search?.text !== searchText);

  const sections = useMemo(() => groupMemoriesByTime(memories), [memories]);
  const reviewCount =
    (inbox?.proposed_count ?? 0) + (inbox?.suggestions.length ?? 0) + (inbox?.held_back_count ?? 0);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await load();
    setIsRefreshing(false);
  };

  const handleLoadMore = async () => {
    if (isLoadingMore || !hasLoaded || memories.length >= total || results !== null) return;
    setIsLoadingMore(true);
    try {
      const page = await listMyMemories({ limit: PAGE_SIZE, offset: memories.length });
      setMemories((previous) => {
        const known = new Set(previous.map((memory) => memory.id));
        return [...previous, ...page.items.filter((memory) => !known.has(memory.id))];
      });
      setTotal(page.total);
    } catch (loadError) {
      showToast(getErrorMessage(loadError, "Couldn't load more memories"));
    } finally {
      setIsLoadingMore(false);
    }
  };

  const handleToggleCapture = async (nextValue: boolean) => {
    if (isSavingSetting || captureEnabled === null) return;
    const previousValue = captureEnabled;
    setCaptureEnabled(nextValue);
    setIsSavingSetting(true);
    try {
      const me = await updateMe({ memory_capture_enabled: nextValue });
      setCaptureEnabled(me.memory_capture_enabled);
      showToast(nextValue ? 'Chats will become memories' : 'Chats will no longer become memories');
    } catch (saveError) {
      setCaptureEnabled(previousValue);
      showToast(getErrorMessage(saveError, 'Could not save your choice'));
    } finally {
      setIsSavingSetting(false);
    }
  };

  /** Runs one review action for an item, then reloads everything it may have changed. */
  const act = async (key: string, work: () => Promise<string | void>) => {
    if (busy.has(key)) return;
    setBusy((current) => new Set(current).add(key));
    try {
      const message = await work();
      if (message) showToast(message);
      await load();
    } catch (actionError) {
      showToast(getErrorMessage(actionError, 'Something went wrong'), 3500);
    } finally {
      setBusy((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  };

  const handleQuickStatus = (memory: MemoryItem, action: 'accept' | 'retract') =>
    act(memory.id, async () => {
      await changeMemoryStatus(memory.id, action);
      return action === 'accept' ? 'Accepted' : 'Marked as wrong';
    });

  const handleAcceptAll = async () => {
    if (isAcceptingAll || proposed.length === 0) return;
    setIsAcceptingAll(true);
    try {
      const accepted = await acceptMemories(
        proposed.slice(0, ACCEPT_ALL_LIMIT).map((memory) => memory.id)
      );
      showToast(accepted === 1 ? '1 memory accepted' : `${accepted} memories accepted`);
      await load();
    } catch (acceptError) {
      showToast(getErrorMessage(acceptError, 'Could not accept them'));
    } finally {
      setIsAcceptingAll(false);
    }
  };

  const handleSuggestion = (suggestion: MemorySuggestion, choice: SuggestionChoice) =>
    act(suggestionKey(suggestion), async () => {
      const { first, second } = suggestion;
      if (choice === 'dismiss') {
        await dismissSuggestion(first.id, second.id, suggestion.kind);
        return 'Kept both';
      }
      // The newer memory is kept: it is the user's latest word.
      await keepMemory(second.id, first.id, choice);
      return choice === 'merge' ? 'Merged' : 'Kept the newer one';
    });

  const handleDismissHeldBack = (heldBack: HeldBack) =>
    act(heldBack.run_id, async () => {
      await dismissHeldBack(heldBack.run_id);
      return 'Dismissed';
    });

  const handleEditorSubmit = async (draft: MemoryDraft) => {
    if (!editor) return;
    if (editor.kind === 'create') {
      await createMemory(draft);
      showToast('Memory saved');
    } else {
      await saveHeldBack(editor.heldBack.run_id, draft);
      showToast('Saved from the message');
    }
    setEditor(null);
    await load();
  };

  const addFromFiles = async () => {
    const picked = await pickAttachments(0);
    for (const error of picked.errors) showToast(error, 3500);
    if (!picked.attachments.length) return;
    setIsReadingFiles(true);
    try {
      let read = 0;
      for (const file of picked.attachments) {
        const result = await memoryFromFile(file.name, file.media_type, file.data);
        if (result.created) read += 1;
      }
      showToast(
        read
          ? 'Read. New memories appear in a moment.'
          : 'You saved this before; nothing new to read.',
        3500
      );
      await load();
    } catch (error) {
      showToast(getErrorMessage(error, "Couldn't read the file"), 4000);
    } finally {
      setIsReadingFiles(false);
    }
  };

  const chooseAdd = (key: (typeof ADD_OPTIONS)[number]['key']) => {
    setIsAddMenuOpen(false);
    if (key === 'write') setEditor({ kind: 'create' });
    else if (key === 'file') void addFromFiles();
    else router.push('/import');
  };

  const openMemory = (memory: MemoryItem) =>
    router.push({ pathname: '/memories/[id]', params: { id: memory.id } });

  if (!hasSession) {
    return <View style={styles.safeArea} />;
  }

  const errorBox = error ? (
    <TouchableOpacity
      style={styles.errorBox}
      onPress={() => {
        setError(null);
        void load();
      }}
      activeOpacity={0.75}
      accessibilityRole="button">
      <Text style={styles.errorText}>{error}</Text>
      <Text style={styles.linkText}>Try again</Text>
    </TouchableOpacity>
  ) : null;

  const spinnerOrNothing =
    !hasLoaded && !error ? (
      <ActivityIndicator style={styles.spinner} color={Colors.primary} />
    ) : undefined;

  const refreshControl = (
    <RefreshControl
      refreshing={isRefreshing}
      onRefresh={handleRefresh}
      tintColor={Colors.primary}
    />
  );

  const renderAll = () => {
    if (searchText && searchIn === 'chats') {
      return (
        <FlatList
          data={chatResults ?? []}
          keyExtractor={(hit) => hit.message_id}
          contentContainerStyle={styles.listContent}
          keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => (
            <TouchableOpacity
              style={styles.hitRow}
              onPress={() => openChatThread(item.thread_id)}
              activeOpacity={0.7}
              accessibilityRole="button">
              <Text style={styles.hitMeta}>
                {item.role === 'user' ? 'You' : 'Cooper'} · {item.thread_title} ·{' '}
                {formatRelativeTime(item.created_at)}
              </Text>
              <Text style={styles.hitText} numberOfLines={3}>
                {snippetParts(item.snippet).map((part, index) => (
                  <Text key={index} style={part.match ? styles.hitMatch : undefined}>
                    {part.text}
                  </Text>
                ))}
              </Text>
            </TouchableOpacity>
          )}
          ItemSeparatorComponent={Separator}
          ListEmptyComponent={
            isSearching ? (
              <ActivityIndicator style={styles.spinner} color={Colors.primary} />
            ) : (
              <Text style={styles.emptyText}>No chat mentions “{searchText}”.</Text>
            )
          }
        />
      );
    }
    if (results !== null || isSearching) {
      return (
        <FlatList
          data={results ?? []}
          keyExtractor={(memory) => memory.id}
          contentContainerStyle={styles.listContent}
          keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => <MemoryRow memory={item} onPress={() => openMemory(item)} />}
          ItemSeparatorComponent={Separator}
          ListEmptyComponent={
            isSearching ? (
              <ActivityIndicator style={styles.spinner} color={Colors.primary} />
            ) : (
              <Text style={styles.emptyText}>Nothing matches “{query.trim()}”.</Text>
            )
          }
        />
      );
    }
    return (
      <SectionList
        sections={sections}
        keyExtractor={(memory) => memory.id}
        contentContainerStyle={styles.listContent}
        stickySectionHeadersEnabled={false}
        ListHeaderComponent={
          <View style={styles.header}>
            <View style={styles.groupCard}>
              <View style={styles.settingRow}>
                <View style={styles.settingText}>
                  <Text style={styles.settingTitle}>Save chats as memories</Text>
                  <Text style={styles.settingDescription}>
                    What you tell Cooper becomes memories a moment after you send it. Only your
                    messages are used, not Cooper&apos;s replies.
                  </Text>
                </View>
                {captureEnabled === null ? (
                  error ? null : (
                    <ActivityIndicator color={Colors.primary} />
                  )
                ) : (
                  <Switch
                    value={captureEnabled}
                    onValueChange={handleToggleCapture}
                    disabled={isSavingSetting}
                    trackColor={{ false: Colors.border, true: Colors.primaryLight }}
                    thumbColor={captureEnabled ? Colors.primary : Colors.surfaceMuted}
                    accessibilityLabel="Save chats as memories"
                  />
                )}
              </View>
            </View>
            {hasLoaded ? (
              <Text style={styles.countText}>
                {total === 1 ? '1 memory' : `${total.toLocaleString()} memories`}
              </Text>
            ) : null}
            {errorBox}
          </View>
        }
        renderSectionHeader={({ section }) => (
          <Text style={styles.sectionTitle}>{section.title}</Text>
        )}
        renderItem={({ item }) => <MemoryRow memory={item} onPress={() => openMemory(item)} />}
        ItemSeparatorComponent={Separator}
        ListEmptyComponent={
          hasLoaded ? (
            <Text style={styles.emptyText}>
              Nothing yet. Tell Cooper something about yourself, like &quot;My sister Priya lives in
              Pune&quot;, or tap + to write a memory.
            </Text>
          ) : (
            spinnerOrNothing
          )
        }
        ListFooterComponent={
          isLoadingMore ? (
            <ActivityIndicator style={styles.spinner} color={Colors.primary} />
          ) : undefined
        }
        onEndReached={handleLoadMore}
        onEndReachedThreshold={0.4}
        refreshControl={refreshControl}
      />
    );
  };

  const renderReview = () => {
    const suggestions = inbox?.suggestions ?? [];
    const heldBack = inbox?.held_back ?? [];
    const proposedCount = inbox?.proposed_count ?? proposed.length;
    const nothingToReview =
      hasLoaded && suggestions.length === 0 && heldBack.length === 0 && proposed.length === 0;
    return (
      <FlatList
        data={proposed}
        keyExtractor={(memory) => memory.id}
        contentContainerStyle={styles.listContent}
        ListHeaderComponent={
          <View style={styles.header}>
            {errorBox}
            {nothingToReview ? (
              <Text style={styles.emptyText}>
                Nothing to review. New memories from your chats show up here until you accept them.
              </Text>
            ) : null}
            {suggestions.length ? (
              <View>
                <Text style={styles.sectionTitle}>Look alike · {suggestions.length}</Text>
                {suggestions.map((suggestion) => (
                  <SuggestionCard
                    key={suggestionKey(suggestion)}
                    suggestion={suggestion}
                    busy={busy.has(suggestionKey(suggestion))}
                    onChoose={(choice) => handleSuggestion(suggestion, choice)}
                    onOpen={openMemory}
                  />
                ))}
              </View>
            ) : null}
            {heldBack.length ? (
              <View>
                <Text style={styles.sectionTitle}>
                  Held back · {inbox?.held_back_count ?? heldBack.length}
                </Text>
                {heldBack.map((item) => (
                  <HeldBackCard
                    key={item.run_id}
                    heldBack={item}
                    busy={busy.has(item.run_id)}
                    onSave={() => setEditor({ kind: 'held', heldBack: item })}
                    onDismiss={() => handleDismissHeldBack(item)}
                    onOpenChat={openChatThread}
                  />
                ))}
              </View>
            ) : null}
            {proposed.length ? (
              <View style={styles.toReviewHeader}>
                <Text style={[styles.sectionTitle, styles.flex]}>
                  New memories · {proposedCount}
                </Text>
                <TouchableOpacity
                  style={styles.acceptAll}
                  onPress={handleAcceptAll}
                  disabled={isAcceptingAll}
                  activeOpacity={0.8}
                  accessibilityRole="button">
                  {isAcceptingAll ? (
                    <ActivityIndicator size="small" color={Colors.primary} />
                  ) : (
                    <Text style={styles.acceptAllText}>
                      Accept{' '}
                      {proposed.length === proposedCount ? 'all' : `these ${proposed.length}`}
                    </Text>
                  )}
                </TouchableOpacity>
              </View>
            ) : null}
            {spinnerOrNothing}
          </View>
        }
        renderItem={({ item }) => (
          <MemoryRow
            memory={item}
            onPress={() => openMemory(item)}
            onAccept={() => handleQuickStatus(item, 'accept')}
            onRetract={() => handleQuickStatus(item, 'retract')}
            busy={busy.has(item.id)}
          />
        )}
        ItemSeparatorComponent={Separator}
        refreshControl={refreshControl}
      />
    );
  };

  const renderPeople = () => (
    <FlatList
      data={people}
      keyExtractor={(person) => person.id}
      contentContainerStyle={styles.listContent}
      ListHeaderComponent={<View style={styles.header}>{errorBox}</View>}
      renderItem={({ item }) => (
        <TouchableOpacity
          style={styles.personRow}
          onPress={() => router.push({ pathname: '/people/[id]', params: { id: item.id } })}
          activeOpacity={0.7}
          accessibilityRole="button">
          <View style={styles.personAvatar}>
            <Text style={styles.personInitial}>{item.name.charAt(0).toUpperCase()}</Text>
          </View>
          <View style={styles.flex}>
            <Text style={styles.personName}>{item.name}</Text>
            <Text style={styles.personMeta}>
              {item.entity_type === 'person' ? 'Person' : memoryTypeLabel(item.entity_type)} ·{' '}
              {item.memory_count === 1 ? '1 memory' : `${item.memory_count} memories`}
              {item.last_seen_at ? ` · ${formatRelativeTime(item.last_seen_at)}` : ''}
            </Text>
          </View>
        </TouchableOpacity>
      )}
      ItemSeparatorComponent={Separator}
      ListEmptyComponent={
        hasLoaded ? (
          <Text style={styles.emptyText}>
            People, places, and things you mention to Cooper show up here.
          </Text>
        ) : (
          spinnerOrNothing
        )
      }
      refreshControl={refreshControl}
    />
  );

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right', 'bottom']}>
      <ScreenHeader
        title="Memories"
        right={
          <TouchableOpacity
            style={styles.addButton}
            onPress={() => setIsAddMenuOpen(true)}
            disabled={isReadingFiles}
            activeOpacity={0.8}
            accessibilityRole="button"
            accessibilityLabel="Add a memory">
            {isReadingFiles ? (
              <ActivityIndicator size="small" color={Colors.white} />
            ) : (
              <HugeiconsIcon icon={PlusSignIcon} size={20} color={Colors.white} />
            )}
          </TouchableOpacity>
        }
      />

      <View style={styles.tabs} accessibilityRole="tablist">
        {(
          [
            ['all', 'All'],
            ['review', reviewCount ? `To review · ${reviewCount}` : 'To review'],
            ['people', 'People'],
          ] as const
        ).map(([value, label]) => (
          <TouchableOpacity
            key={value}
            style={[styles.tab, tab === value && styles.tabSelected]}
            onPress={() => setTab(value)}
            activeOpacity={0.8}
            accessibilityRole="tab"
            accessibilityState={{ selected: tab === value }}>
            <Text style={[styles.tabText, tab === value && styles.tabTextSelected]}>{label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {tab === 'all' ? (
        <View style={styles.searchBar}>
          <HugeiconsIcon icon={Search01Icon} size={18} color={Colors.iconMuted} />
          <TextInput
            style={styles.searchInput}
            value={query}
            onChangeText={setQuery}
            placeholder="Search memories and chats"
            placeholderTextColor={Colors.iconMuted}
            returnKeyType="search"
            autoCorrect={false}
            accessibilityLabel="Search your memories"
          />
          {query ? (
            <TouchableOpacity onPress={() => setQuery('')} accessibilityRole="button">
              <Text style={styles.linkText}>Clear</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      ) : null}

      {tab === 'all' && searchText ? (
        <View style={styles.searchModes}>
          {(
            [
              ['memories', 'Memories'],
              ['chats', 'Chats'],
            ] as const
          ).map(([value, label]) => (
            <TouchableOpacity
              key={value}
              style={[styles.searchMode, searchIn === value && styles.searchModeSelected]}
              onPress={() => setSearchIn(value)}
              accessibilityRole="button"
              accessibilityState={{ selected: searchIn === value }}>
              <Text
                style={[
                  styles.searchModeText,
                  searchIn === value && styles.searchModeTextSelected,
                ]}>
                {label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      ) : null}

      {tab === 'all' ? renderAll() : tab === 'review' ? renderReview() : renderPeople()}

      <Modal
        visible={isAddMenuOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setIsAddMenuOpen(false)}>
        <TouchableWithoutFeedback onPress={() => setIsAddMenuOpen(false)}>
          <View style={styles.menuOverlay}>
            <View style={styles.menu}>
              {ADD_OPTIONS.map((option) => (
                <TouchableOpacity
                  key={option.key}
                  style={styles.menuItem}
                  onPress={() => chooseAdd(option.key)}
                  activeOpacity={0.7}
                  accessibilityRole="button">
                  <Text style={styles.menuLabel}>{option.label}</Text>
                  <Text style={styles.menuHint}>{option.hint}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        </TouchableWithoutFeedback>
      </Modal>

      <MemoryEditorModal
        visible={editor !== null}
        title={editor?.kind === 'held' ? 'Save as memory' : 'Write a memory'}
        confirmText="Save"
        initial={
          editor?.kind === 'held'
            ? { ...NEW_DRAFT, content: heldBackDraft(editor.heldBack) }
            : NEW_DRAFT
        }
        hint={
          editor?.kind === 'held'
            ? 'Say what Cooper should remember. It keeps a link to your message.'
            : undefined
        }
        onClose={() => setEditor(null)}
        onSubmit={handleEditorSubmit}
      />
    </SafeAreaView>
  );
}

function Separator() {
  return <View style={styles.separator} />;
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  flex: {
    flex: 1,
  },
  addButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: Colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabs: {
    flexDirection: 'row',
    gap: 6,
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  tab: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 18,
    backgroundColor: Colors.surface,
  },
  tabSelected: {
    backgroundColor: Colors.iconDark,
  },
  tabText: {
    fontSize: 13.5,
    fontWeight: '600',
    color: Colors.textSecondary,
  },
  tabTextSelected: {
    color: Colors.white,
  },
  menuOverlay: {
    flex: 1,
    backgroundColor: Colors.overlay,
    justifyContent: 'flex-start',
    alignItems: 'flex-end',
    paddingTop: 90,
    paddingHorizontal: 16,
  },
  menu: {
    width: 260,
    borderRadius: 16,
    backgroundColor: Colors.white,
    paddingVertical: 6,
  },
  menuItem: {
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  menuLabel: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  menuHint: {
    marginTop: 2,
    fontSize: 12.5,
    color: Colors.textSecondary,
  },
  searchModes: {
    flexDirection: 'row',
    gap: 6,
    marginHorizontal: 16,
    marginTop: 8,
  },
  searchMode: {
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  searchModeSelected: {
    borderColor: Colors.primaryBorder,
    backgroundColor: Colors.primarySubtle,
  },
  searchModeText: {
    fontSize: 12.5,
    fontWeight: '600',
    color: Colors.textSecondary,
  },
  searchModeTextSelected: {
    color: Colors.primary,
  },
  hitRow: {
    paddingVertical: 12,
  },
  hitMeta: {
    fontSize: 12,
    color: Colors.textSecondary,
  },
  hitText: {
    marginTop: 3,
    fontSize: 14.5,
    lineHeight: 20,
    color: Colors.textPrimary,
  },
  hitMatch: {
    fontWeight: '700',
    color: Colors.iconDark,
  },
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 16,
    marginTop: 12,
    paddingHorizontal: 12,
    height: 42,
    borderRadius: 21,
    backgroundColor: Colors.surfaceInput,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
  },
  searchInput: {
    flex: 1,
    fontSize: 15,
    color: Colors.iconDark,
    paddingVertical: 0,
  },
  listContent: {
    paddingHorizontal: 20,
    paddingBottom: 40,
  },
  header: {
    paddingTop: 16,
    gap: 12,
  },
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
  countText: {
    fontSize: 13,
    color: Colors.textSecondary,
  },
  sectionTitle: {
    marginTop: 14,
    marginBottom: 6,
    fontSize: 12,
    fontWeight: '700',
    color: Colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  toReviewHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  acceptAll: {
    marginTop: 8,
    paddingHorizontal: 12,
    height: 32,
    borderRadius: 16,
    backgroundColor: Colors.primarySubtle,
    alignItems: 'center',
    justifyContent: 'center',
  },
  acceptAllText: {
    fontSize: 13,
    fontWeight: '700',
    color: Colors.primary,
  },
  separator: {
    height: 1,
    backgroundColor: Colors.borderLight,
  },
  emptyText: {
    fontSize: 14,
    lineHeight: 20,
    color: Colors.textSecondary,
    paddingVertical: 12,
  },
  spinner: {
    marginVertical: 16,
  },
  errorBox: {
    padding: 14,
    borderRadius: 14,
    backgroundColor: Colors.errorLight,
    gap: 6,
  },
  errorText: {
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.error,
  },
  linkText: {
    fontSize: 13.5,
    fontWeight: '700',
    color: Colors.primary,
  },
  personRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 12,
  },
  personAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Colors.primarySubtle,
    alignItems: 'center',
    justifyContent: 'center',
  },
  personInitial: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.primary,
  },
  personName: {
    fontSize: 15.5,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  personMeta: {
    marginTop: 2,
    fontSize: 12.5,
    color: Colors.textSecondary,
  },
});
