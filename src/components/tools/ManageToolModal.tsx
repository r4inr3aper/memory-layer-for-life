/**
 * ManageToolModal Component ('src/components/tools/ManageToolModal.tsx')
 *
 * Bottom sheet / modal dialog for managing an active tool connection:
 * - Shows connected account email / label
 * - Shows connection status badge
 * - Options to Reconnect (re-authorize) or Disconnect tool
 * - For apps that can be memory sources (Google Calendar), whether its items become memories
 */

import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  TouchableWithoutFeedback,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { Image } from 'expo-image';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  Cancel01Icon,
  Link02Icon,
  Logout01Icon,
  InformationCircleIcon,
  UserIcon,
} from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { Tool, ToolConnectionStatus } from '@/types/tools';
import { MEMORY_SOURCE_APPS, MemorySourceToggle } from './MemorySourceToggle';

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
  if (!tool) return null;

  const imageUrl = tool.logo_url;
  const isConnected = tool.status === 'connected';

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <TouchableWithoutFeedback onPress={onClose}>
        <View style={styles.overlay}>
          <TouchableWithoutFeedback>
            <View style={styles.card}>
              {/* Header */}
              <View style={styles.header}>
                <View style={styles.headerTitleRow}>
                  <View style={styles.logoWrapper}>
                    {imageUrl ? (
                      <Image
                        source={{ uri: imageUrl }}
                        style={styles.logoImage}
                        contentFit="contain"
                      />
                    ) : (
                      <Text style={styles.initialText}>{tool.name.charAt(0).toUpperCase()}</Text>
                    )}
                  </View>
                  <View style={styles.titleTextWrapper}>
                    <Text style={styles.toolTitle} numberOfLines={1}>
                      {tool.name}
                    </Text>
                    <View style={styles.statusPill}>
                      <View
                        style={[
                          styles.statusDot,
                          {
                            backgroundColor: isConnected ? Colors.success : Colors.warning,
                          },
                        ]}
                      />
                      <Text style={styles.statusPillText}>{STATUS_LABEL[tool.status]}</Text>
                    </View>
                  </View>
                </View>

                <TouchableOpacity
                  style={styles.closeBtn}
                  onPress={onClose}
                  disabled={isLoading}
                  activeOpacity={0.7}>
                  <HugeiconsIcon icon={Cancel01Icon} size={18} color={Colors.iconMuted} />
                </TouchableOpacity>
              </View>

              {/* Description */}
              {tool.description && <Text style={styles.descriptionText}>{tool.description}</Text>}

              {/* Account Details Box */}
              <View style={styles.detailsCard}>
                <View style={styles.detailRow}>
                  <HugeiconsIcon icon={UserIcon} size={18} color={Colors.primary} />
                  <View style={styles.detailContent}>
                    <Text style={styles.detailLabel}>Connected Account</Text>
                    <Text style={styles.detailValue} numberOfLines={1}>
                      {tool.connected_email || tool.connected_label || 'Authorized User Account'}
                    </Text>
                  </View>
                </View>

                {tool.connected_at && (
                  <View style={styles.detailRowDivider}>
                    <View style={styles.detailRow}>
                      <HugeiconsIcon
                        icon={InformationCircleIcon}
                        size={18}
                        color={Colors.textMuted}
                      />
                      <View style={styles.detailContent}>
                        <Text style={styles.detailLabel}>Connected since</Text>
                        <Text style={styles.detailValueSubtle} numberOfLines={1}>
                          {new Date(tool.connected_at).toLocaleDateString()}
                        </Text>
                      </View>
                    </View>
                  </View>
                )}
              </View>

              {isConnected && MEMORY_SOURCE_APPS.includes(tool.slug) ? (
                <MemorySourceToggle app={tool.slug} />
              ) : null}

              {/* Actions */}
              <View style={styles.actionSection}>
                {/* Reconnect Button */}
                <TouchableOpacity
                  style={styles.reconnectBtn}
                  onPress={() => onReconnect(tool)}
                  disabled={isLoading}
                  activeOpacity={0.8}>
                  {isLoading ? (
                    <ActivityIndicator size="small" color={Colors.primary} />
                  ) : (
                    <>
                      <HugeiconsIcon
                        icon={Link02Icon}
                        size={18}
                        color={Colors.primary}
                        strokeWidth={2}
                      />
                      <Text style={styles.reconnectBtnText}>Reconnect Account</Text>
                    </>
                  )}
                </TouchableOpacity>

                {/* Disconnect Button */}
                <TouchableOpacity
                  style={styles.disconnectBtn}
                  onPress={() => onDisconnect(tool)}
                  disabled={isLoading}
                  activeOpacity={0.8}>
                  {isLoading ? (
                    <ActivityIndicator size="small" color={Colors.error} />
                  ) : (
                    <>
                      <HugeiconsIcon
                        icon={Logout01Icon}
                        size={18}
                        color={Colors.error}
                        strokeWidth={2}
                      />
                      <Text style={styles.disconnectBtnText}>Disconnect Tool</Text>
                    </>
                  )}
                </TouchableOpacity>
              </View>
            </View>
          </TouchableWithoutFeedback>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: Colors.overlay,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  card: {
    width: '100%',
    maxWidth: 360,
    backgroundColor: Colors.white,
    borderRadius: 24,
    padding: 22,
    ...Platform.select({
      ios: {
        shadowColor: Colors.black,
        shadowOffset: { width: 0, height: 10 },
        shadowOpacity: 0.2,
        shadowRadius: 24,
      },
      android: {
        elevation: 10,
      },
      web: {
        boxShadow: '0 16px 36px rgba(0, 0, 0, 0.2)',
      },
    }),
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 14,
  },
  headerTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    marginRight: 10,
  },
  logoWrapper: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: Colors.surfaceMuted,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
    overflow: 'hidden',
  },
  logoImage: {
    width: 30,
    height: 30,
  },
  initialText: {
    fontSize: 18,
    fontWeight: '700',
    color: Colors.primary,
  },
  titleTextWrapper: {
    flex: 1,
  },
  toolTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: Colors.text,
    letterSpacing: -0.3,
    marginBottom: 3,
  },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    backgroundColor: Colors.successLight,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginRight: 5,
  },
  statusPillText: {
    fontSize: 11.5,
    fontWeight: '700',
    color: Colors.success,
    textTransform: 'capitalize',
  },
  closeBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: Colors.surfaceMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  descriptionText: {
    fontSize: 13.5,
    color: Colors.textSecondary,
    lineHeight: 19,
    marginBottom: 16,
  },
  detailsCard: {
    backgroundColor: Colors.surface,
    borderRadius: 16,
    padding: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    marginBottom: 20,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  detailRowDivider: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
  },
  detailContent: {
    marginLeft: 12,
    flex: 1,
  },
  detailLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: Colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  detailValue: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text,
  },
  detailValueSubtle: {
    fontSize: 12.5,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    color: Colors.textSecondary,
  },
  actionSection: {
    gap: 10,
  },
  reconnectBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    height: 44,
    borderRadius: 14,
    backgroundColor: Colors.primarySubtle,
    borderWidth: 1,
    borderColor: Colors.primaryBorder,
    gap: 8,
  },
  reconnectBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.primary,
  },
  disconnectBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    height: 44,
    borderRadius: 14,
    backgroundColor: Colors.errorLight,
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.25)',
    gap: 8,
  },
  disconnectBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.error,
  },
});

export default ManageToolModal;
