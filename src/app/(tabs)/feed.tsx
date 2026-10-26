/**
 * Feed Tab Screen ('/(tabs)/feed'), labelled "Today" in the tab bar.
 *
 * Today: what to act on now, from what the user told their assistant (TodaySection);
 * then this week's patterns, when the memories support them (InsightsSection); then what
 * the assistant did on its own: the results of finished scheduled runs, newest first,
 * the latest three until "Show all". Tapping a result posted to a chat opens that chat.
 * Pull to refresh reloads all three.
 *
 * Laid out as an iOS grouped screen: a large title at the top of the content, then
 * inset-grouped sections and compact white cards on the grouped background.
 */

import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  AlertCircleIcon,
  ArrowRight01Icon,
  CheckmarkCircle02Icon,
} from '@hugeicons/core-free-icons';
import { InsightsSection } from '@/components/feed/InsightsSection';
import { TodaySection } from '@/components/feed/TodaySection';
import {
  AppText,
  Button,
  Card,
  EmptyState,
  IconTile,
  LargeTitle,
  PressableScale,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Radius, ScreenMargin, continuous } from '@/constants/theme';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { listActivity } from '@/lib/api/activity';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import type { ActivityItem, ScheduleDelivery } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';
import { openChatThread } from '@/lib/navigation';

const PAGE_LIMIT = 30;
// Scheduled results shown before "Show all".
const RUNS_FOLDED = 3;
const FEED_ERROR_FALLBACK = 'Could not load your feed';

const DELIVERY_LABEL: Record<ScheduleDelivery, string> = {
  chat: 'Chat',
  slack: 'Slack',
  email: 'Email',
  calendar: 'Calendar',
  notion: 'Notion',
  teams: 'Teams',
  discord: 'Discord',
};

type LoadStatus = 'loading' | 'ready' | 'error';

export default function FeedScreen() {
  const { profile } = useAgentProfile();
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [showAllRuns, setShowAllRuns] = useState(false);
  // Bumped by pull to refresh, so the cards and insights reload with the results.
  const [refreshKey, setRefreshKey] = useState(0);

  // Whether a page has loaded; later failures then keep the list and only show a toast.
  const hasLoadedRef = useRef(false);

  /** Loads the newest page. */
  const loadFirstPage = useCallback((signal?: AbortSignal) => {
    return listActivity({ limit: PAGE_LIMIT, offset: 0 }, signal)
      .then((page) => {
        hasLoadedRef.current = true;
        setItems(page.items);
        setTotal(page.total);
        setStatus('ready');
      })
      .catch((error) => {
        if (isAbortError(error, signal)) return;
        console.error('Failed to load the feed:', error);
        const message = getErrorMessage(error, FEED_ERROR_FALLBACK);
        if (hasLoadedRef.current) {
          showToast(message);
        } else {
          setErrorMessage(message);
          setStatus('error');
        }
      });
  }, []);

  // Tabs stay mounted, so refresh whenever the feed is opened.
  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      void loadFirstPage(controller.signal);
      return () => controller.abort();
    }, [loadFirstPage])
  );

  const handleRefresh = () => {
    setIsRefreshing(true);
    setRefreshKey((key) => key + 1);
    void loadFirstPage().finally(() => setIsRefreshing(false));
  };

  const handleRetry = () => {
    setStatus('loading');
    void loadFirstPage();
  };

  const handleLoadMore = () => {
    if (!showAllRuns || status !== 'ready' || isLoadingMore || items.length >= total) return;

    setIsLoadingMore(true);
    listActivity({ limit: PAGE_LIMIT, offset: items.length })
      .then((page) => {
        setItems((prev) => {
          const seen = new Set(prev.map((item) => item.run_id));
          return [...prev, ...page.items.filter((item) => !seen.has(item.run_id))];
        });
        setTotal(page.total);
      })
      .catch((error) => {
        console.error('Failed to load more of the feed:', error);
        showToast(getErrorMessage(error, 'Could not load more results'));
      })
      .finally(() => setIsLoadingMore(false));
  };

  const renderItem = ({ item }: { item: ActivityItem }) => {
    const failed = item.status === 'failed';
    const threadId = item.thread_id;
    const body = failed
      ? item.error_message || 'The task could not finish.'
      : item.summary || 'Finished without a summary.';
    const meta = [
      formatRelativeTime(item.finished_at, undefined, 'Recently'),
      item.delivery !== 'chat' ? `Sent to ${DELIVERY_LABEL[item.delivery]}` : null,
      item.trigger === 'manual' ? 'Run manually' : null,
    ]
      .filter(Boolean)
      .join(' · ');

    const content = (
      <View style={styles.result}>
        <IconTile
          icon={failed ? AlertCircleIcon : CheckmarkCircle02Icon}
          color={failed ? Colors.systemRed : Colors.systemGreen}
        />
        <View style={styles.resultText}>
          <AppText variant="footnote" color="secondary">
            <AppText variant="footnote" weight="600" color={failed ? 'destructive' : 'success'}>
              {failed ? 'Failed' : 'Done'}
            </AppText>
            {meta ? ` · ${meta}` : null}
          </AppText>
          <AppText variant="headline">{item.title}</AppText>
          <AppText
            variant="subheadline"
            color={failed ? 'destructive' : 'secondary'}
            numberOfLines={4}>
            {body}
          </AppText>
          {threadId ? (
            <View style={styles.openChatRow}>
              <AppText variant="footnote" color="tint" weight="600">
                Open in chat
              </AppText>
              <HugeiconsIcon icon={ArrowRight01Icon} size={14} color={Colors.tint} strokeWidth={2.2} />
            </View>
          ) : null}
        </View>
      </View>
    );

    // A result posted to a chat is a pressable card (PressableScale styled as Card, so it
    // keeps its accessibility hint, which Card does not pass through).
    return threadId ? (
      <PressableScale
        onPress={() => openChatThread(threadId)}
        pressedScale={0.98}
        accessibilityRole="button"
        accessibilityHint="Opens the chat with this result"
        containerStyle={styles.resultSpacing}
        style={[styles.resultCard, continuous]}>
        {content}
      </PressableScale>
    ) : (
      <Card style={styles.resultSpacing}>{content}</Card>
    );
  };

  const header = (
    <View>
      <LargeTitle
        title="Today"
        subtitle={`What to do now, from what you've told ${profile.name}.`}
      />
      <TodaySection refreshKey={refreshKey} />
      <InsightsSection refreshKey={refreshKey} />
      {items.length ? (
        <AppText variant="footnote" color="secondary" style={styles.sectionHeader}>
          Scheduled results
        </AppText>
      ) : null}
    </View>
  );

  const emptyState =
    status === 'loading' ? (
      <View style={styles.loading}>
        <ActivityIndicator color={Colors.systemGray} />
      </View>
    ) : status === 'error' ? (
      <Card style={styles.stateCard}>
        <EmptyState
          compact
          icon={AlertCircleIcon}
          title="Couldn't load your feed"
          message={errorMessage !== FEED_ERROR_FALLBACK ? errorMessage : undefined}
          actionTitle="Try again"
          onAction={handleRetry}
          style={styles.stateContent}
        />
      </Card>
    ) : undefined;

  const shownItems = showAllRuns ? items : items.slice(0, RUNS_FOLDED);
  const footer = isLoadingMore ? (
    <ActivityIndicator style={styles.footerSpinner} color={Colors.systemGray} />
  ) : !showAllRuns && total > RUNS_FOLDED ? (
    <Button
      title={`Show all ${total} scheduled results`}
      variant="plain"
      onPress={() => setShowAllRuns(true)}
      containerStyle={styles.showAll}
    />
  ) : undefined;

  return (
    <View style={styles.container}>
      <FlatList
        style={styles.list}
        contentContainerStyle={styles.listContent}
        data={shownItems}
        keyExtractor={(item) => item.run_id}
        renderItem={renderItem}
        ListHeaderComponent={header}
        ListEmptyComponent={emptyState}
        ListFooterComponent={footer}
        onEndReached={handleLoadMore}
        onEndReachedThreshold={0.4}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={handleRefresh}
            tintColor={Colors.systemGray}
          />
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingBottom: 32,
    flexGrow: 1,
  },
  // The iOS grouped-section header, as ListSection draws it.
  sectionHeader: {
    marginHorizontal: ScreenMargin,
    paddingHorizontal: 16,
    marginBottom: 7,
    textTransform: 'uppercase',
    letterSpacing: 0.2,
  },
  resultSpacing: {
    marginHorizontal: ScreenMargin,
    marginBottom: 10,
  },
  // Card's surface, for the pressable results.
  resultCard: {
    backgroundColor: Colors.secondaryGroupedBackground,
    borderRadius: Radius.lg,
    padding: 16,
  },
  result: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  resultText: {
    flex: 1,
    gap: 3,
  },
  openChatRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    marginTop: 6,
  },
  showAll: {
    alignSelf: 'center',
    marginTop: 2,
  },
  loading: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 32,
  },
  stateCard: {
    marginHorizontal: ScreenMargin,
  },
  stateContent: {
    paddingVertical: 12,
  },
  footerSpinner: {
    marginVertical: 16,
  },
});
