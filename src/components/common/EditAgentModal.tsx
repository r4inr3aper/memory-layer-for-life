/**
 * EditAgentModal Component
 *
 * A sheet to personalize the agent, as iOS edits a contact: the avatar large at the top,
 * then the name, the avatar choices, and the accent color, with Cancel and Save in the
 * sheet's title bar.
 *
 * Edits the saved agent profile (`AgentProfileContext`), which persists on the backend.
 */

import React, { useState } from 'react';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { Tick02Icon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { Radius, ScreenMargin, Typography, continuous } from '@/constants/theme';
import { AGENT_ICONS } from '@/constants/agentIcons';
import { AGENT_NAME_MAX_LENGTH, useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage } from '@/lib/api/client';
import { haptic } from '@/lib/haptics';
import type { AgentProfile } from '@/types';
import { AppText } from '@/components/ui/AppText';
import { BottomSheet } from '@/components/ui/BottomSheet';
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
      haptic.success();
      showToast('Agent updated');
      onClose();
    } catch (error) {
      console.error('Failed to save the agent profile:', error);
      haptic.error();
      showToast(getErrorMessage(error, 'Could not save your changes'));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <BottomSheet
      visible={visible}
      onClose={onClose}
      dismissible={!isSaving}
      title="Edit Agent"
      leftAction={{ label: 'Cancel', onPress: onClose }}
      rightAction={{
        label: 'Save',
        onPress: () => void handleSave(),
        disabled: !name.trim(),
        loading: isSaving,
      }}
      scrollable>
      <View style={styles.avatarSection}>
        <MascotAvatar size={88} icon={selectedIcon} color={selectedColor} />
      </View>

      {/* Name */}
      <View style={[styles.group, continuous]}>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="Agent name"
          placeholderTextColor={Colors.placeholder}
          maxLength={AGENT_NAME_MAX_LENGTH}
          returnKeyType="done"
          onSubmitEditing={() => void handleSave()}
          accessibilityLabel="Agent name"
        />
      </View>

      {/* Avatar */}
      <AppText variant="footnote" color="secondary" style={styles.sectionHeader}>
        AVATAR
      </AppText>
      <View style={[styles.group, styles.grid, continuous]}>
        {AGENT_ICONS.map((icon) => {
          const isSelected = selectedIcon === icon.key;
          return (
            <Pressable
              key={icon.key}
              style={[styles.avatarOption, continuous, isSelected && styles.avatarOptionSelected]}
              onPress={() => {
                if (isSelected) return;
                haptic.selection();
                setSelectedIcon(icon.key);
              }}
              hitSlop={4}
              accessibilityRole="button"
              accessibilityLabel={`${icon.label} avatar`}
              accessibilityState={{ selected: isSelected }}>
              <MascotAvatar size={38} icon={icon.key} color={selectedColor} />
            </Pressable>
          );
        })}
      </View>

      {/* Color */}
      <AppText variant="footnote" color="secondary" style={styles.sectionHeader}>
        COLOR
      </AppText>
      <View style={[styles.group, styles.colorRow, continuous]}>
        {THEME_COLORS.map((color) => {
          const isSelected = selectedColor === color;
          return (
            <Pressable
              key={color}
              style={[styles.colorRing, isSelected && { borderColor: color }]}
              onPress={() => {
                if (isSelected) return;
                haptic.selection();
                setSelectedColor(color);
              }}
              hitSlop={6}
              accessibilityRole="button"
              accessibilityLabel="Accent color"
              accessibilityState={{ selected: isSelected }}>
              <View style={[styles.colorDot, { backgroundColor: color }]}>
                {isSelected ? (
                  <HugeiconsIcon icon={Tick02Icon} size={16} color={Colors.white} strokeWidth={2.8} />
                ) : null}
              </View>
            </Pressable>
          );
        })}
      </View>
    </BottomSheet>
  );
};

const styles = StyleSheet.create({
  avatarSection: {
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
    marginBottom: 20,
  },
  group: {
    marginHorizontal: ScreenMargin,
    borderRadius: Radius.md,
    backgroundColor: Colors.secondaryGroupedBackground,
    overflow: 'hidden',
  },
  input: {
    ...Typography.body,
    minHeight: 48,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: Colors.label,
  },
  sectionHeader: {
    marginHorizontal: ScreenMargin + 16,
    marginTop: 24,
    marginBottom: 7,
    letterSpacing: 0.2,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    padding: 12,
  },
  avatarOption: {
    width: 52,
    height: 52,
    borderRadius: Radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.groupedBackground,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  avatarOptionSelected: {
    backgroundColor: Colors.tintFill,
    borderColor: Colors.tint,
  },
  colorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 12,
  },
  colorRing: {
    width: 42,
    height: 42,
    borderRadius: 21,
    borderWidth: 2.5,
    borderColor: 'transparent',
    alignItems: 'center',
    justifyContent: 'center',
  },
  colorDot: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

export default EditAgentModal;
