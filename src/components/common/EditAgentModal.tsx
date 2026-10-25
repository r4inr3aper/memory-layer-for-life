/**
 * EditAgentModal Component
 *
 * Minimalist agent personalization modal:
 * - Avatar preview
 * - Agent Name input
 * - Color accent selector
 * - Clean Save & Cancel actions
 *
 * Edits the saved agent profile (`AgentProfileContext`), which persists on the backend.
 */

import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TextInput,
  TouchableOpacity,
  TouchableWithoutFeedback,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { Cancel01Icon, CheckmarkCircle02Icon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { AGENT_ICONS } from '@/constants/agentIcons';
import { AGENT_NAME_MAX_LENGTH, useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage } from '@/lib/api/client';
import type { AgentProfile } from '@/types';
import { MascotAvatar } from './MascotAvatar';

export interface EditAgentModalProps {
  visible: boolean;
  onClose: () => void;
}

const THEME_COLORS = [
  Colors.primary,
  Colors.avatarAccentIndigo,
  Colors.avatarAccentEmerald,
  Colors.avatarAccentAmber,
  Colors.avatarAccentViolet,
  Colors.avatarAccentRose,
];

export const EditAgentModal: React.FC<EditAgentModalProps> = ({ visible, onClose }) => {
  const { profile, saveProfile } = useAgentProfile();
  const [name, setName] = useState(profile.name);
  const [selectedIcon, setSelectedIcon] = useState(profile.icon);
  const [selectedColor, setSelectedColor] = useState(profile.color);
  const [isSaving, setIsSaving] = useState(false);

  // Start from the saved profile every time the modal opens.
  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible) {
      setName(profile.name);
      setSelectedIcon(profile.icon);
      setSelectedColor(profile.color);
    }
  }

  const handleSave = async () => {
    if (isSaving) return;
    const trimmed = name.trim();
    if (!trimmed) {
      showToast('Give your agent a name.');
      return;
    }

    const changes: Partial<AgentProfile> = {};
    if (trimmed !== profile.name) changes.name = trimmed;
    if (selectedIcon !== profile.icon) changes.icon = selectedIcon;
    if (selectedColor !== profile.color) changes.color = selectedColor;
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }

    setIsSaving(true);
    try {
      await saveProfile(changes);
      showToast('Agent updated');
      onClose();
    } catch (error) {
      console.error('Failed to save the agent profile:', error);
      showToast(getErrorMessage(error, 'Could not save your changes'));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}>
      <TouchableWithoutFeedback onPress={onClose}>
        <View style={styles.overlay}>
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
            style={styles.keyboardContainer}>
            <TouchableWithoutFeedback>
              <View style={styles.card}>
                {/* Header with Close */}
                <View style={styles.header}>
                  <Text style={styles.title}>Edit Agent</Text>
                  <TouchableOpacity
                    style={styles.closeBtn}
                    onPress={onClose}
                    activeOpacity={0.7}
                    accessibilityRole="button"
                    accessibilityLabel="Close">
                    <HugeiconsIcon icon={Cancel01Icon} size={18} color={Colors.iconMuted} />
                  </TouchableOpacity>
                </View>

                {/* Avatar Preview */}
                <View style={styles.avatarSection}>
                  <MascotAvatar size={68} icon={selectedIcon} color={selectedColor} />
                </View>

                {/* Name Input */}
                <View style={styles.inputGroup}>
                  <Text style={styles.label}>Name</Text>
                  <TextInput
                    style={styles.input}
                    value={name}
                    onChangeText={setName}
                    placeholder="Agent name"
                    placeholderTextColor={Colors.iconMuted}
                    maxLength={AGENT_NAME_MAX_LENGTH}
                    returnKeyType="done"
                    onSubmitEditing={handleSave}
                  />
                </View>

                {/* Emoji Avatar Picker */}
                <View style={styles.avatarPickerGroup}>
                  <Text style={styles.label}>Avatar</Text>
                  <View style={styles.avatarGrid}>
                    {AGENT_ICONS.map((icon) => {
                      const isSelected = selectedIcon === icon.key;
                      return (
                        <TouchableOpacity
                          key={icon.key}
                          style={[
                            styles.avatarOption,
                            isSelected && styles.avatarOptionSelected,
                          ]}
                          onPress={() => setSelectedIcon(icon.key)}
                          activeOpacity={0.8}
                          accessibilityRole="button"
                          accessibilityLabel={`${icon.label} avatar`}
                          accessibilityState={{ selected: isSelected }}>
                          <MascotAvatar size={34} icon={icon.key} color={selectedColor} />
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                </View>

                {/* Theme Color Dots */}
                <View style={styles.colorGroup}>
                  <Text style={styles.label}>Theme</Text>
                  <View style={styles.colorRow}>
                    {THEME_COLORS.map((color) => {
                      const isSelected = selectedColor === color;
                      return (
                        <TouchableOpacity
                          key={color}
                          style={[
                            styles.colorDot,
                            { backgroundColor: color },
                            isSelected && styles.colorDotSelected,
                          ]}
                          onPress={() => setSelectedColor(color)}
                          activeOpacity={0.8}
                          accessibilityRole="button"
                          accessibilityState={{ selected: isSelected }}>
                          {isSelected && (
                            <HugeiconsIcon
                              icon={CheckmarkCircle02Icon}
                              size={14}
                              color={Colors.white}
                              strokeWidth={2.5}
                            />
                          )}
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                </View>

                {/* Actions */}
                <View style={styles.actionRow}>
                  <TouchableOpacity
                    style={styles.cancelBtn}
                    onPress={onClose}
                    activeOpacity={0.7}>
                    <Text style={styles.cancelText}>Cancel</Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    style={[
                      styles.saveBtn,
                      { backgroundColor: selectedColor },
                      isSaving && styles.saveBtnBusy,
                    ]}
                    onPress={handleSave}
                    disabled={isSaving}
                    activeOpacity={0.8}>
                    {isSaving ? (
                      <ActivityIndicator size="small" color={Colors.white} />
                    ) : (
                      <Text style={styles.saveText}>Save</Text>
                    )}
                  </TouchableOpacity>
                </View>
              </View>
            </TouchableWithoutFeedback>
          </KeyboardAvoidingView>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  keyboardContainer: {
    width: '100%',
    alignItems: 'center',
  },
  card: {
    width: '100%',
    maxWidth: 340,
    backgroundColor: Colors.white,
    borderRadius: 20,
    padding: 20,
    ...Platform.select({
      ios: {
        shadowColor: Colors.black,
        shadowOffset: { width: 0, height: 8 },
        shadowOpacity: 0.15,
        shadowRadius: 20,
      },
      android: {
        elevation: 8,
      },
      web: {
        boxShadow: '0 12px 32px rgba(0, 0, 0, 0.15)',
      },
    }),
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.2,
  },
  closeBtn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarSection: {
    alignItems: 'center',
    justifyContent: 'center',
    marginVertical: 10,
  },
  inputGroup: {
    marginTop: 12,
    marginBottom: 14,
  },
  label: {
    fontSize: 11,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: 6,
  },
  input: {
    backgroundColor: Colors.surfaceInput,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    fontWeight: '500',
    color: Colors.iconDark,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
  },
  avatarPickerGroup: {
    marginBottom: 14,
  },
  avatarGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  avatarOption: {
    width: 46,
    height: 46,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.avatarOptionBg,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  avatarOptionSelected: {
    backgroundColor: Colors.avatarOptionSelectedBg,
    borderColor: Colors.avatarOptionSelectedBorder,
    borderWidth: 1.5,
  },
  colorGroup: {
    marginBottom: 20,
  },
  colorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 4,
  },
  colorDot: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  colorDotSelected: {
    borderWidth: 2.5,
    borderColor: Colors.white,
    ...Platform.select({
      ios: {
        shadowColor: Colors.black,
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.25,
        shadowRadius: 3,
      },
      android: {
        elevation: 3,
      },
    }),
  },
  actionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  cancelBtn: {
    flex: 1,
    height: 42,
    borderRadius: 21,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  saveBtn: {
    flex: 1,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveBtnBusy: {
    opacity: 0.75,
  },
  saveText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.white,
  },
});

export default EditAgentModal;
