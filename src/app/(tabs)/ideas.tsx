/**
 * Ideas Tab Screen ('/(tabs)/ideas')
 *
 * The user's own ideas, from their memories (things to build, try, or explore that they
 * told their assistant), newest first: tap one to see where it came from, or "Explore" to
 * think it through in chat. Below, a few things the assistant can do, as prompts to try.
 * Tapping either puts a prompt in the chat input, ready to edit and send.
 *
 * Laid out as an iOS grouped screen: a large title, the ideas as an inset-grouped list,
 * and the prompts as pressable cards on the grouped background.
 */

import React, { useCallback, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import Animated from 'react-native-reanimated';
import { useFocusEffect, useRouter } from 'expo-router';
import { AlertCircleIcon, Idea01Icon } from '@hugeicons/core-free-icons';
import {
  AppText,
  Button,
  Card,
  EmptyState,
  LargeTitle,
  ListSection,
  PressableScale,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Radius, ScreenMargin, continuous } from '@/constants/theme';
import { IDEA_ITEMS } from '@/constants/dummyData';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { listMyMemories } from '@/lib/api/memories';
import type { MemoryItem } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';
import { openChatWithPrefill } from '@/lib/navigation';

const IDEAS_LIMIT = 50;
const IDEAS_ERROR_FALLBACK = "Couldn't load your ideas";

export default function IdeasScreen() {
  const router = useRouter();
  const { profile } = useAgentProfile();
  const [ideas, setIdeas] = useState<MemoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const load = useCallback((signal?: AbortSignal) => {
    return listMyMemories({ memory_type: 'idea', limit: IDEAS_LIMIT }, signal)
      .then((page) => {
        setIdeas(page.items);
        setError(null);
      })
      .catch((loadError) => {
        if (isAbortError(loadError, signal)) return;
        setError(getErrorMessage(loadError, IDEAS_ERROR_FALLBACK));
      });
  }, []);

  // Tabs stay mounted, so reload whenever Ideas is shown: new ideas arrive from chats.
  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [load])
  );

  const explore = (idea: MemoryItem) =>
    openChatWithPrefill(
      `Let's explore my idea: ${idea.title || idea.content}. What would a small first step be?`
    );

  return (
    <View style={styles.container}>
      <ScrollView
        style={styles.scrollArea}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
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
        <LargeTitle
          title="Ideas"
          subtitle={`Things to build, try, or explore, saved from what you tell ${profile.name}.`}
        />

        {error ? (
          <Card style={styles.stateCard}>
            <EmptyState
              compact
              icon={AlertCircleIcon}
              title={IDEAS_ERROR_FALLBACK}
              message={error !== IDEAS_ERROR_FALLBACK ? error : undefined}
              actionTitle="Try again"
              onAction={() => void load()}
              style={styles.stateContent}
            />
          </Card>
        ) : null}

        {ideas === null && !error ? (
          <View style={styles.loading}>
            <ActivityIndicator color={Colors.systemGray} />
          </View>
        ) : null}

        {ideas !== null && ideas.length === 0 ? (
          <Card style={styles.stateCard}>
            <EmptyState
              compact
              icon={Idea01Icon}
              title="Your ideas collect here"
              message={`Tell ${profile.name} one, like "idea: a shared grocery list that sorts itself by aisle".`}
              style={styles.stateContent}
            />
          </Card>
        ) : null}

        {ideas?.length ? (
          <ListSection header={`Your ideas · ${ideas.length}`}>
            {ideas.map((idea) => (
              <IdeaRow
                key={idea.id}
                title={idea.title || idea.content}
                meta={`Noted ${formatRelativeTime(idea.observed_at ?? idea.created_at)}`}
                onOpen={() => router.push({ pathname: '/memories/[id]', params: { id: idea.id } })}
                onExplore={() => explore(idea)}
                exploreLabel={`Explore ${idea.title || idea.content} with ${profile.name}`}
              />
            ))}
          </ListSection>
        ) : null}

        <AppText variant="footnote" color="secondary" style={styles.sectionHeader}>
          Things to try
        </AppText>
        <View style={styles.prompts}>
          {IDEA_ITEMS.map((item) => (
            // PressableScale styled as Card, so the card keeps its accessibility hint
            // (Card does not pass one through).
            <PressableScale
              key={item.id}
              onPress={() => openChatWithPrefill(item.prompt)}
              pressedScale={0.98}
              accessibilityRole="button"
              accessibilityHint="Opens the chat with this idea's prompt"
              style={[styles.promptCard, continuous]}>
              <View style={[styles.promptIcon, continuous]}>
                <AppText variant="title2">{item.icon}</AppText>
              </View>
              <View style={styles.promptText}>
                <AppText variant="headline">{item.title}</AppText>
                <AppText variant="subheadline" color="secondary" numberOfLines={4}>
                  {item.description}
                </AppText>
              </View>
            </PressableScale>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

/**
 * One of the user's ideas, as a list cell: the text opens where it came from, and the
 * tinted Explore capsule beside it (a sibling, so VoiceOver reaches both) starts a chat.
 * The cell highlights while the text is pressed: at once on touch down, fading out after
 * release, as ListRow does.
 */
function IdeaRow({
  title,
  meta,
  onOpen,
  onExplore,
  exploreLabel,
}: {
  title: string;
  meta: string;
  onOpen: () => void;
  onExplore: () => void;
  exploreLabel: string;
}) {
  const [pressed, setPressed] = useState(false);
  return (
    <Animated.View style={[styles.ideaRow, pressed ? styles.rowPressed : styles.rowIdle]}>
      <Pressable
        style={styles.ideaBody}
        onPress={onOpen}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        unstable_pressDelay={40}
        pressRetentionOffset={16}
        accessibilityRole="button"
        accessibilityHint="Opens where this idea came from">
        <AppText variant="body" numberOfLines={3}>
          {title}
        </AppText>
        <AppText variant="footnote" color="secondary">
          {meta}
        </AppText>
      </Pressable>
      <Button
        title="Explore"
        variant="tinted"
        size="small"
        onPress={onExplore}
        accessibilityLabel={exploreLabel}
        containerStyle={styles.exploreButton}
      />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 32,
  },
  loading: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 40,
  },
  stateCard: {
    marginHorizontal: ScreenMargin,
    marginBottom: 28,
  },
  stateContent: {
    paddingVertical: 12,
  },
  // The iOS grouped-section header, as ListSection draws it.
  sectionHeader: {
    marginHorizontal: ScreenMargin,
    paddingHorizontal: 16,
    marginBottom: 7,
    textTransform: 'uppercase',
    letterSpacing: 0.2,
  },
  ideaRow: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    paddingRight: 16,
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  rowPressed: {
    backgroundColor: Colors.cellPressed,
    transitionDuration: 0,
  },
  rowIdle: {
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionDuration: 350,
  },
  ideaBody: {
    flex: 1,
    gap: 2,
    paddingLeft: 16,
    paddingRight: 12,
    paddingVertical: 11,
  },
  exploreButton: {
    flexShrink: 0,
  },
  prompts: {
    marginHorizontal: ScreenMargin,
    gap: 10,
  },
  // Card's surface.
  promptCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 14,
    backgroundColor: Colors.secondaryGroupedBackground,
    borderRadius: Radius.lg,
    padding: 16,
  },
  promptIcon: {
    width: 44,
    height: 44,
    borderRadius: Radius.md,
    backgroundColor: Colors.tertiaryFill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  promptText: {
    flex: 1,
    gap: 4,
  },
});
