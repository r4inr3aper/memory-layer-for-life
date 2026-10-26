/**
 * InsightsSection Component
 *
 * "This week" on the Feed, under Today: what the user's own memories show over time
 * (money noted, people on their mind or gone quiet, how much they finish, quiet goals,
 * recurring themes), each shown only when enough evidence supports it. Each compact card
 * opens what it is about and takes a thumbs up or down; thumbs down hides it, and the
 * cards below close the gap. Loads whenever the Feed is shown and when `refreshKey`
 * changes; shows nothing when there is nothing to say.
 *
 * Primitives are imported from their own files (not the `@/components/ui` index) so the
 * section's test does not load the sheet and header modules it never renders.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { FadeOut, LinearTransition } from 'react-native-reanimated';
import { useFocusEffect, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { BulbIcon, ThumbsDownIcon, ThumbsUpIcon } from '@hugeicons/core-free-icons';
import { AppText } from '@/components/ui/AppText';
import { Card } from '@/components/ui/Card';
import { IconButton } from '@/components/ui/IconButton';
import { Colors } from '@/constants/colors';
import { Motion, ScreenMargin } from '@/constants/theme';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { listInsights, sendInsightFeedback } from '@/lib/api/insights';
import type { Insight } from '@/lib/api/types';

// A hidden card fades out; the cards below slide up into its place. Built once, at module
// scope. Reanimated skips both with Reduce Motion on.
const CARD_EXIT = FadeOut.duration(Motion.duration.small).easing(Motion.easeOut);
const CARD_REFLOW = LinearTransition.duration(240).easing(Motion.easeInOut);

export function InsightsSection({ refreshKey = 0 }: { refreshKey?: number }) {
  const router = useRouter();
  const [insights, setInsights] = useState<Insight[]>([]);
  const [thanked, setThanked] = useState<ReadonlySet<string>>(new Set());

  const load = useCallback((signal?: AbortSignal) => {
    listInsights(signal)
      .then(setInsights)
      .catch((error) => {
        if (isAbortError(error, signal)) return;
        // The rest of the Feed still works; insights are a bonus.
        console.warn('Failed to load insights:', error);
      });
  }, []);

  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      load(controller.signal);
      return () => controller.abort();
    }, [load])
  );

  useEffect(() => {
    if (refreshKey > 0) load();
  }, [refreshKey, load]);

  const open = (insight: Insight) => {
    if (insight.target === 'person' && insight.target_id) {
      router.push({ pathname: '/people/[id]', params: { id: insight.target_id } });
    } else if (insight.target === 'memory' && insight.target_id) {
      router.push({ pathname: '/memories/[id]', params: { id: insight.target_id } });
    } else if (insight.target === 'todo') {
      router.navigate('/(tabs)/tasks');
    } else {
      router.push('/memories');
    }
  };

  const feedback = async (insight: Insight, useful: boolean) => {
    if (!useful) {
      setInsights((current) => current.filter((item) => item.key !== insight.key));
    } else {
      setThanked((current) => new Set(current).add(insight.key));
    }
    try {
      await sendInsightFeedback(insight.key, insight.kind, useful);
    } catch (error) {
      showToast(getErrorMessage(error, 'Could not save your feedback'));
      if (!useful) setInsights((current) => [insight, ...current]);
    }
  };

  if (insights.length === 0) return null;

  return (
    <View style={styles.section}>
      <AppText variant="footnote" color="secondary" style={styles.sectionTitle}>
        This week
      </AppText>
      {insights.map((insight) => (
        <Animated.View key={insight.key} exiting={CARD_EXIT} layout={CARD_REFLOW}>
          <Card onPress={() => open(insight)} style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={styles.icon}>
                <HugeiconsIcon icon={BulbIcon} size={15} color={Colors.tint} strokeWidth={2} />
              </View>
              <AppText variant="headline" style={styles.title}>
                {insight.title}
              </AppText>
            </View>
            <AppText variant="subheadline" color="secondary">
              {insight.body}
            </AppText>
            <View style={styles.footer}>
              <AppText variant="footnote" color="tertiary" style={styles.evidence}>
                Based on {insight.memory_ids.length}{' '}
                {insight.memory_ids.length === 1 ? 'memory' : 'memories'}
              </AppText>
              {thanked.has(insight.key) ? (
                <AppText variant="footnote" color="success" weight="600" style={styles.thanks}>
                  Thanks
                </AppText>
              ) : (
                <View style={styles.votes}>
                  <IconButton
                    icon={ThumbsUpIcon}
                    variant="plain"
                    size={32}
                    iconSize={18}
                    color={Colors.systemGray}
                    haptic="light"
                    onPress={() => feedback(insight, true)}
                    accessibilityLabel="Useful"
                  />
                  <IconButton
                    icon={ThumbsDownIcon}
                    variant="plain"
                    size={32}
                    iconSize={18}
                    color={Colors.systemGray}
                    haptic="light"
                    onPress={() => feedback(insight, false)}
                    accessibilityLabel="Not useful, hide it"
                  />
                </View>
              )}
            </View>
          </Card>
        </Animated.View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    marginHorizontal: ScreenMargin,
    marginBottom: 28,
    gap: 10,
  },
  // The iOS grouped-section header, as ListSection draws it.
  sectionTitle: {
    paddingHorizontal: 16,
    marginBottom: -3,
    textTransform: 'uppercase',
    letterSpacing: 0.2,
  },
  card: {
    paddingTop: 14,
    paddingBottom: 8,
    gap: 6,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  icon: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: Colors.tintFill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    flex: 1,
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 40,
  },
  evidence: {
    flex: 1,
  },
  // Far enough apart that the two 44 pt touch targets do not overlap.
  votes: {
    flexDirection: 'row',
    gap: 12,
    marginRight: -6,
  },
  thanks: {
    paddingRight: 4,
  },
});

export default InsightsSection;
