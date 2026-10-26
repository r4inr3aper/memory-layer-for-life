/**
 * ToolCard Component ('src/components/tools/ToolCard.tsx')
 *
 * One app in the Tools & Connections list, as an inset-grouped row:
 * - The app's glyph: its logo from the backend catalog's logo_url (expo-image), on a
 *   rounded tile, or its initial when there is no logo
 * - Its name, and below it "Connected" with the account, the pending or failed state, or
 *   what the app does
 * - At the right: a small tinted Connect (or Retry) button, or, once connected, a chevron:
 *   the row opens the Manage sheet
 */

import React from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { Image } from 'expo-image';
import { AppText, Button, ListRow } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { continuous } from '@/constants/theme';
import { Tool } from '@/types/tools';

export interface ToolCardProps {
  tool: Tool;
  isLoading?: boolean;
  onConnect?: (tool: Tool) => void;
  onDisconnect?: (tool: Tool) => void;
  onManage?: (tool: Tool) => void;
  /**
   * The row's glyph; the app's `AppGlyph` by default. A list passes it in when it needs
   * to see the glyph (ListSection insets its separators past a row's `leading`).
   */
  leading?: React.ReactNode;
}

/** The app's logo on a rounded tile, the size of a list row's icon tile by default. */
export function AppGlyph({ tool, size = 30 }: { tool: Tool; size?: number }) {
  const logoSize = Math.round(size * 0.68);
  return (
    <View
      style={[
        styles.glyph,
        continuous,
        { width: size, height: size, borderRadius: Math.round(size * 0.24) },
      ]}>
      {tool.logo_url ? (
        <Image
          source={{ uri: tool.logo_url }}
          style={{ width: logoSize, height: logoSize }}
          contentFit="contain"
          transition={200}
        />
      ) : (
        <View style={styles.initialFallback}>
          <AppText variant={size >= 44 ? 'title2' : 'headline'} color="tint">
            {tool.name ? tool.name.charAt(0).toUpperCase() : 'T'}
          </AppText>
        </View>
      )}
    </View>
  );
}

export const ToolCard: React.FC<ToolCardProps> = ({
  tool,
  isLoading = false,
  onConnect,
  onDisconnect,
  onManage,
  leading,
}) => {
  const isConnected = tool.status === 'connected';
  const isPending = tool.status === 'pending';
  const isFailed = tool.status === 'failed';
  const account = tool.connected_email || tool.connected_label;

  // Subtitle resolution
  let subtitle = tool.description || undefined;
  if (isConnected) {
    subtitle = account ? `Connected · ${account}` : 'Connected';
  } else if (isPending) {
    subtitle = 'Authorization pending...';
  } else if (isFailed) {
    subtitle = 'Connection failed. Tap retry.';
  }

  const canManage = isConnected && Boolean(onManage);

  let accessory: React.ReactNode;
  if (isLoading) {
    accessory = <ActivityIndicator size="small" color={Colors.secondaryLabel} />;
  } else if (isConnected) {
    // With a Manage sheet, the row opens it (a chevron); without one, disconnect here.
    accessory = canManage ? undefined : (
      <Button
        title="Disconnect"
        variant="destructive"
        size="small"
        onPress={() => onDisconnect?.(tool)}
      />
    );
  } else if (isPending) {
    accessory = (
      <Button title="Pending..." variant="gray" size="small" onPress={() => onConnect?.(tool)} />
    );
  } else if (isFailed) {
    accessory = (
      <Button title="Retry" variant="tinted" size="small" onPress={() => onConnect?.(tool)} />
    );
  } else {
    accessory = (
      <Button title="Connect" variant="tinted" size="small" onPress={() => onConnect?.(tool)} />
    );
  }

  return (
    <ListRow
      title={tool.name}
      subtitle={subtitle}
      leading={leading ?? <AppGlyph tool={tool} />}
      accessory={accessory}
      onPress={canManage ? () => onManage?.(tool) : undefined}
    />
  );
};

const styles = StyleSheet.create({
  glyph: {
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    backgroundColor: Colors.tertiaryFill,
  },
  initialFallback: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.tintFill,
  },
});
