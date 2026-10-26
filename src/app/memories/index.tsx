/**
 * Memories Screen ('/memories')
 *
 * What Cooper remembers about the user, in three segments:
 *
 * - All: memories that may still be true, newest first and grouped by when they were
 *   saved, with search (words, names, and meaning; or the chats themselves) and the switch
 *   for saving chats as memories.
 * - To review: memories waiting to be accepted, pairs that look like duplicates or
 *   conflicts, and messages Cooper held back.
 * - People: the people, places, and things the memories mention.
 *
 * "+" opens a pull-down menu to write a memory, read one from a file, or import a chat.
 * Everything reloads when the screen is shown again, so changes made on a memory's own
 * screen appear here.
 *
 * One list holds every segment: the large title, the segmented control, and the search
 * field sit in its header, so typing never remounts the field and the bar's title appears
 * once the large one scrolls under it. Rows are inset-grouped (MemoryRow's InsetCell),
 * since a virtualized list cannot use ListSection.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  StyleSheet,
  TextInput,
  View,
  type ListRenderItemInfo,
} from 'react-native';
import Animated, {
  FadeIn,
  FadeOut,
  Keyframe,
  ReduceMotion,
  useReducedMotion,
} from 'react-native-reanimated';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import {
  AlertCircleIcon,
  ArrowRight01Icon,
  Brain01Icon,
  CancelCircleIcon,
  CheckmarkCircle02Icon,
  File01Icon,
  MessageMultiple01Icon,
  PencilEdit02Icon,
  PlusSignIcon,
  Search01Icon,
  UserGroupIcon,
} from '@hugeicons/core-free-icons';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  AppSwitch,
  AppText,
  Button,
  Card,
  EmptyState,
  IconButton,
  LargeTitle,
  ListRow,
  ListSection,
  PressableScale,
  ScreenHeader,
  SegmentedControl,
  useScrollY,
} from '@/components/ui';
import { MemoryEditorModal, type MemoryDraft } from '@/components/memories/MemoryEditorModal';
import {
  CellPressable,
  EntityAvatar,
  InsetCell,
  InsetGroupHeader,
  LEADING_INSET,
  MemoryRow,
} from '@/components/memories/MemoryRow';
import {
  HeldBackCard,
  SuggestionCard,
  type SuggestionChoice,
} from '@/components/memories/ReviewCards';
import { Colors } from '@/constants/colors';
import {
  Elevation,
  Hairline,
  Motion,
  Radius,
  ScreenMargin,
  Typography,
  continuous,
} from '@/constants/theme';
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

const ADD_OPTIONS: readonly {
  key: 'write' | 'file' | 'import';
  label: string;
  hint: string;
  icon: IconSvgElement;
}[] = [
  { key: 'write', label: 'Write a memory', hint: 'Something for Cooper to know.', icon: PencilEdit02Icon },
  { key: 'file', label: 'From a photo or PDF', hint: 'A receipt, a note, a document.', icon: File01Icon },
  { key: 'import', label: 'Import a WhatsApp chat', hint: 'Bring an exported chat in.', icon: MessageMultiple01Icon },
];

const SEARCH_SCOPES = [
  { value: 'memories', label: 'Memories' },
  { value: 'chats', label: 'Chats' },
] as const;

const NEW_DRAFT: MemoryDraft = { content: '', memory_type: 'note', sensitive: false };

// The add menu grows out of the "+" it hangs from, from 95% (never from nothing), on a
// strong ease-out; with Reduce Motion it only fades. It leaves faster than it came.
const MENU_IN = new Keyframe({
  0: { opacity: 0, transform: [{ scale: 0.95 }] },
  100: { opacity: 1, transform: [{ scale: 1 }], easing: Motion.easeOut },
}).duration(Motion.duration.small);
const MENU_FADE_IN = FadeIn.duration(Motion.duration.small).reduceMotion(ReduceMotion.Never);
const MENU_OUT = FadeOut.duration(140).easing(Motion.easeOut).reduceMotion(ReduceMotion.Never);

/** One row of the list: a group header, a row in an inset group, or a review card. */
type Entry =
  | { kind: 'header'; key: string; title: string; acceptAll?: boolean }
  | { kind: 'memory'; key: string; memory: MemoryItem; first: boolean; last: boolean; review: boolean }
  | { kind: 'hit'; key: string; hit: MessageHit; first: boolean; last: boolean }
  | { kind: 'person'; key: string; person: Person; first: boolean; last: boolean }
  | { kind: 'suggestion'; key: string; suggestion: MemorySuggestion; last: boolean }
  | { kind: 'heldBack'; key: string; heldBack: HeldBack; last: boolean };

function suggestionKey(suggestion: MemorySuggestion): string {
  return `${suggestion.first.id}:${suggestion.second.id}`;
}

function memoryEntries(memories: readonly MemoryItem[], review = false): Entry[] {
  return memories.map((memory, index) => ({
    kind: 'memory',
    key: `m:${memory.id}`,
    memory,
    review,
    first: index === 0,
    last: index === memories.length - 1,
  }));
}

export default function MemoriesScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const reducedMotion = useReducedMotion();
  const { scrollY, onScroll } = useScrollY();
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
  const proposedCount = inbox?.proposed_count ?? proposed.length;

  // What the list shows: the timeline, search results (memories or chats), or a segment.
  const mode =
    tab === 'all' ? (searchText ? (searchIn === 'chats' ? 'chats' : 'results') : 'timeline') : tab;

  const entries = useMemo((): Entry[] => {
    if (mode === 'timeline') {
      return sections.flatMap((section): Entry[] => [
        { kind: 'header', key: `h:${section.title}`, title: section.title },
        ...memoryEntries(section.data),
      ]);
    }
    if (mode === 'results') return memoryEntries(results ?? []);
    if (mode === 'chats') {
      const hits = chatResults ?? [];
      return hits.map((hit, index) => ({
        kind: 'hit',
        key: `c:${hit.message_id}`,
        hit,
        first: index === 0,
        last: index === hits.length - 1,
      }));
    }
    if (mode === 'people') {
      return people.map((person, index) => ({
        kind: 'person',
        key: `p:${person.id}`,
        person,
        first: index === 0,
        last: index === people.length - 1,
      }));
    }
    const suggestions = inbox?.suggestions ?? [];
    const heldBack = inbox?.held_back ?? [];
    const list: Entry[] = [];
    if (suggestions.length) {
      list.push({ kind: 'header', key: 'h:suggestions', title: `Look alike · ${suggestions.length}` });
      suggestions.forEach((suggestion, index) =>
        list.push({
          kind: 'suggestion',
          key: `s:${suggestionKey(suggestion)}`,
          suggestion,
          last: index === suggestions.length - 1,
        })
      );
    }
    if (heldBack.length) {
      list.push({
        kind: 'header',
        key: 'h:held',
        title: `Held back · ${inbox?.held_back_count ?? heldBack.length}`,
      });
      heldBack.forEach((item, index) =>
        list.push({
          kind: 'heldBack',
          key: `b:${item.run_id}`,
          heldBack: item,
          last: index === heldBack.length - 1,
        })
      );
    }
    if (proposed.length) {
      list.push({
        kind: 'header',
        key: 'h:proposed',
        title: `New memories · ${proposedCount}`,
        acceptAll: true,
      });
      list.push(...memoryEntries(proposed, true));
    }
    return list;
  }, [mode, sections, results, chatResults, people, inbox, proposed, proposedCount]);

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

  const spinner = <ActivityIndicator style={styles.spinner} color={Colors.systemGray} />;

  const errorCard = error ? (
    <Card
      onPress={() => {
        setError(null);
        void load();
      }}
      containerStyle={styles.errorCard}
      style={styles.errorCardBody}>
      <HugeiconsIcon icon={AlertCircleIcon} size={22} color={Colors.systemRed} strokeWidth={2} />
      <View style={styles.flex}>
        <AppText variant="subheadline">{error}</AppText>
        <AppText variant="subheadline" weight="600" color="tint">
          Try again
        </AppText>
      </View>
    </Card>
  ) : null;

  const captureSection = (
    <ListSection footer="What you tell Cooper becomes memories a moment after you send it. Only your messages are used, not Cooper's replies.">
      <ListRow
        title="Save chats as memories"
        accessory={
          captureEnabled === null ? (
            error ? (
              'none'
            ) : (
              <ActivityIndicator color={Colors.systemGray} />
            )
          ) : (
            <AppSwitch
              value={captureEnabled}
              onValueChange={handleToggleCapture}
              disabled={isSavingSetting}
              accessibilityLabel="Save chats as memories"
            />
          )
        }
      />
    </ListSection>
  );

  // Stays mounted while the user types, so the field keeps its focus and keyboard.
  const listHeader = (
    <View>
      <LargeTitle title="Memories" />
      <SegmentedControl
        segments={[
          { value: 'all', label: 'All' },
          { value: 'review', label: 'To review', badge: reviewCount || undefined },
          { value: 'people', label: 'People' },
        ]}
        value={tab}
        onChange={setTab}
        style={styles.segments}
      />
      {tab === 'all' ? (
        <View style={[styles.searchField, continuous]}>
          <HugeiconsIcon icon={Search01Icon} size={17} color={Colors.systemGray} strokeWidth={2} />
          <TextInput
            style={styles.searchInput}
            value={query}
            onChangeText={setQuery}
            placeholder="Search memories and chats"
            placeholderTextColor={Colors.placeholder}
            selectionColor={Colors.tint}
            returnKeyType="search"
            autoCorrect={false}
            accessibilityLabel="Search your memories"
          />
          {query ? (
            <PressableScale
              onPress={() => setQuery('')}
              hitSlop={12}
              pressedScale={0.9}
              accessibilityRole="button"
              accessibilityLabel="Clear">
              <HugeiconsIcon icon={CancelCircleIcon} size={18} color={Colors.tertiaryLabel} strokeWidth={2} />
            </PressableScale>
          ) : null}
        </View>
      ) : null}
      {tab === 'all' && searchText ? (
        <SegmentedControl
          segments={SEARCH_SCOPES}
          value={searchIn}
          onChange={setSearchIn}
          style={styles.scopes}
        />
      ) : null}
      {errorCard}
      {mode === 'timeline' ? captureSection : null}
    </View>
  );

  const listEmpty = (() => {
    if (mode === 'results' || mode === 'chats') {
      if (isSearching) return spinner;
      return (
        <EmptyState
          icon={Search01Icon}
          title="No results"
          message={
            mode === 'chats'
              ? `No chat mentions “${searchText}”.`
              : `Nothing matches “${searchText}”.`
          }
        />
      );
    }
    if (!hasLoaded) return error ? undefined : spinner;
    if (mode === 'timeline') {
      return (
        <EmptyState
          icon={Brain01Icon}
          title="No memories yet"
          message="Tell Cooper something about yourself, like “My sister Priya lives in Pune”, or write one here."
          actionTitle="Write a memory"
          onAction={() => setEditor({ kind: 'create' })}
        />
      );
    }
    if (mode === 'review') {
      return (
        <EmptyState
          icon={CheckmarkCircle02Icon}
          title="Nothing to review"
          message="New memories from your chats show up here until you accept them."
        />
      );
    }
    return (
      <EmptyState
        icon={UserGroupIcon}
        title="No people yet"
        message="People, places, and things you mention to Cooper show up here."
      />
    );
  })();

  // The count closes the timeline, as Contacts counts its list at the bottom.
  const listFooter =
    mode !== 'timeline' ? undefined : isLoadingMore ? (
      spinner
    ) : hasLoaded && memories.length ? (
      <AppText variant="footnote" color="secondary" align="center" style={styles.count}>
        {total === 1 ? '1 memory' : `${total.toLocaleString()} memories`}
      </AppText>
    ) : undefined;

  const renderEntry = ({ item }: ListRenderItemInfo<Entry>) => {
    switch (item.kind) {
      case 'header':
        return (
          <InsetGroupHeader
            title={item.title}
            action={
              item.acceptAll ? (
                <Button
                  title={`Accept ${proposed.length === proposedCount ? 'all' : `these ${proposed.length}`}`}
                  variant="plain"
                  size="small"
                  haptic="success"
                  loading={isAcceptingAll}
                  onPress={handleAcceptAll}
                />
              ) : undefined
            }
          />
        );
      case 'memory': {
        const { memory } = item;
        return (
          <InsetCell first={item.first} last={item.last} inset={LEADING_INSET}>
            {item.review ? (
              <MemoryRow
                memory={memory}
                onPress={() => openMemory(memory)}
                onAccept={() => handleQuickStatus(memory, 'accept')}
                onRetract={() => handleQuickStatus(memory, 'retract')}
                busy={busy.has(memory.id)}
              />
            ) : (
              <MemoryRow memory={memory} onPress={() => openMemory(memory)} />
            )}
          </InsetCell>
        );
      }
      case 'hit':
        return (
          <InsetCell first={item.first} last={item.last}>
            <HitRow hit={item.hit} onPress={() => openChatThread(item.hit.thread_id)} />
          </InsetCell>
        );
      case 'person': {
        const { person } = item;
        return (
          <InsetCell first={item.first} last={item.last} inset={LEADING_INSET}>
            <ListRow
              leading={<EntityAvatar type={person.entity_type} name={person.name} />}
              title={person.name}
              subtitle={
                `${person.entity_type === 'person' ? 'Person' : memoryTypeLabel(person.entity_type)} · ` +
                `${person.memory_count === 1 ? '1 memory' : `${person.memory_count} memories`}` +
                `${person.last_seen_at ? ` · ${formatRelativeTime(person.last_seen_at)}` : ''}`
              }
              onPress={() => router.push({ pathname: '/people/[id]', params: { id: person.id } })}
            />
          </InsetCell>
        );
      }
      case 'suggestion': {
        const key = suggestionKey(item.suggestion);
        return (
          <View style={[styles.cardSlot, item.last && styles.cardSlotLast]}>
            <SuggestionCard
              suggestion={item.suggestion}
              busy={busy.has(key)}
              onChoose={(choice) => handleSuggestion(item.suggestion, choice)}
              onOpen={openMemory}
            />
          </View>
        );
      }
      case 'heldBack':
        return (
          <View style={[styles.cardSlot, item.last && styles.cardSlotLast]}>
            <HeldBackCard
              heldBack={item.heldBack}
              busy={busy.has(item.heldBack.run_id)}
              onSave={() => setEditor({ kind: 'held', heldBack: item.heldBack })}
              onDismiss={() => handleDismissHeldBack(item.heldBack)}
              onOpenChat={openChatThread}
            />
          </View>
        );
    }
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      <ScreenHeader
        title="Memories"
        scrollY={scrollY}
        right={
          isReadingFiles ? (
            <View
              style={styles.barSpinner}
              accessible
              accessibilityLabel="Add a memory"
              accessibilityState={{ disabled: true, busy: true }}>
              <ActivityIndicator size="small" color={Colors.systemGray} />
            </View>
          ) : (
            <IconButton
              icon={PlusSignIcon}
              onPress={() => setIsAddMenuOpen((open) => !open)}
              accessibilityLabel="Add a memory"
            />
          )
        }
      />

      <View style={styles.flex}>
        <Animated.FlatList
          data={entries}
          keyExtractor={(entry) => entry.key}
          renderItem={renderEntry}
          ListHeaderComponent={listHeader}
          ListEmptyComponent={listEmpty}
          ListFooterComponent={listFooter}
          contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}
          onScroll={onScroll}
          scrollEventThrottle={16}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
          onEndReached={mode === 'timeline' ? handleLoadMore : undefined}
          onEndReachedThreshold={0.4}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
              tintColor={Colors.systemGray}
            />
          }
        />

        {/* The pull-down menu of "+": it hangs from the button and a tap outside closes it. */}
        {isAddMenuOpen ? (
          <Pressable
            style={StyleSheet.absoluteFill}
            onPress={() => setIsAddMenuOpen(false)}
            accessibilityRole="button"
            accessibilityLabel="Close the menu"
          />
        ) : null}
        {isAddMenuOpen ? (
          <Animated.View
            entering={reducedMotion ? MENU_FADE_IN : MENU_IN}
            exiting={MENU_OUT}
            style={[styles.menu, continuous]}>
            <View style={[styles.menuClip, continuous]}>
              {ADD_OPTIONS.map((option, index) => (
                <React.Fragment key={option.key}>
                  {index > 0 ? <View style={styles.menuSeparator} /> : null}
                  <CellPressable onPress={() => chooseAdd(option.key)} style={styles.menuItem}>
                    <View style={styles.flex}>
                      <AppText variant="body">{option.label}</AppText>
                      <AppText variant="footnote" color="secondary">
                        {option.hint}
                      </AppText>
                    </View>
                    <HugeiconsIcon icon={option.icon} size={20} color={Colors.label} strokeWidth={1.8} />
                  </CellPressable>
                </React.Fragment>
              ))}
            </View>
          </Animated.View>
        ) : null}
      </View>

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

/** A chat message that matches the search: who said it where and when, the words in bold. */
function HitRow({ hit, onPress }: { hit: MessageHit; onPress: () => void }) {
  return (
    <CellPressable onPress={onPress} style={styles.hitRow}>
      <View style={styles.hitTexts}>
        <AppText variant="footnote" color="secondary" numberOfLines={1}>
          {hit.role === 'user' ? 'You' : 'Cooper'} · {hit.thread_title} ·{' '}
          {formatRelativeTime(hit.created_at)}
        </AppText>
        <AppText variant="body" numberOfLines={3}>
          {snippetParts(hit.snippet).map((part, index) => (
            <AppText key={index} variant="body" weight={part.match ? '600' : undefined}>
              {part.text}
            </AppText>
          ))}
        </AppText>
      </View>
      <HugeiconsIcon icon={ArrowRight01Icon} size={18} color={Colors.tertiaryLabel} strokeWidth={2.2} />
    </CellPressable>
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
  barSpinner: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.tertiaryFill,
  },
  segments: {
    marginHorizontal: ScreenMargin,
    marginBottom: 12,
  },
  // The iOS search field: a gray well with a magnifier. On the grouped gray, iOS's
  // translucent tertiary fill comes out as `fill`; the opaque `tertiaryFill` would vanish.
  searchField: {
    height: 36,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginHorizontal: ScreenMargin,
    marginBottom: 16,
    paddingHorizontal: 8,
    borderRadius: 10,
    backgroundColor: Colors.fill,
  },
  searchInput: {
    flex: 1,
    height: 36,
    paddingVertical: 0,
    fontSize: Typography.body.fontSize,
    letterSpacing: Typography.body.letterSpacing,
    color: Colors.label,
  },
  scopes: {
    marginHorizontal: ScreenMargin,
    marginTop: -4,
    marginBottom: 20,
  },
  errorCard: {
    marginHorizontal: ScreenMargin,
    marginBottom: 20,
  },
  errorCardBody: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  cardSlot: {
    marginHorizontal: ScreenMargin,
    marginBottom: 12,
  },
  cardSlotLast: {
    marginBottom: 28,
  },
  hitRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  hitTexts: {
    flex: 1,
    gap: 2,
  },
  count: {
    marginTop: -12,
    marginBottom: 12,
  },
  spinner: {
    marginVertical: 24,
  },
  menu: {
    position: 'absolute',
    top: 2,
    right: ScreenMargin,
    width: 264,
    borderRadius: Radius.md + 2,
    backgroundColor: Colors.secondaryGroupedBackground,
    transformOrigin: 'top right',
    ...Elevation.floating,
  },
  menuClip: {
    borderRadius: Radius.md + 2,
    overflow: 'hidden',
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  menuSeparator: {
    height: Hairline,
    backgroundColor: Colors.separator,
  },
});
