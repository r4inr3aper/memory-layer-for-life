/**
 * Feed Tab Screen ('/(tabs)/feed')
 *
 * "For you": insights from the user's own memories (InsightsSection), then what the
 * assistant did on its own: the results of finished scheduled runs, newest first.
 * Tapping a result that was posted to a chat opens that chat.
 */

import React, { useCallback, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { useFocusEffect } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  AlertCircleIcon,
  ArrowRight01Icon,
  CheckmarkCircle02Icon,
  NewsIcon,
} from '@hugeicons/core-free-icons';
import { InsightsSection } from '@/components/feed/InsightsSection';
import { Colors } from '@/constants/colors';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { listActivity } from '@/lib/api/activity';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import type { ActivityItem, ScheduleDelivery } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';
import { openChatThread } from '@/lib/navigation';

const PAGE_LIMIT = 30;

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
        const message = getErrorMessage(error, 'Could not load your feed');
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
    void loadFirstPage().finally(() => setIsRefreshing(false));
  };

  const handleRetry = () => {
    setStatus('loading');
    void loadFirstPage();
  };

  const handleLoadMore = () => {
    if (status !== 'ready' || isLoadingMore || items.length >= total) return;

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

  const renderItem = ({ item, index }: { item: ActivityItem; index: number }) => {
    const failed = item.status === 'failed';
    const threadId = item.thread_id;
    const body = failed
      ? item.error_message || 'The task could not finish.'
      : item.summary || 'Finished without a summary.';

    return (
      <View>
        <TouchableOpacity
          style={styles.row}
          onPress={threadId ? () => openChatThread(threadId) : undefined}
          disabled={!threadId}
          activeOpacity={0.75}
          accessibilityRole={threadId ? 'button' : undefined}
          accessibilityHint={threadId ? 'Opens the chat with this result' : undefined}>
          <View
            style={[
              styles.iconContainer,
              { backgroundColor: failed ? Colors.errorLight : Colors.successLight },
            ]}>
            <HugeiconsIcon
              icon={failed ? AlertCircleIcon : CheckmarkCircle02Icon}
              size={20}
              color={failed ? Colors.error : Colors.success}
              strokeWidth={2}
            />
          </View>

          <View style={styles.textContainer}>
            <View style={styles.metaRow}>
              <Text style={[styles.statusText, { color: failed ? Colors.error : Colors.success }]}>
                {failed ? 'Failed' : 'Done'}
              </Text>
              <Text style={styles.metaDot}>•</Text>
              <Text style={styles.timeText}>
                {formatRelativeTime(item.finished_at, undefined, 'Recently')}
              </Text>
              {item.delivery !== 'chat' ? (
                <>
                  <Text style={styles.metaDot}>•</Text>
                  <Text style={styles.timeText}>Sent to {DELIVERY_LABEL[item.delivery]}</Text>
                </>
              ) : null}
              {item.trigger === 'manual' ? (
                <>
                  <Text style={styles.metaDot}>•</Text>
                  <Text style={styles.timeText}>Run manually</Text>
                </>
              ) : null}
            </View>

            <Text style={styles.itemTitle}>{item.title}</Text>
            <Text style={[styles.itemSummary, failed && styles.itemError]} numberOfLines={4}>
              {body}
            </Text>

            {threadId ? (
              <View style={styles.openChatRow}>
                <Text style={styles.openChatText}>Open in chat</Text>
                <HugeiconsIcon
                  icon={ArrowRight01Icon}
                  size={14}
                  color={Colors.primary}
                  strokeWidth={2}
                />
              </View>
            ) : null}
          </View>
        </TouchableOpacity>

        {index < items.length - 1 && <View style={styles.divider} />}
      </View>
    );
  };

  const header = (
    <View>
      <View style={styles.titleWrapper}>
        <Text style={styles.pageTitle}>Feed</Text>
        <Text style={styles.pageSubtitle}>
          What your memories show, and what {profile.name} did on your schedules.
        </Text>
      </View>
      <InsightsSection />
    </View>
  );

  const emptyState =
    status === 'loading' ? (
      <View style={styles.stateContainer}>
        <ActivityIndicator color={Colors.primary} />
        <Text style={styles.stateText}>Loading your feed...</Text>
      </View>
    ) : status === 'error' ? (
      <View style={styles.stateContainer}>
        <View style={[styles.stateIcon, { backgroundColor: Colors.errorLight }]}>
          <HugeiconsIcon icon={AlertCircleIcon} size={22} color={Colors.error} />
        </View>
        <Text style={styles.stateTitle}>Couldn&apos;t load your feed</Text>
        <Text style={styles.stateBody}>{errorMessage}</Text>
        <TouchableOpacity style={styles.retryBtn} onPress={handleRetry} activeOpacity={0.8}>
          <Text style={styles.retryText}>Try again</Text>
        </TouchableOpacity>
      </View>
    ) : (
      <View style={styles.stateContainer}>
        <View style={styles.stateIcon}>
          <HugeiconsIcon icon={NewsIcon} size={22} color={Colors.primary} />
        </View>
        <Text style={styles.stateTitle}>Nothing here yet</Text>
        <Text style={styles.stateBody}>Results of your scheduled tasks appear here.</Text>
      </View>
    );

  return (
    <View style={styles.container}>
      <FlatList
        style={styles.list}
        contentContainerStyle={styles.listContent}
        data={items}
        keyExtractor={(item) => item.run_id}
        renderItem={renderItem}
        ListHeaderComponent={header}
        ListEmptyComponent={emptyState}
        ListFooterComponent={
          isLoadingMore ? (
            <ActivityIndicator style={styles.footerSpinner} color={Colors.primary} />
          ) : undefined
        }
        onEndReached={handleLoadMore}
        onEndReachedThreshold={0.4}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={handleRefresh}
            tintColor={Colors.primary}
          />
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingBottom: 24,
    flexGrow: 1,
  },
  titleWrapper: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 14,
  },
  pageTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.5,
  },
  pageSubtitle: {
    marginTop: 4,
    fontSize: 14,
    lineHeight: 20,
    color: Colors.textSecondary,
    fontWeight: '500',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingHorizontal: 20,
    paddingVertical: 18,
    gap: 14,
  },
  iconContainer: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  textContainer: {
    flex: 1,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 5,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '800',
  },
  metaDot: {
    fontSize: 12,
    color: Colors.textMuted,
  },
  timeText: {
    fontSize: 12,
    fontWeight: '600',
    color: Colors.textMuted,
  },
  itemTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.iconDark,
    lineHeight: 22,
    letterSpacing: -0.2,
  },
  itemSummary: {
    marginTop: 6,
    fontSize: 14,
    fontWeight: '400',
    color: Colors.textSecondary,
    lineHeight: 20,
  },
  itemError: {
    color: Colors.error,
  },
  openChatRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 10,
  },
  openChatText: {
    fontSize: 12.5,
    fontWeight: '700',
    color: Colors.primary,
  },
  divider: {
    height: 1,
    backgroundColor: Colors.borderLight,
    marginHorizontal: 20,
  },
  stateContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 36,
    paddingVertical: 72,
  },
  stateIcon: {
    width: 48,
    height: 48,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.primarySubtle,
    marginBottom: 14,
  },
  stateText: {
    marginTop: 12,
    fontSize: 14,
    color: Colors.textSecondary,
    fontWeight: '600',
  },
  stateTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  stateBody: {
    marginTop: 6,
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'center',
    color: Colors.textSecondary,
  },
  retryBtn: {
    marginTop: 16,
    paddingHorizontal: 16,
    paddingVertical: 9,
    borderRadius: 12,
    backgroundColor: Colors.primary,
  },
  retryText: {
    fontSize: 13,
    fontWeight: '700',
    color: Colors.white,
  },
  footerSpinner: {
    marginVertical: 16,
  },
});
