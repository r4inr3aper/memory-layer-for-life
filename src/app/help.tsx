/**
 * Help & Feedback Screen ('/help')
 *
 * A short FAQ and a feedback form that sends the message to the team (`POST /feedback`)
 * with the platform and app version.
 */

import React, { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import Constants from 'expo-constants';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ScreenHeader } from '@/components/common/ScreenHeader';
import { Colors } from '@/constants/colors';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage } from '@/lib/api/client';
import { sendFeedback } from '@/lib/api/me';
import type { DevicePlatform } from '@/lib/api/types';

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
        'Files you attach are read with your message and not kept. To remove everything, use ' +
        'Delete account in Settings: it disconnects your apps and permanently deletes your data.',
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
      showToast('Thanks! Your feedback was sent.');
    } catch (error) {
      console.error('Failed to send feedback:', error);
      showToast(getErrorMessage(error, 'Could not send your feedback'));
    } finally {
      setIsSending(false);
    }
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right', 'bottom']}>
      <ScreenHeader title="Help & Feedback" />

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          style={styles.flex}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled">
          <Text style={styles.sectionTitle}>Frequently asked</Text>
          <View style={styles.groupCard}>
            {buildFaq(profile.name).map((entry, index) => (
              <View key={entry.question}>
                {index > 0 && <View style={styles.rowDivider} />}
                <View style={styles.faqItem}>
                  <Text style={styles.faqQuestion}>{entry.question}</Text>
                  <Text style={styles.faqAnswer}>{entry.answer}</Text>
                </View>
              </View>
            ))}
          </View>

          <Text style={styles.sectionTitle}>Send feedback</Text>
          <View style={styles.groupCard}>
            <TextInput
              style={styles.feedbackInput}
              value={message}
              onChangeText={setMessage}
              placeholder="What's working, what isn't, or what you'd like next..."
              placeholderTextColor={Colors.iconMuted}
              multiline
              maxLength={FEEDBACK_MAX_LENGTH}
              textAlignVertical="top"
              editable={!isSending}
              accessibilityLabel="Feedback"
            />
            <View style={styles.feedbackFooter}>
              <Text style={styles.counterText}>
                {message.length.toLocaleString()} / {FEEDBACK_MAX_LENGTH.toLocaleString()}
              </Text>
              <TouchableOpacity
                style={[styles.sendBtn, !canSend && styles.sendBtnDisabled]}
                onPress={handleSend}
                disabled={!canSend}
                activeOpacity={0.8}
                accessibilityRole="button">
                {isSending ? (
                  <ActivityIndicator size="small" color={Colors.white} />
                ) : (
                  <Text style={styles.sendText}>Send</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
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
  scrollContent: {
    padding: 20,
    paddingBottom: 40,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: Colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 8,
    marginLeft: 4,
  },
  groupCard: {
    backgroundColor: Colors.surface,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
    overflow: 'hidden',
    marginBottom: 24,
  },
  rowDivider: {
    height: 1,
    backgroundColor: Colors.borderLight,
    marginHorizontal: 16,
  },
  faqItem: {
    paddingVertical: 14,
    paddingHorizontal: 16,
  },
  faqQuestion: {
    fontSize: 15.5,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.2,
  },
  faqAnswer: {
    marginTop: 5,
    fontSize: 14,
    lineHeight: 20,
    color: Colors.textSecondary,
  },
  feedbackInput: {
    minHeight: 140,
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 14,
    fontSize: 15,
    lineHeight: 21,
    color: Colors.iconDark,
  },
  feedbackFooter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingBottom: 14,
  },
  counterText: {
    fontSize: 12,
    color: Colors.iconMuted,
  },
  sendBtn: {
    minWidth: 84,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
    backgroundColor: Colors.primary,
  },
  sendBtnDisabled: {
    opacity: 0.5,
  },
  sendText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.white,
  },
});
