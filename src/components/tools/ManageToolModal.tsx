/**
 * ManageToolModal Component ('src/components/tools/ManageToolModal.tsx')
 *
 * The sheet for managing a connected app, in inset-grouped sections:
 * - The app's glyph, name, connection status, and what it does
 * - The connected account (email or label) and since when, and Reconnect Account
 *   (re-authorize)
 * - For apps that can be memory sources (Google Calendar), whether its items become memories
 * - Disconnect Tool, on its own at the bottom
 */

import React, { useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { AppText, BottomSheet, ListRow, ListSection } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Tool, ToolConnectionStatus } from '@/types/tools';
import { MEMORY_SOURCE_APPS, MemorySourceToggle } from './MemorySourceToggle';
import { AppGlyph } from './ToolCard';

export interface ManageToolModalProps {
  visible: boolean;
  tool: Tool | null;
  isLoading?: boolean;
  onClose: () => void;
  onReconnect: (tool: Tool) => void;
  onDisconnect: (tool: Tool) => void;
}

const STATUS_LABEL: Record<ToolConnectionStatus, string> = {
  connected: 'Connected',
  pending: 'Pending',
  failed: 'Failed',
  revoked: 'Disconnected',
  not_connected: 'Not connected',
};

export const ManageToolModal: React.FC<ManageToolModalProps> = ({
  visible,
  tool,
  isLoading = false,
  onClose,
  onReconnect,
  onDisconnect,
}) => {
  // The sheet keeps showing the last app while it slides away after `tool` is cleared.
  const [lastTool, setLastTool] = useState<Tool | null>(tool);
  if (tool && tool !== lastTool) {
    setLastTool(tool);
  }
  const shown = tool ?? lastTool;
  if (!shown) return null;

  const isConnected = shown.status === 'connected';
  const busy = isLoading ? <ActivityIndicator size="small" color={Colors.secondaryLabel} /> : undefined;

  return (
    <BottomSheet
      visible={visible}
      onClose={onClose}
      rightAction={{ label: 'Done', onPress: onClose, disabled: isLoading }}
      scrollable>
      {/* Header */}
      <View style={styles.hero}>
        <AppGlyph tool={shown} size={60} />
        <AppText variant="title2" align="center" numberOfLines={2}>
          {shown.name}
        </AppText>
        <View style={styles.status}>
          <View
            style={[
              styles.statusDot,
              { backgroundColor: isConnected ? Colors.systemGreen : Colors.systemOrange },
            ]}
          />
          <AppText variant="subheadline" color="secondary">
            {STATUS_LABEL[shown.status]}
          </AppText>
        </View>
        {shown.description ? (
          <AppText variant="footnote" color="secondary" align="center" style={styles.description}>
            {shown.description}
          </AppText>
        ) : null}
      </View>

      {/* Account */}
      <ListSection header="Account">
        <ListRow
          title={shown.connected_email || shown.connected_label || 'Authorized User Account'}
          subtitle="Connected Account"
        />
        {shown.connected_at ? (
          <ListRow
            title="Connected since"
            value={new Date(shown.connected_at).toLocaleDateString()}
          />
        ) : null}
        <ListRow
          title="Reconnect Account"
          action
          onPress={isLoading ? undefined : () => onReconnect(shown)}
          accessory={busy}
        />
      </ListSection>

      {isConnected && MEMORY_SOURCE_APPS.includes(shown.slug) ? (
        <MemorySourceToggle app={shown.slug} />
      ) : null}

      <ListSection>
        <ListRow
          title="Disconnect Tool"
          action
          destructive
          onPress={isLoading ? undefined : () => onDisconnect(shown)}
          accessory={busy}
        />
      </ListSection>
    </BottomSheet>
  );
};

const styles = StyleSheet.create({
  hero: {
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 32,
    paddingTop: 4,
    paddingBottom: 24,
  },
  status: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  description: {
    marginTop: 4,
  },
});

export default ManageToolModal;
