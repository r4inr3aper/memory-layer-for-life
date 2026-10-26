/**
 * Inset-grouped lists, as in iOS Settings: white cells in a rounded group on the grouped
 * background, separated by hairlines inset past the icon, with a header above and an
 * explanation below.
 *
 *   <ListSection header="Account" footer="Signed in with Google.">
 *     <ListRow icon={UserIcon} iconColor={Colors.systemBlue} title="Profile" onPress={...} />
 *     <ListRow title="Notifications" accessory={<AppSwitch ... />} />
 *   </ListSection>
 *
 * A pressable row highlights while touched, the way a cell does: instantly on touch down,
 * fading out after release. Rows do not scale; buttons do.
 */

import React, { Children, isValidElement, useState } from 'react';
import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import Animated from 'react-native-reanimated';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import { ArrowRight01Icon, Tick02Icon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { Hairline, Radius, ScreenMargin, continuous } from '@/constants/theme';
import { AppText } from './AppText';

const ROW_PADDING = 16;
const TILE_SIZE = 30;
const TILE_GAP = 14;

// --- Section -------------------------------------------------------------------------

export interface ListSectionProps {
  header?: string;
  /** A small action at the right of the header, such as "See all". */
  headerAction?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}

export function ListSection({ header, headerAction, footer, children, style }: ListSectionProps) {
  const rows = Children.toArray(children).filter(isValidElement);
  return (
    <View style={[styles.section, style]}>
      {header || headerAction ? (
        <View style={styles.headerRow}>
          {header ? (
            <AppText variant="footnote" color="secondary" style={styles.header}>
              {header.toUpperCase()}
            </AppText>
          ) : (
            <View />
          )}
          {headerAction}
        </View>
      ) : null}
      <View style={[styles.group, continuous]}>
        {rows.map((row, index) => (
          <React.Fragment key={row.key ?? index}>
            {index > 0 ? (
              <View style={styles.separatorTrack}>
                <View style={[styles.separator, { marginLeft: separatorInset(rows[index - 1]) }]} />
              </View>
            ) : null}
            {row}
          </React.Fragment>
        ))}
      </View>
      {footer ? (
        typeof footer === 'string' ? (
          <AppText variant="footnote" color="secondary" style={styles.footer}>
            {footer}
          </AppText>
        ) : (
          <View style={styles.footer}>{footer}</View>
        )
      ) : null}
    </View>
  );
}

/** Separators start where the row above starts its text, past its icon, as in iOS. */
function separatorInset(row: React.ReactElement): number {
  const props = row.props as Partial<ListRowProps>;
  return props.icon || props.leading ? ROW_PADDING + TILE_SIZE + TILE_GAP : ROW_PADDING;
}

// --- Icon tile -------------------------------------------------------------------------

export interface IconTileProps {
  icon: IconSvgElement;
  /** The tile's color; the glyph is white on it. */
  color?: string;
  size?: number;
}

/** A white glyph on a colored rounded square, as Settings marks each row. */
export function IconTile({ icon, color = Colors.systemBlue, size = TILE_SIZE }: IconTileProps) {
  return (
    <View
      style={[
        styles.tile,
        continuous,
        { width: size, height: size, borderRadius: Math.round(size * 0.24), backgroundColor: color },
      ]}>
      <HugeiconsIcon icon={icon} size={Math.round(size * 0.6)} color={Colors.white} strokeWidth={2} />
    </View>
  );
}

// --- Row -----------------------------------------------------------------------------

export interface ListRowProps {
  title: string;
  subtitle?: string;
  /** A value shown at the right in gray, such as the current setting. */
  value?: string;
  icon?: IconSvgElement;
  iconColor?: string;
  /** Anything to show in place of the icon tile (an avatar). */
  leading?: React.ReactNode;
  /** Shown at the right; a chevron by default when the row is pressable. */
  accessory?: React.ReactNode | 'chevron' | 'check' | 'none';
  onPress?: () => void;
  onLongPress?: () => void;
  destructive?: boolean;
  /** The title in the tint, centered, for a row that is a button ("Add link"). */
  action?: boolean;
  disabled?: boolean;
  numberOfLines?: number;
  /** The subtitle's color when it is a status (a failure in red); gray by default. */
  subtitleColor?: string;
  /** For a row in a list of choices: announced as selected. */
  selected?: boolean;
  /** For a row that shows and hides content: announced as expanded or collapsed. */
  expanded?: boolean;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  testID?: string;
}

export function ListRow({
  title,
  subtitle,
  value,
  icon,
  iconColor,
  leading,
  accessory,
  onPress,
  onLongPress,
  destructive = false,
  action = false,
  disabled = false,
  numberOfLines = 1,
  subtitleColor,
  selected,
  expanded,
  accessibilityLabel,
  accessibilityHint,
  testID,
}: ListRowProps) {
  const [pressed, setPressed] = useState(false);
  const pressable = Boolean(onPress || onLongPress) && !disabled;
  const resolvedAccessory = accessory ?? (onPress && !action ? 'chevron' : 'none');
  const titleColor = destructive ? Colors.systemRed : action ? Colors.tint : Colors.label;

  const content = (
    <Animated.View
      style={[
        styles.row,
        pressed ? styles.rowPressed : styles.rowIdle,
        disabled && styles.rowDisabled,
      ]}>
      {leading ?? (icon ? <IconTile icon={icon} color={iconColor} /> : null)}
      <View style={[styles.texts, action && styles.actionTexts]}>
        <AppText variant="body" numberOfLines={numberOfLines} style={{ color: titleColor }}>
          {title}
        </AppText>
        {subtitle ? (
          <AppText variant="footnote" color={subtitleColor ?? 'secondary'} numberOfLines={2}>
            {subtitle}
          </AppText>
        ) : null}
      </View>
      {value ? (
        <AppText variant="body" color="secondary" numberOfLines={1} style={styles.value}>
          {value}
        </AppText>
      ) : null}
      {resolvedAccessory === 'chevron' ? (
        <HugeiconsIcon icon={ArrowRight01Icon} size={18} color={Colors.tertiaryLabel} strokeWidth={2.2} />
      ) : resolvedAccessory === 'check' ? (
        <HugeiconsIcon icon={Tick02Icon} size={20} color={Colors.tint} strokeWidth={2.4} />
      ) : resolvedAccessory === 'none' ? null : (
        resolvedAccessory
      )}
    </Animated.View>
  );

  if (!pressable) {
    return (
      <View accessible={Boolean(accessibilityLabel)} accessibilityLabel={accessibilityLabel} testID={testID}>
        {content}
      </View>
    );
  }
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      onPressIn={() => setPressed(true)}
      onPressOut={() => setPressed(false)}
      unstable_pressDelay={40}
      pressRetentionOffset={16}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? title}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled, selected, expanded }}
      testID={testID}>
      {content}
    </Pressable>
  );
}


const styles = StyleSheet.create({
  section: {
    marginHorizontal: ScreenMargin,
    marginBottom: 28,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    paddingHorizontal: ROW_PADDING,
    marginBottom: 7,
  },
  header: {
    letterSpacing: 0.2,
  },
  group: {
    backgroundColor: Colors.secondaryGroupedBackground,
    borderRadius: Radius.md,
    overflow: 'hidden',
  },
  separatorTrack: {
    backgroundColor: Colors.secondaryGroupedBackground,
  },
  separator: {
    height: Hairline,
    backgroundColor: Colors.separator,
  },
  footer: {
    paddingHorizontal: ROW_PADDING,
    marginTop: 7,
  },
  tile: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  row: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: TILE_GAP,
    paddingHorizontal: ROW_PADDING,
    paddingVertical: 10,
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  // Highlight at once on touch down; fade out after release.
  rowPressed: {
    backgroundColor: Colors.cellPressed,
    transitionDuration: 0,
  },
  rowIdle: {
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionDuration: 350,
  },
  rowDisabled: {
    opacity: 0.4,
  },
  texts: {
    flex: 1,
    gap: 2,
  },
  actionTexts: {
    alignItems: 'center',
  },
  value: {
    maxWidth: '45%',
  },
});
