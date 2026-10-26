/**
 * Settings Tab Screen ('/(tabs)/settings')
 *
 * Laid out as iOS Settings: a large title, then inset-grouped sections of rows on the
 * grouped background, each row marked by a colored glyph tile.
 * - Today: the usage meter (prompts used against the daily limit) and cost history
 * - Tools & Connections, Notifications
 * - Memories, Files & links, Import a WhatsApp chat
 * - Help & Feedback, Export my data
 * - Sign Out and Delete account, in their own section at the bottom
 */

import { CostHistory } from "@/components/settings/CostHistory";
import { AppText, Button, LargeTitle, ListRow, ListSection } from "@/components/ui";
import { Colors } from "@/constants/colors";
import { Radius } from "@/constants/theme";
import { useAgentProfile } from "@/context/AgentProfileContext";
import { showToast } from "@/context/ToastContext";
import { getErrorMessage, isAbortError } from "@/lib/api/client";
import { deleteAccount, getUsage } from "@/lib/api/me";
import type { AccountDeletion, Usage } from "@/lib/api/types";
import { exportMyData } from "@/lib/dataExport";
import { alertAsync, confirmAsync } from "@/lib/dialogs";
import { formatResetTime } from "@/lib/formatTime";
import { signOut, signOutDeletedAccount } from "@/lib/session";
import { formatCost } from "@/lib/usageChart";
import {
  Brain01Icon,
  Download01Icon,
  Folder01Icon,
  Grid02Icon,
  HelpCircleIcon,
  Notification01Icon,
  WhatsappIcon,
} from "@hugeicons/core-free-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, View } from "react-native";

export default function SettingsScreen() {
  const router = useRouter();
  const { profile } = useAgentProfile();
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
        console.error("Failed to load usage:", error);
        setUsageError(getErrorMessage(error, "Couldn't load your usage"));
      });
  }, []);

  // Refresh the meter whenever Settings is opened (tabs stay mounted).
  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      loadUsage(controller.signal);
      return () => controller.abort();
    }, [loadUsage]),
  );

  const handleSignOut = async () => {
    if (isSigningOut) return;
    const confirmed = await confirmAsync({
      title: "Sign out?",
      message: "You'll need to sign in with Google again to use the app.",
      confirmText: "Sign out",
      destructive: true,
    });
    if (!confirmed) return;

    setIsSigningOut(true);
    const { error } = await signOut();
    if (error) {
      setIsSigningOut(false);
      showToast(getErrorMessage(error, "Could not sign out"));
      return;
    }
    showToast("Signed Out");
    router.replace("/");
  };

  const handleExport = async () => {
    if (isExporting) return;
    setIsExporting(true);
    try {
      await exportMyData();
    } catch (error) {
      console.error("Failed to export data:", error);
      showToast(getErrorMessage(error, "Could not export your data"), 3500);
    } finally {
      setIsExporting(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (isDeleting) return;

    const wantsToDelete = await confirmAsync({
      title: "Delete your account?",
      message:
        "This permanently deletes your chats, memories, schedules, and app connections. " +
        "Export your data first if you want a copy. " +
        "It can't be undone.",
      confirmText: "Continue",
      destructive: true,
    });
    if (!wantsToDelete) return;

    const isSure = await confirmAsync({
      title: "Are you sure?",
      message: "Your account and everything in it will be deleted for good.",
      confirmText: "Delete account",
      destructive: true,
    });
    if (!isSure) return;

    setIsDeleting(true);
    let result: AccountDeletion;
    try {
      result = await deleteAccount();
    } catch (error) {
      console.error("Failed to delete account:", error);
      showToast(getErrorMessage(error, "Could not delete your account"), 3500);
      setIsDeleting(false);
      return;
    }

    const leftConnected = result.apps_not_disconnected;
    if (leftConnected > 0) {
      await alertAsync(
        "Revoke remaining app access",
        `${leftConnected} connected ${leftConnected === 1 ? "app" : "apps"} could not be ` +
          `disconnected automatically. Remove Zoop's access in ${
            leftConnected === 1 ? "that app's" : "those apps'"
          } account settings (for example, your Google or Slack security settings).`,
      );
    }

    const { error } = await signOutDeletedAccount();
    if (error) {
      console.warn("Sign-out after account deletion failed:", error);
    }
    showToast("Your account was deleted");
    router.replace("/");
  };

  const promptLimit = usage?.prompt_limit ?? null;
  const percentUsed =
    usage && promptLimit !== null
      ? promptLimit > 0
        ? Math.min(100, Math.round((usage.prompts_used / promptLimit) * 100))
        : 100
      : null;
  const isFull = percentUsed !== null && percentUsed >= 100;

  const busy = (
    <ActivityIndicator size="small" color={Colors.secondaryLabel} />
  );

  return (
    <View style={styles.container}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        <LargeTitle title="Settings" />

        {/* Today's usage: the meter, then cost history as a disclosure row. */}
        <ListSection header="Today">
          <View style={styles.meter}>
            {usage ? (
              <>
                <View style={styles.meterHeader}>
                  <AppText variant="headline" style={styles.meterTitle}>
                    {promptLimit !== null
                      ? `${usage.prompts_used.toLocaleString()} of ${promptLimit.toLocaleString()} prompts used`
                      : `${usage.prompts_used.toLocaleString()} ${usage.prompts_used === 1 ? "prompt" : "prompts"} used`}
                  </AppText>
                  {percentUsed !== null ? (
                    <AppText
                      variant="subheadline"
                      color={isFull ? "destructive" : "secondary"}
                    >
                      {percentUsed}%
                    </AppText>
                  ) : null}
                </View>
                {percentUsed !== null ? (
                  <View style={styles.track}>
                    <View
                      style={[
                        styles.fill,
                        { width: `${percentUsed}%` },
                        isFull && styles.fillFull,
                      ]}
                    />
                  </View>
                ) : null}
                <AppText variant="footnote" color="secondary">
                  {formatCost(usage.estimated_cost, usage.currency)} spent · Resets{" "}
                  {formatResetTime(usage.resets_at)}
                </AppText>
              </>
            ) : usageError ? (
              <View style={styles.usageError}>
                <AppText variant="subheadline" color="destructive">
                  {usageError}
                </AppText>
                <Button
                  title="Try again"
                  variant="plain"
                  size="small"
                  onPress={() => {
                    setUsageError(null);
                    loadUsage();
                  }}
                  containerStyle={styles.retry}
                />
              </View>
            ) : (
              <ActivityIndicator
                style={styles.usageSpinner}
                color={Colors.secondaryLabel}
              />
            )}
          </View>
          {usage ? <CostHistory /> : null}
        </ListSection>

        <ListSection>
          <ListRow
            icon={Grid02Icon}
            iconColor={Colors.systemBlue}
            title="Tools & Connections"
            onPress={() => router.push("/tools")}
          />
          <ListRow
            icon={Notification01Icon}
            iconColor={Colors.systemRed}
            title="Notifications"
            onPress={() => router.push("/notifications")}
          />
        </ListSection>

        <ListSection>
          <ListRow
            icon={Brain01Icon}
            iconColor={Colors.systemPurple}
            title="Memories"
            onPress={() => router.push("/memories")}
          />
          <ListRow
            icon={Folder01Icon}
            iconColor={Colors.systemIndigo}
            title="Files & links"
            subtitle={`Resume, documents, and links ${profile.name} can send`}
            onPress={() => router.push("/files")}
          />
          <ListRow
            icon={WhatsappIcon}
            iconColor={Colors.systemGreen}
            title="Import a WhatsApp chat"
            onPress={() => router.push("/import")}
          />
        </ListSection>

        <ListSection>
          <ListRow
            icon={HelpCircleIcon}
            iconColor={Colors.systemOrange}
            title="Help & Feedback"
            onPress={() => router.push("/help")}
          />
          <ListRow
            icon={Download01Icon}
            iconColor={Colors.systemGray}
            title={isExporting ? "Preparing your data..." : "Export my data"}
            subtitle="Saves everything Zoop holds for you as one file"
            onPress={isExporting ? undefined : handleExport}
            accessory={isExporting ? busy : "none"}
          />
        </ListSection>

        {/* Account actions that end the session, apart from everything else. */}
        <ListSection>
          <ListRow
            title={isSigningOut ? "Signing out..." : "Sign Out"}
            action
            destructive
            onPress={isSigningOut ? undefined : handleSignOut}
            accessory={isSigningOut ? busy : undefined}
          />
          <ListRow
            title={isDeleting ? "Deleting account..." : "Delete account"}
            action
            destructive
            onPress={isDeleting ? undefined : handleDeleteAccount}
            accessory={isDeleting ? busy : undefined}
          />
        </ListSection>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingTop: 8,
    paddingBottom: 24,
  },
  meter: {
    paddingHorizontal: 16,
    paddingVertical: 14,
    gap: 10,
  },
  meterHeader: {
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 12,
  },
  meterTitle: {
    flexShrink: 1,
  },
  track: {
    height: 6,
    borderRadius: Radius.pill,
    backgroundColor: Colors.tertiaryFill,
    overflow: "hidden",
  },
  fill: {
    height: "100%",
    borderRadius: Radius.pill,
    backgroundColor: Colors.tint,
  },
  fillFull: {
    backgroundColor: Colors.systemRed,
  },
  usageError: {
    alignItems: "flex-start",
    gap: 4,
  },
  retry: {
    marginLeft: -4,
  },
  usageSpinner: {
    alignSelf: "flex-start",
    marginVertical: 6,
  },
});
