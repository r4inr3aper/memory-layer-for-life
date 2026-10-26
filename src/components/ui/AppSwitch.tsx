/**
 * AppSwitch: the platform switch in iOS green, with a selection tick when it flips.
 */

import React from 'react';
import { Platform, Switch, type SwitchProps } from 'react-native';
import { Colors } from '@/constants/colors';
import { haptic } from '@/lib/haptics';

export function AppSwitch({ onValueChange, ...props }: SwitchProps) {
  return (
    <Switch
      {...props}
      trackColor={{ false: Colors.systemGray4, true: Colors.systemGreen }}
      thumbColor={Platform.OS === 'android' ? Colors.white : undefined}
      ios_backgroundColor={Colors.systemGray5}
      onValueChange={(value) => {
        haptic.selection();
        onValueChange?.(value);
      }}
    />
  );
}

export default AppSwitch;
