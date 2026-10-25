/**
 * InsightsSection Component
 *
 * "For you" at the top of the Feed: what the user's own memories show over time (money
 * noted, people on their mind or gone quiet, how much they finish, quiet goals, recurring
 * themes). Each card opens what it is about and takes a thumbs up or down; thumbs down
 * hides it. Loads whenever the Feed is shown; shows nothing when there is nothing to say.
 */

import React, { useCallback, useState } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { BulbIcon, ThumbsDownIcon, ThumbsUpIcon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { listInsights, sendInsightFeedback } from '@/lib/api/insights';
import type { Insight } from '@/lib/api/types';

export function InsightsSection() {
  const router = useRouter();
  const [insights, setInsights] = useState<Insight[]>([]);
  const [thanked, setThanked] = useState<ReadonlySet<string>>(new Set());

  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      listInsights(controller.signal)
        .then(setInsights)
        .catch((error) => {
          if (isAbortError(error, controller.signal)) return;
          // The rest of the Feed still works; insights are a bonus.
          console.warn('Failed to load insights:', error);
        });
      return () => controller.abort();
    }, [])
  );

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
      <Text style={styles.sectionTitle}>For you</Text>
      {insights.map((insight) => (
        <TouchableOpacity
          key={insight.key}
          style={styles.card}
          onPress={() => open(insight)}
          activeOpacity={0.8}
          accessibilityRole="button">
          <View style={styles.cardHeader}>
            <View style={styles.icon}>
              <HugeiconsIcon icon={BulbIcon} size={16} color={Colors.primary} />
            </View>
            <Text style={styles.title}>{insight.title}</Text>
          </View>
          <Text style={styles.body}>{insight.body}</Text>
          <View style={styles.footer}>
            <Text style={styles.evidence}>
              Based on {insight.memory_ids.length}{' '}
              {insight.memory_ids.length === 1 ? 'memory' : 'memories'}
            </Text>
            {thanked.has(insight.key) ? (
              <Text style={styles.thanks}>Thanks</Text>
            ) : (
              <View style={styles.votes}>
                <TouchableOpacity
                  onPress={() => feedback(insight, true)}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  accessibilityRole="button"
                  accessibilityLabel="Useful">
                  <HugeiconsIcon icon={ThumbsUpIcon} size={18} color={Colors.iconMuted} />
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => feedback(insight, false)}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  accessibilityRole="button"
                  accessibilityLabel="Not useful, hide it">
                  <HugeiconsIcon icon={ThumbsDownIcon} size={18} color={Colors.iconMuted} />
                </TouchableOpacity>
              </View>
            )}
          </View>
        </TouchableOpacity>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    marginBottom: 12,
    gap: 10,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: Colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  card: {
    padding: 14,
    borderRadius: 16,
    backgroundColor: Colors.primarySubtle,
    gap: 6,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  icon: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: Colors.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    flex: 1,
    fontSize: 15,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  body: {
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.textPrimary,
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 2,
  },
  evidence: {
    fontSize: 12,
    color: Colors.textSecondary,
  },
  votes: {
    flexDirection: 'row',
    gap: 16,
  },
  thanks: {
    fontSize: 12.5,
    fontWeight: '600',
    color: Colors.success,
  },
});

export default InsightsSection;
