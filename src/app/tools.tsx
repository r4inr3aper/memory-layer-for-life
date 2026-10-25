/**
 * Tools & Connections Screen ('/tools')
 *
 * Minimal list view for tool connections under Settings:
 * - Uncategorized flat list ("Show All")
 * - Displays Tool Icon, Name, and Connect/Disconnect/Manage actions
 * - Composio OAuth linking through the backend API, with polling and AppState refresh
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  AppState,
  AppStateStatus,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as WebBrowser from 'expo-web-browser';
import * as Linking from 'expo-linking';
import { useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { ArrowLeft01Icon, RefreshIcon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { getErrorMessage } from '@/lib/api/client';
import { connectTool, disconnectTool, getToolConnection, listTools } from '@/lib/api/tools';
import { confirmAsync } from '@/lib/dialogs';
import { Tool } from '@/types/tools';
import { ToolCard } from '@/components/tools/ToolCard';
import { ManageToolModal } from '@/components/tools/ManageToolModal';
import { showToast } from '@/context/ToastContext';

// Enable WebBrowser auth completion handling
WebBrowser.maybeCompleteAuthSession();

const PENDING_POLL_MS = 3500;

export default function ToolsConnectionsScreen() {
  const router = useRouter();

  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  // Apps with a connect/disconnect/status request in flight, by slug
  const [busySlugs, setBusySlugs] = useState<Record<string, boolean>>({});

  // Active tool for Manage modal
  const [selectedManageTool, setSelectedManageTool] = useState<Tool | null>(null);

  // Status checks in flight, by slug, so polling never stacks requests
  const checkingStatusRef = useRef<Record<string, boolean>>({});

  const setBusy = (slug: string, busy: boolean) =>
    setBusySlugs((prev) => ({ ...prev, [slug]: busy }));

  /** Replaces one app's entry in the list and in the open Manage modal. */
  const applyTool = useCallback((updated: Tool) => {
    setTools((prev) => prev.map((item) => (item.slug === updated.slug ? updated : item)));
    setSelectedManageTool((prev) => (prev?.slug === updated.slug ? updated : prev));
  }, []);

  // 1. Load the app catalog with the user's connection status
  const loadTools = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      setTools(await listTools());
    } catch (err) {
      console.error('[tools.tsx] Error loading tools:', err);
      showToast(getErrorMessage(err, 'Failed to load tools'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // First load; `loading` starts out true.
  useEffect(() => {
    let isCurrent = true;
    listTools()
      .then((catalog) => {
        if (isCurrent) setTools(catalog);
      })
      .catch((err) => {
        if (!isCurrent) return;
        console.error('[tools.tsx] Error loading tools:', err);
        showToast(getErrorMessage(err, 'Failed to load tools'));
      })
      .finally(() => {
        if (isCurrent) setLoading(false);
      });
    return () => {
      isCurrent = false;
    };
  }, []);

  // 2. Refresh when the user returns to the app, for example after authorizing
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextAppState: AppStateStatus) => {
      if (nextAppState === 'active') {
        loadTools(true);
      }
    });

    return () => {
      subscription.remove();
    };
  }, [loadTools]);

  // 3. Ask the backend for one app's current status (it checks Composio)
  const checkToolStatus = useCallback(
    async (tool: Tool, silent = false): Promise<Tool | undefined> => {
      if (checkingStatusRef.current[tool.slug]) return;
      checkingStatusRef.current[tool.slug] = true;

      try {
        const updated = await getToolConnection(tool.slug);

        if (!silent) {
          if (tool.status !== 'connected' && updated.status === 'connected') {
            showToast(`Successfully connected to ${updated.name}!`);
          } else if (updated.status === 'failed') {
            showToast(`Connection to ${updated.name} failed. Please try again.`);
          }
        }

        applyTool(updated);
        return updated;
      } catch (err) {
        console.warn(`[tools.tsx] Status check error for ${tool.slug}:`, err);
      } finally {
        checkingStatusRef.current[tool.slug] = false;
      }
    },
    [applyTool]
  );

  // 4. Poll pending connections until they resolve
  useEffect(() => {
    const pendingTools = tools.filter((t) => t.status === 'pending');
    if (pendingTools.length === 0) return;

    const intervalId = setInterval(() => {
      pendingTools.forEach((tool) => {
        checkToolStatus(tool);
      });
    }, PENDING_POLL_MS);

    return () => clearInterval(intervalId);
  }, [tools, checkToolStatus]);

  // 5. Connect: backend starts the Composio link -> browser -> status check
  const handleConnect = async (targetTool: Tool) => {
    setBusy(targetTool.slug, true);

    try {
      // Deep link back into the app after authorizing
      const callbackUrl = Linking.createURL('/tools');
      const { tool: started, connect_url } = await connectTool(targetTool.slug, callbackUrl);
      applyTool(started);

      if (!connect_url) {
        showToast(`${started.name} is already connected`);
        return;
      }

      showToast(`Opening authentication for ${started.name}...`);

      let browserResult: WebBrowser.WebBrowserAuthSessionResult | undefined;
      try {
        browserResult = await WebBrowser.openAuthSessionAsync(connect_url, callbackUrl);
      } catch (browserErr) {
        console.warn('[tools.tsx] openAuthSessionAsync fallback:', browserErr);
        await WebBrowser.openBrowserAsync(connect_url);
      }

      const updated = await checkToolStatus(started);
      if (
        (browserResult?.type === 'cancel' || browserResult?.type === 'dismiss') &&
        updated?.status === 'pending'
      ) {
        showToast('Authorization window closed. Connection pending...');
      }
    } catch (err) {
      console.error('[tools.tsx] Connect error:', err);
      showToast(getErrorMessage(err, `Failed to connect to ${targetTool.name}`));
    } finally {
      setBusy(targetTool.slug, false);
    }
  };

  // 6. Disconnect: removes every connected account of the app, after the user confirms
  const handleDisconnect = async (targetTool: Tool) => {
    const confirmed = await confirmAsync({
      title: `Disconnect ${targetTool.name}?`,
      message:
        `Your assistant won't be able to use ${targetTool.name}, and schedules that deliver ` +
        'there will fail, until you connect it again.',
      confirmText: 'Disconnect',
      destructive: true,
    });
    if (!confirmed) return;

    setBusy(targetTool.slug, true);

    try {
      applyTool(await disconnectTool(targetTool.slug));
      setSelectedManageTool((prev) => (prev?.slug === targetTool.slug ? null : prev));
      showToast(`Disconnected from ${targetTool.name}`);
    } catch (err) {
      console.error('[tools.tsx] Disconnect error:', err);
      showToast(getErrorMessage(err, `Failed to disconnect ${targetTool.name}`));
    } finally {
      setBusy(targetTool.slug, false);
    }
  };

  // 7. Reconnect: re-authorize from scratch (disconnect, then connect again)
  const handleReconnect = async (targetTool: Tool) => {
    setSelectedManageTool(null);
    setBusy(targetTool.slug, true);

    let revoked: Tool;
    try {
      revoked = await disconnectTool(targetTool.slug);
      applyTool(revoked);
    } catch (err) {
      console.error('[tools.tsx] Reconnect error:', err);
      showToast(getErrorMessage(err, `Failed to reconnect ${targetTool.name}`));
      setBusy(targetTool.slug, false);
      return;
    }

    await handleConnect(revoked);
  };

  // 8. Manage: opens the Manage modal
  const handleManage = (targetTool: Tool) => {
    setSelectedManageTool(targetTool);
  };

  return (
    // react-native-safe-area-context, not React Native's SafeAreaView: that one is iOS-only,
    // so on Android the status bar drew over this screen.
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right', 'bottom']}>
      <View style={styles.container}>
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity
            style={styles.backButton}
            onPress={() => router.back()}
            activeOpacity={0.7}
            hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
            <HugeiconsIcon
              icon={ArrowLeft01Icon}
              size={22}
              color={Colors.iconDark}
              strokeWidth={2}
            />
          </TouchableOpacity>

          <View style={styles.headerTitleContainer}>
            <Text style={styles.headerTitle}>Tools & Connections</Text>
          </View>

          <TouchableOpacity
            style={styles.refreshButton}
            onPress={() => loadTools(true)}
            activeOpacity={0.7}>
            <HugeiconsIcon icon={RefreshIcon} size={20} color={Colors.iconDark} strokeWidth={2} />
          </TouchableOpacity>
        </View>

        {/* Content Body */}
        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={Colors.primary} />
            <Text style={styles.loadingText}>Fetching tool connections...</Text>
          </View>
        ) : (
          <ScrollView
            style={styles.scrollView}
            contentContainerStyle={styles.scrollContent}
            showsVerticalScrollIndicator={false}
            refreshControl={
              <RefreshControl
                refreshing={refreshing}
                onRefresh={() => loadTools(true)}
                tintColor={Colors.primary}
              />
            }>
            {/* Flat List Container */}
            <View style={styles.listCard}>
              {tools.map((tool, index) => (
                <React.Fragment key={tool.slug}>
                  {index > 0 && <View style={styles.rowDivider} />}
                  <ToolCard
                    tool={tool}
                    isLoading={!!busySlugs[tool.slug]}
                    onConnect={handleConnect}
                    onDisconnect={handleDisconnect}
                    onManage={handleManage}
                  />
                </React.Fragment>
              ))}
            </View>

            <View style={{ height: 40 }} />
          </ScrollView>
        )}

        {/* Manage Tool Connection Modal */}
        <ManageToolModal
          visible={!!selectedManageTool}
          tool={selectedManageTool}
          isLoading={selectedManageTool ? !!busySlugs[selectedManageTool.slug] : false}
          onClose={() => setSelectedManageTool(null)}
          onReconnect={handleReconnect}
          onDisconnect={(toolToDisconnect) => {
            handleDisconnect(toolToDisconnect);
          }}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  container: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  backButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: Colors.surfaceMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitleContainer: {
    flex: 1,
    marginLeft: 12,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: Colors.text,
    letterSpacing: -0.4,
  },
  refreshButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: Colors.surfaceMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
  },
  loadingText: {
    fontSize: 14,
    color: Colors.textMuted,
    marginTop: 12,
    fontWeight: '500',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 16,
    paddingBottom: 32,
  },
  listCard: {
    backgroundColor: Colors.white,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: Colors.border,
    overflow: 'hidden',
  },
  rowDivider: {
    height: 1,
    backgroundColor: Colors.borderLight,
    marginLeft: 68,
  },
});
