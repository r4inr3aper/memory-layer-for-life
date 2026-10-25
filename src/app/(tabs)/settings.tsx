/**
 * Settings Tab Screen ('/(tabs)/settings')
 *
 * Clean settings & account management:
 * - Today's usage meter (prompts used against the daily limit) and cost history
 * - Settings items (Tools & Connections, Memories, Notifications, Help & Feedback)
 * - Account: Export my data, Sign Out, and Delete account
 */

import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  Grid02Icon,
  Brain01Icon,
  Notification01Icon,
  ArrowRight01Icon,
  HelpCircleIcon,
  Logout01Icon,
  UserRemove01Icon,
  Download01Icon,
  Upload01Icon,
} from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { deleteAccount, getUsage } from '@/lib/api/me';
import type { AccountDeletion, Usage } from '@/lib/api/types';
import { alertAsync, confirmAsync } from '@/lib/dialogs';
import { formatResetTime } from '@/lib/formatTime';
import { formatCost } from '@/lib/usageChart';
import { CostHistory } from '@/components/settings/CostHistory';
import { signOut, signOutDeletedAccount } from '@/lib/session';
import { exportMyData } from '@/lib/dataExport';

export default function SettingsScreen() {
  const router = useRouter();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  const loadUsage = useCallback((signal?: AbortSignal) => {
    getUsage(signal)
      .then((nextUsage) => {
        setUsage(nextUsage);
        setUsageError(null);
      })
      .catch((error) => {
        if (isAbortError(error, signal)) return;
        console.error('Failed to load usage:', error);
        setUsageError(getErrorMessage(error, "Couldn't load your usage"));
      });
  }, []);

  // Refresh the meter whenever Settings is opened (tabs stay mounted).
  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      loadUsage(controller.signal);
      return () => controller.abort();
    }, [loadUsage])
  );

  const handleSignOut = async () => {
    if (isSigningOut) return;
    const confirmed = await confirmAsync({
      title: 'Sign out?',
      message: "You'll need to sign in with Google again to use the app.",
      confirmText: 'Sign out',
      destructive: true,
    });
    if (!confirmed) return;

    setIsSigningOut(true);
    const { error } = await signOut();
    if (error) {
      setIsSigningOut(false);
      showToast(getErrorMessage(error, 'Could not sign out'));
      return;
    }
    showToast('Signed Out');
    router.replace('/');
  };

  const handleExport = async () => {
    if (isExporting) return;
    setIsExporting(true);
    try {
      await exportMyData();
    } catch (error) {
      console.error('Failed to export data:', error);
      showToast(getErrorMessage(error, 'Could not export your data'), 3500);
    } finally {
      setIsExporting(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (isDeleting) return;

    const wantsToDelete = await confirmAsync({
      title: 'Delete your account?',
      message:
        'This permanently deletes your chats, memories, schedules, and app connections. ' +
        'Export your data first if you want a copy. ' +
        "It can't be undone.",
      confirmText: 'Continue',
      destructive: true,
    });
    if (!wantsToDelete) return;

    const isSure = await confirmAsync({
      title: 'Are you sure?',
      message: 'Your account and everything in it will be deleted for good.',
      confirmText: 'Delete account',
      destructive: true,
    });
    if (!isSure) return;

    setIsDeleting(true);
    let result: AccountDeletion;
    try {
      result = await deleteAccount();
    } catch (error) {
      console.error('Failed to delete account:', error);
      showToast(getErrorMessage(error, 'Could not delete your account'), 3500);
      setIsDeleting(false);
      return;
    }

    const leftConnected = result.apps_not_disconnected;
    if (leftConnected > 0) {
      await alertAsync(
        'Revoke remaining app access',
        `${leftConnected} connected ${leftConnected === 1 ? 'app' : 'apps'} could not be ` +
          `disconnected automatically. Remove Zoop's access in ${
            leftConnected === 1 ? "that app's" : "those apps'"
          } account settings (for example, your Google or Slack security settings).`
      );
    }

    const { error } = await signOutDeletedAccount();
    if (error) {
      console.warn('Sign-out after account deletion failed:', error);
    }
    showToast('Your account was deleted');
    router.replace('/');
  };

  const promptLimit = usage?.prompt_limit ?? null;
  const percentUsed =
    usage && promptLimit !== null
      ? promptLimit > 0
        ? Math.min(100, Math.round((usage.prompts_used / promptLimit) * 100))
        : 100
      : null;

  return (
    <View style={styles.container}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}>
        {/* Title */}
        <View style={styles.headerRow}>
          <Text style={styles.pageTitle}>Settings</Text>
        </View>

        {/* 1. Usage Card */}
        <View style={styles.planCard}>
          <View style={styles.planHeaderRow}>
            <Text style={styles.planTitle}>Today</Text>
            {percentUsed !== null ? (
              <Text style={styles.planUsageText}>{percentUsed}% used</Text>
            ) : null}
          </View>

          {usage ? (
            <>
              <Text style={styles.planResetText}>
                {promptLimit !== null
                  ? `${usage.prompts_used.toLocaleString()} of ${promptLimit.toLocaleString()} prompts used`
                  : `${usage.prompts_used.toLocaleString()} ${usage.prompts_used === 1 ? 'prompt' : 'prompts'} used`}
                {` · ${formatCost(usage.estimated_cost, usage.currency)} spent`}
              </Text>
              {percentUsed !== null ? (
                <View style={styles.progressBarTrack}>
                  <View
                    style={[
                      styles.progressBarFill,
                      { width: `${percentUsed}%` },
                      percentUsed >= 100 && styles.progressBarFull,
                    ]}
                  />
                </View>
              ) : null}
              <Text style={[styles.planResetText, styles.usageLastLine]}>
                Resets {formatResetTime(usage.resets_at)}
              </Text>
              <CostHistory />
            </>
          ) : usageError ? (
            <TouchableOpacity
              onPress={() => {
                setUsageError(null);
                loadUsage();
              }}
              activeOpacity={0.7}
              accessibilityRole="button">
              <Text style={styles.usageErrorText}>{usageError}</Text>
              <Text style={styles.retryText}>Try again</Text>
            </TouchableOpacity>
          ) : (
            <ActivityIndicator style={styles.usageSpinner} color={Colors.primary} />
          )}
        </View>

        {/* 2. Primary Group: Tools & Connections */}
        <View style={styles.groupCard}>
          <TouchableOpacity
            style={styles.listItem}
            onPress={() => router.push('/tools')}
            activeOpacity={0.65}>
            <View style={styles.listIconCol}>
              <HugeiconsIcon icon={Grid02Icon} size={22} color={Colors.iconDark} strokeWidth={2} />
            </View>
            <Text style={styles.listLabel}>Tools & Connections</Text>
            <HugeiconsIcon
              icon={ArrowRight01Icon}
              size={20}
              color={Colors.iconMuted}
              strokeWidth={1.8}
            />
          </TouchableOpacity>
        </View>

        {/* 3. Secondary Group: Preferences & Support */}
        <View style={styles.groupCard}>
          <TouchableOpacity
            style={styles.listItem}
            onPress={() => router.push('/memories')}
            activeOpacity={0.65}>
            <View style={styles.listIconCol}>
              <HugeiconsIcon icon={Brain01Icon} size={22} color={Colors.iconDark} strokeWidth={2} />
            </View>
            <Text style={styles.listLabel}>Memories</Text>
            <HugeiconsIcon
              icon={ArrowRight01Icon}
              size={20}
              color={Colors.iconMuted}
              strokeWidth={1.8}
            />
          </TouchableOpacity>

          <View style={styles.rowDivider} />

          <TouchableOpacity
            style={styles.listItem}
            onPress={() => router.push('/import')}
            activeOpacity={0.65}>
            <View style={styles.listIconCol}>
              <HugeiconsIcon
                icon={Upload01Icon}
                size={22}
                color={Colors.iconDark}
                strokeWidth={2}
              />
            </View>
            <Text style={styles.listLabel}>Import a WhatsApp chat</Text>
            <HugeiconsIcon
              icon={ArrowRight01Icon}
              size={20}
              color={Colors.iconMuted}
              strokeWidth={1.8}
            />
          </TouchableOpacity>

          <View style={styles.rowDivider} />

          <TouchableOpacity
            style={styles.listItem}
            onPress={() => router.push('/notifications')}
            activeOpacity={0.65}>
            <View style={styles.listIconCol}>
              <HugeiconsIcon
                icon={Notification01Icon}
                size={22}
                color={Colors.iconDark}
                strokeWidth={2}
              />
            </View>
            <Text style={styles.listLabel}>Notifications</Text>
            <HugeiconsIcon
              icon={ArrowRight01Icon}
              size={20}
              color={Colors.iconMuted}
              strokeWidth={1.8}
            />
          </TouchableOpacity>

          <View style={styles.rowDivider} />

          <TouchableOpacity
            style={styles.listItem}
            onPress={() => router.push('/help')}
            activeOpacity={0.65}>
            <View style={styles.listIconCol}>
              <HugeiconsIcon
                icon={HelpCircleIcon}
                size={22}
                color={Colors.iconDark}
                strokeWidth={2}
              />
            </View>
            <Text style={styles.listLabel}>Help & Feedback</Text>
            <HugeiconsIcon
              icon={ArrowRight01Icon}
              size={20}
              color={Colors.iconMuted}
              strokeWidth={1.8}
            />
          </TouchableOpacity>
        </View>

        {/* 4. Account Group: Export, Sign Out & Delete account */}
        <View style={styles.groupCard}>
          <TouchableOpacity
            style={styles.listItem}
            onPress={handleExport}
            disabled={isExporting}
            activeOpacity={0.65}
            accessibilityHint="Saves everything Zoop holds for you as one file">
            <View style={styles.listIconCol}>
              <HugeiconsIcon
                icon={Download01Icon}
                size={22}
                color={Colors.iconDark}
                strokeWidth={2}
              />
            </View>
            <Text style={styles.listLabel}>
              {isExporting ? 'Preparing your data...' : 'Export my data'}
            </Text>
            {isExporting ? (
              <ActivityIndicator size="small" color={Colors.primary} />
            ) : (
              <HugeiconsIcon
                icon={ArrowRight01Icon}
                size={20}
                color={Colors.iconMuted}
                strokeWidth={1.8}
              />
            )}
          </TouchableOpacity>

          <View style={styles.rowDivider} />

          <TouchableOpacity
            style={styles.listItem}
            onPress={handleSignOut}
            disabled={isSigningOut}
            activeOpacity={0.65}>
            <View style={styles.listIconCol}>
              <HugeiconsIcon icon={Logout01Icon} size={22} color={Colors.error} strokeWidth={2} />
            </View>
            <Text style={[styles.listLabel, { color: Colors.error }]}>
              {isSigningOut ? 'Signing out...' : 'Sign Out'}
            </Text>
            {isSigningOut ? (
              <ActivityIndicator size="small" color={Colors.error} />
            ) : (
              <HugeiconsIcon
                icon={ArrowRight01Icon}
                size={20}
                color={Colors.iconMuted}
                strokeWidth={1.8}
              />
            )}
          </TouchableOpacity>

          <View style={styles.rowDivider} />

          <TouchableOpacity
            style={styles.listItem}
            onPress={handleDeleteAccount}
            disabled={isDeleting}
            activeOpacity={0.65}>
            <View style={styles.listIconCol}>
              <HugeiconsIcon
                icon={UserRemove01Icon}
                size={22}
                color={Colors.error}
                strokeWidth={2}
              />
            </View>
            <Text style={[styles.listLabel, { color: Colors.error }]}>
              {isDeleting ? 'Deleting account...' : 'Delete account'}
            </Text>
            {isDeleting ? (
              <ActivityIndicator size="small" color={Colors.error} />
            ) : (
              <HugeiconsIcon
                icon={ArrowRight01Icon}
                size={20}
                color={Colors.iconMuted}
                strokeWidth={1.8}
              />
            )}
          </TouchableOpacity>
        </View>

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 24,
  },
  headerRow: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 16,
  },
  pageTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.5,
  },
  planCard: {
    marginHorizontal: 20,
    marginBottom: 20,
    backgroundColor: '#FAFAFB',
    borderRadius: 20,
    padding: 18,
    borderWidth: 1,
    borderColor: '#ECEEF0',
  },
  planHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  planTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.2,
  },
  planUsageText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#0066FF',
  },
  planResetText: {
    fontSize: 12.5,
    color: '#707070',
    marginBottom: 12,
  },
  progressBarTrack: {
    height: 6,
    backgroundColor: '#E6E8EA',
    borderRadius: 3,
    overflow: 'hidden',
    marginBottom: 14,
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#0066FF',
    borderRadius: 3,
  },
  progressBarFull: {
    backgroundColor: Colors.error,
  },
  usageLastLine: {
    marginBottom: 0,
  },
  usageErrorText: {
    fontSize: 13,
    lineHeight: 18,
    color: Colors.error,
  },
  retryText: {
    marginTop: 6,
    fontSize: 13.5,
    fontWeight: '700',
    color: Colors.primary,
  },
  usageSpinner: {
    alignSelf: 'flex-start',
    marginVertical: 6,
  },
  groupCard: {
    marginHorizontal: 20,
    marginBottom: 16,
    backgroundColor: '#FAFAFB',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#ECEEF0',
    overflow: 'hidden',
  },
  listItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 15,
    paddingHorizontal: 16,
  },
  listIconCol: {
    width: 32,
    alignItems: 'flex-start',
  },
  listLabel: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
    color: Colors.iconDark,
    letterSpacing: -0.2,
  },
  rowDivider: {
    height: 1,
    backgroundColor: '#F0F0F2',
    marginLeft: 48,
  },
});
