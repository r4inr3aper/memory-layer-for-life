/**
 * Help & Feedback Screen ('/help')
 *
 * A short FAQ and a feedback form that sends the message to the team (`POST /feedback`)
 * with the platform and app version. A pushed screen with a large title over
 * inset-grouped sections; Send is the one filled button.
 */

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, TextInput, View } from 'react-native';
import Animated from 'react-native-reanimated';
import Constants from 'expo-constants';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  AppText,
  Button,
  LargeTitle,
  ListSection,
  ScreenHeader,
  useScrollY,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { ScreenMargin, Typography } from '@/constants/theme';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage } from '@/lib/api/client';
import { sendFeedback } from '@/lib/api/me';
import type { DevicePlatform } from '@/lib/api/types';
import { haptic } from '@/lib/haptics';

const FEEDBACK_MAX_LENGTH = 4000;

interface FaqEntry {
  question: string;
  answer: string;
}

function buildFaq(agentName: string): FaqEntry[] {
  return [
    {
      question: `What can ${agentName} do?`,
      answer:
        `${agentName} answers questions, researches on the web, and works in the apps you ` +
        'connect, such as reading your email or posting to Slack. Ask in your own words in ' +
        'the chat; you can attach images and PDFs too.',
    },
    {
      question: 'How do schedules work?',
      answer:
        `Ask for something on a schedule, like "every weekday at 8:00, summarize my inbox". ` +
        `${agentName} proposes it as a card and nothing runs until you confirm. You can also ` +
        'tap New on the Tasks tab. Pause or run schedules there; results show up in the Feed ' +
        'and in the chat.',
    },
    {
      question: 'How do I connect apps?',
      answer:
        'Open Settings, then Tools & Connections, and tap Connect next to an app. You sign in ' +
        'to the app in your browser to allow access, and you can disconnect it from the same ' +
        'screen at any time.',
    },
    {
      question: 'Your data and deleting your account',
      answer:
        `Your chats, schedules, and app connections are stored so ${agentName} can use them. ` +
        'Files you attach in chat are read with your message and not kept; to keep one for ' +
        `${agentName}, such as your resume, add it in Settings, Files & links (only its text ` +
        'is stored, and deleting it removes it). To remove everything, use Delete account in ' +
        'Settings: it disconnects your apps and permanently deletes your data.',
    },
  ];
}

/** The platform as the backend names it, when it is one it knows. */
function getDevicePlatform(): DevicePlatform | undefined {
  return Platform.OS === 'ios' || Platform.OS === 'android' || Platform.OS === 'web'
    ? Platform.OS
    : undefined;
}

export default function HelpScreen() {
  const { profile } = useAgentProfile();
  const insets = useSafeAreaInsets();
  const { scrollY, onScroll } = useScrollY();
  const [message, setMessage] = useState('');
  const [isSending, setIsSending] = useState(false);

  const trimmed = message.trim();
  const canSend = trimmed.length > 0 && !isSending;

  const handleSend = async () => {
    if (!canSend) return;

    setIsSending(true);
    try {
      await sendFeedback({
        message: trimmed,
        platform: getDevicePlatform(),
        app_version: Constants.expoConfig?.version,
      });
      setMessage('');
      haptic.success();
      showToast('Thanks! Your feedback was sent.');
    } catch (error) {
      console.error('Failed to send feedback:', error);
      haptic.error();
      showToast(getErrorMessage(error, 'Could not send your feedback'));
    } finally {
      setIsSending(false);
    }
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      <ScreenHeader title="Help & Feedback" scrollY={scrollY} />

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <Animated.ScrollView
          style={styles.flex}
          contentContainerStyle={{ paddingBottom: insets.bottom + 32 }}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="interactive"
          onScroll={onScroll}
          scrollEventThrottle={16}>
          <LargeTitle title="Help & Feedback" />

          <ListSection header="Frequently asked">
            {buildFaq(profile.name).map((entry) => (
              <View key={entry.question} style={styles.faqItem}>
                <AppText variant="headline">{entry.question}</AppText>
                <AppText variant="subheadline" color="secondary">
                  {entry.answer}
                </AppText>
              </View>
            ))}
          </ListSection>

          <ListSection
            header="Send feedback"
            footer="Your message goes to the team with your platform and app version.">
            <View style={styles.feedbackCell}>
              <TextInput
                style={styles.feedbackInput}
                value={message}
                onChangeText={setMessage}
                placeholder="What's working, what isn't, or what you'd like next..."
                placeholderTextColor={Colors.placeholder}
                selectionColor={Colors.tint}
                multiline
                maxLength={FEEDBACK_MAX_LENGTH}
                textAlignVertical="top"
                editable={!isSending}
                accessibilityLabel="Feedback"
              />
              <AppText variant="caption1" color="tertiary" align="right">
                {message.length.toLocaleString()} / {FEEDBACK_MAX_LENGTH.toLocaleString()}
              </AppText>
            </View>
          </ListSection>

          <Button
            title="Send"
            variant="filled"
            size="large"
            block
            onPress={handleSend}
            loading={isSending}
            disabled={trimmed.length === 0}
            containerStyle={styles.sendButton}
          />
        </Animated.ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
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
  faqItem: {
    gap: 4,
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: Colors.secondaryGroupedBackground,
  },
  feedbackCell: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 10,
    gap: 6,
    backgroundColor: Colors.secondaryGroupedBackground,
  },
  feedbackInput: {
    ...Typography.body,
    minHeight: 140,
    padding: 0,
    color: Colors.label,
  },
  sendButton: {
    marginHorizontal: ScreenMargin,
  },
});
