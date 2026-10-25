/**
 * ToolCard Component ('src/components/tools/ToolCard.tsx')
 *
 * List item row for tool connections:
 * - App logo from the backend catalog's logo_url, using expo-image
 * - Tool Name and connected status / account subtitle
 * - Connect / Pending / Connected / Manage / Disconnect buttons
 */

import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { Image } from 'expo-image';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { Settings02Icon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { Tool } from '@/types/tools';

export interface ToolCardProps {
  tool: Tool;
  isLoading?: boolean;
  onConnect?: (tool: Tool) => void;
  onDisconnect?: (tool: Tool) => void;
  onManage?: (tool: Tool) => void;
}

export const ToolCard: React.FC<ToolCardProps> = ({
  tool,
  isLoading = false,
  onConnect,
  onDisconnect,
  onManage,
}) => {
  const imageUrl = tool.logo_url;
  const isConnected = tool.status === 'connected';
  const isPending = tool.status === 'pending';
  const isFailed = tool.status === 'failed';

  // Subtitle resolution
  let subtitle = tool.description || null;
  if (isConnected) {
    subtitle = tool.connected_email || tool.connected_label || 'Connected';
  } else if (isPending) {
    subtitle = 'Authorization pending...';
  } else if (isFailed) {
    subtitle = 'Connection failed. Tap retry.';
  }

  return (
    <View style={styles.listRow}>
      {/* 1. Tool Logo Image from DB */}
      <View style={styles.logoWrapper}>
        {imageUrl ? (
          <Image
            source={{ uri: imageUrl }}
            style={styles.logoImage}
            contentFit="contain"
            transition={200}
          />
        ) : (
          <View style={styles.initialFallback}>
            <Text style={styles.initialText}>
              {tool.name ? tool.name.charAt(0).toUpperCase() : 'T'}
            </Text>
          </View>
        )}
      </View>

      {/* 2. Tool Name & Subtitle / Status */}
      <View style={styles.infoWrapper}>
        <View style={styles.nameRow}>
          <Text style={styles.toolName} numberOfLines={1}>
            {tool.name}
          </Text>
          {isConnected && <View style={styles.connectedDot} />}
          {isPending && <View style={styles.pendingDot} />}
        </View>

        {subtitle && (
          <Text
            style={[
              styles.subtitleText,
              isConnected && styles.connectedSubtitleText,
              isFailed && styles.failedSubtitleText,
              isPending && styles.pendingSubtitleText,
            ]}
            numberOfLines={1}>
            {subtitle}
          </Text>
        )}
      </View>

      {/* 3. Action Buttons Section */}
      <View style={styles.actionContainer}>
        {isLoading ? (
          <View style={styles.loadingWrapper}>
            <ActivityIndicator size="small" color={Colors.primary} />
          </View>
        ) : isConnected ? (
          <View style={styles.connectedActions}>
            {/* Manage Option */}
            {onManage && (
              <TouchableOpacity
                style={styles.manageButton}
                onPress={() => onManage(tool)}
                activeOpacity={0.7}>
                <HugeiconsIcon
                  icon={Settings02Icon}
                  size={16}
                  color={Colors.iconDark}
                  strokeWidth={2}
                />
              </TouchableOpacity>
            )}

            {/* Disconnect Option */}
            <TouchableOpacity
              style={styles.disconnectButton}
              onPress={() => onDisconnect?.(tool)}
              activeOpacity={0.7}>
              <Text style={styles.disconnectButtonText}>Disconnect</Text>
            </TouchableOpacity>
          </View>
        ) : isPending ? (
          <TouchableOpacity
            style={styles.pendingButton}
            onPress={() => onConnect?.(tool)}
            activeOpacity={0.7}>
            <ActivityIndicator
              size="small"
              color={Colors.warning}
              style={{ marginRight: 6 }}
            />
            <Text style={styles.pendingButtonText}>Pending...</Text>
          </TouchableOpacity>
        ) : isFailed ? (
          <TouchableOpacity
            style={styles.retryButton}
            onPress={() => onConnect?.(tool)}
            activeOpacity={0.7}>
            <Text style={styles.retryButtonText}>Retry</Text>
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={styles.connectButton}
            onPress={() => onConnect?.(tool)}
            activeOpacity={0.7}>
            <Text style={styles.connectButtonText}>Connect</Text>
          </TouchableOpacity>
        )}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  listRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: Colors.white,
  },
  logoWrapper: {
    width: 40,
    height: 40,
    borderRadius: 11,
    backgroundColor: Colors.surfaceMuted,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
    overflow: 'hidden',
  },
  logoImage: {
    width: 26,
    height: 26,
  },
  initialFallback: {
    width: '100%',
    height: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.primarySubtle,
  },
  initialText: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.primary,
  },
  infoWrapper: {
    flex: 1,
    marginRight: 10,
  },
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  toolName: {
    fontSize: 15.5,
    fontWeight: '600',
    color: Colors.iconDark,
    letterSpacing: -0.2,
  },
  connectedDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: Colors.success,
    marginLeft: 6,
  },
  pendingDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: Colors.warning,
    marginLeft: 6,
  },
  subtitleText: {
    fontSize: 12.5,
    color: Colors.textMuted,
    marginTop: 2,
  },
  connectedSubtitleText: {
    color: Colors.textSecondary,
    fontWeight: '500',
  },
  pendingSubtitleText: {
    color: Colors.warning,
    fontWeight: '500',
  },
  failedSubtitleText: {
    color: Colors.error,
    fontWeight: '500',
  },
  actionContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  loadingWrapper: {
    paddingHorizontal: 16,
    paddingVertical: 7,
  },
  connectedActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  manageButton: {
    width: 32,
    height: 32,
    borderRadius: 9,
    backgroundColor: Colors.surfaceMuted,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: Colors.border,
  },
  connectButton: {
    backgroundColor: Colors.primary,
    paddingHorizontal: 16,
    paddingVertical: 7,
    borderRadius: 10,
  },
  connectButtonText: {
    fontSize: 13.5,
    fontWeight: '700',
    color: Colors.white,
  },
  pendingButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.warningLight,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.3)',
  },
  pendingButtonText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.warning,
  },
  retryButton: {
    backgroundColor: Colors.primarySubtle,
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: Colors.primaryBorder,
  },
  retryButtonText: {
    fontSize: 13,
    fontWeight: '700',
    color: Colors.primary,
  },
  disconnectButton: {
    backgroundColor: Colors.errorLight,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.2)',
  },
  disconnectButtonText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.error,
  },
});
