/**
 * MemoryRow Component
 *
 * One memory in an inset-grouped list: a tile for its kind, its text, and a footnote with
 * the kind, when it was saved, and markers for what needs the user's attention (to review,
 * sensitive, written by the user). Tapping opens the memory. Lists that review memories
 * pass `onAccept` and `onRetract` for quick buttons.
 *
 * The memory screens' lists are virtualized, so ListSection cannot wrap their rows. The
 * parts here group them the same way: `InsetGroupHeader` above a group, `InsetCell` around
 * each row (rounded outer corners, hairlines inset past the tile), `CellPressable` for a
 * row that highlights while touched. `memoryKind` and `EntityAvatar` are the leading marks
 * for a memory's kind and for a person, place, or thing.
 */

import React, { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  View,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import Animated from 'react-native-reanimated';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import {
  Agreement01Icon,
  ArrowRight01Icon,
  Brain01Icon,
  BulbIcon,
  Building03Icon,
  Calendar03Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  CubeIcon,
  FavouriteIcon,
  Flag02Icon,
  Folder01Icon,
  GitBranchIcon,
  InformationCircleIcon,
  Leaf01Icon,
  Link01Icon,
  Location01Icon,
  LockIcon,
  Money03Icon,
  Note01Icon,
  RepeatIcon,
  Route01Icon,
  Tag01Icon,
  Target02Icon,
  Tick02Icon,
} from '@hugeicons/core-free-icons';
import { AppText, type TextTone } from '@/components/ui/AppText';
import { IconButton } from '@/components/ui/IconButton';
import { IconTile } from '@/components/ui/List';
import { Colors } from '@/constants/colors';
import { Hairline, Radius, ScreenMargin, continuous } from '@/constants/theme';
import type { MemoryItem, MemoryStatus } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';
import { memoryStatusLabel, memoryTypeLabel } from '@/lib/memories';

// The metrics of ListRow, so these rows line up with every other list in the app.
const ROW_PADDING = 16;
const TILE_SIZE = 30;
const TILE_GAP = 14;

/** Where the hairline between rows starts when the rows lead with a tile or an avatar. */
export const LEADING_INSET = ROW_PADDING + TILE_SIZE + TILE_GAP;

// --- Leading marks -----------------------------------------------------------------------

interface Mark {
  icon: IconSvgElement;
  color: string;
}

const MEMORY_KINDS: Record<string, Mark> = {
  semantic_fact: { icon: InformationCircleIcon, color: Colors.systemBlue },
  episodic_event: { icon: Calendar03Icon, color: Colors.systemRed },
  preference: { icon: FavouriteIcon, color: Colors.systemPink },
  intention: { icon: Flag02Icon, color: Colors.systemIndigo },
  task: { icon: CheckmarkCircle02Icon, color: Colors.systemBlue },
  commitment: { icon: Agreement01Icon, color: Colors.systemIndigo },
  goal: { icon: Target02Icon, color: Colors.systemGreen },
  project: { icon: Folder01Icon, color: Colors.systemTeal },
  decision: { icon: GitBranchIcon, color: Colors.systemPurple },
  idea: { icon: BulbIcon, color: Colors.systemOrange },
  open_loop: { icon: RepeatIcon, color: Colors.systemOrange },
  plan: { icon: Route01Icon, color: Colors.systemTeal },
  note: { icon: Note01Icon, color: Colors.systemGray },
  reflection: { icon: Leaf01Icon, color: Colors.systemPurple },
  resource: { icon: Link01Icon, color: Colors.systemTeal },
  financial_note: { icon: Money03Icon, color: Colors.systemGreen },
};

const OTHER_KIND: Mark = { icon: Brain01Icon, color: Colors.systemGray };

/** The glyph and color that mark a kind of memory ("semantic_fact", "preference"). */
export function memoryKind(memoryType: string): Mark {
  return MEMORY_KINDS[memoryType] ?? OTHER_KIND;
}

const ENTITY_KINDS: Record<string, Mark> = {
  organization: { icon: Building03Icon, color: Colors.systemIndigo },
  project: { icon: Folder01Icon, color: Colors.systemTeal },
  concept: { icon: BulbIcon, color: Colors.systemOrange },
  place: { icon: Location01Icon, color: Colors.systemRed },
  event: { icon: Calendar03Icon, color: Colors.systemPink },
  technology: { icon: CubeIcon, color: Colors.systemGray },
  topic: { icon: Tag01Icon, color: Colors.systemPurple },
};

/** A person's monogram, as Contacts shows it; a tile for a place, a project, or a thing. */
export function EntityAvatar({ type, name }: { type: string; name: string }) {
  const mark = type === 'person' ? null : (ENTITY_KINDS[type] ?? { icon: Tag01Icon, color: Colors.systemGray });
  if (mark) {
    return <IconTile icon={mark.icon} color={mark.color} />;
  }
  return (
    <View style={styles.monogram}>
      <AppText variant="subheadline" weight="600" color="inverse">
        {name.charAt(0).toUpperCase()}
      </AppText>
    </View>
  );
}

// --- Grouping ----------------------------------------------------------------------------

/** The uppercase footnote above a group, with an optional action at its right. */
export function InsetGroupHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <View style={[styles.groupHeader, action ? styles.groupHeaderWithAction : null]}>
      <AppText variant="footnote" color="secondary" style={styles.groupHeaderText} numberOfLines={1}>
        {title.toUpperCase()}
      </AppText>
      {action}
    </View>
  );
}

export interface InsetCellProps {
  first: boolean;
  last: boolean;
  /** Where the hairline above the row starts; `LEADING_INSET` for rows with a tile. */
  inset?: number;
  children: React.ReactNode;
}

/** One row of an inset group in a virtualized list (see the top of this file). */
export function InsetCell({ first, last, inset = ROW_PADDING, children }: InsetCellProps) {
  return (
    <View style={[styles.cell, continuous, first && styles.cellFirst, last && styles.cellLast]}>
      {first ? null : (
        <View style={styles.separatorTrack}>
          <View style={[styles.separator, { marginLeft: inset }]} />
        </View>
      )}
      {children}
    </View>
  );
}

export interface CellPressableProps extends Omit<PressableProps, 'style' | 'children'> {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}

/**
 * A cell that highlights the moment a finger lands and fades after it lifts, as ListRow
 * does (cells highlight; they do not scale).
 */
export function CellPressable({ children, style, onPressIn, onPressOut, ...props }: CellPressableProps) {
  const [pressed, setPressed] = useState(false);
  return (
    <Pressable
      unstable_pressDelay={40}
      pressRetentionOffset={16}
      accessibilityRole="button"
      {...props}
      onPressIn={(event) => {
        setPressed(true);
        onPressIn?.(event);
      }}
      onPressOut={(event) => {
        setPressed(false);
        onPressOut?.(event);
      }}>
      <Animated.View style={[styles.highlight, pressed ? styles.pressed : styles.idle, style]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}

// --- Memory row --------------------------------------------------------------------------

const STATUS_TONES: Record<MemoryStatus, TextTone> = {
  proposed: 'tint',
  active: 'success',
  superseded: 'secondary',
  retracted: 'destructive',
};

export interface MemoryRowProps {
  memory: MemoryItem;
  onPress: () => void;
  onAccept?: () => void;
  onRetract?: () => void;
  /** A quick action is being saved. */
  busy?: boolean;
}

export const MemoryRow: React.FC<MemoryRowProps> = ({
  memory,
  onPress,
  onAccept,
  onRetract,
  busy = false,
}) => {
  // The whole cell highlights, the quick buttons' strip included, while the text is held.
  const [pressed, setPressed] = useState(false);
  const kind = memoryKind(memory.memory_type);
  const meta = [memoryTypeLabel(memory.memory_type), formatRelativeTime(memory.created_at)];
  if (memory.created_by === 'user') meta.push('Written by you');
  const hasQuickActions = Boolean(onAccept || onRetract);

  return (
    <Animated.View style={[styles.highlight, styles.row, pressed ? styles.pressed : styles.idle]}>
      <Pressable
        style={[styles.body, hasQuickActions && styles.bodyWithActions]}
        onPress={onPress}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        unstable_pressDelay={40}
        pressRetentionOffset={16}
        accessibilityRole="button"
        accessibilityHint="Opens the memory">
        <View style={styles.tile}>
          <IconTile icon={kind.icon} color={kind.color} />
        </View>
        <View style={styles.texts}>
          <AppText variant="body" numberOfLines={3}>
            {memory.content}
          </AppText>
          <View style={styles.metaRow}>
            {memory.sensitive ? (
              <HugeiconsIcon
                icon={LockIcon}
                size={12}
                color={Colors.secondaryLabel}
                strokeWidth={2}
                accessibilityLabel="Sensitive"
              />
            ) : null}
            <AppText variant="footnote" color="secondary">
              {meta.join(' · ')}
            </AppText>
            {memory.status !== 'active' ? (
              <AppText variant="footnote" weight="600" color={STATUS_TONES[memory.status]}>
                {memoryStatusLabel(memory.status)}
              </AppText>
            ) : null}
          </View>
        </View>
        {hasQuickActions ? null : (
          <HugeiconsIcon
            icon={ArrowRight01Icon}
            size={18}
            color={Colors.tertiaryLabel}
            strokeWidth={2.2}
            style={styles.chevron}
          />
        )}
      </Pressable>

      {hasQuickActions ? (
        <View style={styles.actions}>
          {busy ? (
            <ActivityIndicator size="small" color={Colors.systemGray} />
          ) : (
            <>
              {onRetract ? (
                <IconButton
                  icon={Cancel01Icon}
                  variant="plain"
                  size={32}
                  iconSize={16}
                  color={Colors.systemRed}
                  style={styles.quickRetract}
                  haptic="light"
                  onPress={onRetract}
                  accessibilityLabel="Mark as wrong"
                />
              ) : null}
              {onAccept ? (
                <IconButton
                  icon={Tick02Icon}
                  variant="plain"
                  size={32}
                  iconSize={16}
                  color={Colors.systemGreen}
                  style={styles.quickAccept}
                  haptic="success"
                  onPress={onAccept}
                  accessibilityLabel="Accept"
                />
              ) : null}
            </>
          )}
        </View>
      ) : null}
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  // Grouping
  groupHeader: {
    marginHorizontal: ScreenMargin,
    paddingHorizontal: ROW_PADDING,
    marginBottom: 7,
  },
  groupHeaderWithAction: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    marginBottom: 2,
    paddingRight: ROW_PADDING - 4,
  },
  groupHeaderText: {
    flexShrink: 1,
    letterSpacing: 0.2,
  },
  cell: {
    marginHorizontal: ScreenMargin,
    backgroundColor: Colors.secondaryGroupedBackground,
    overflow: 'hidden',
  },
  cellFirst: {
    borderTopLeftRadius: Radius.md,
    borderTopRightRadius: Radius.md,
  },
  cellLast: {
    borderBottomLeftRadius: Radius.md,
    borderBottomRightRadius: Radius.md,
    marginBottom: 28,
  },
  separatorTrack: {
    backgroundColor: Colors.secondaryGroupedBackground,
  },
  separator: {
    height: Hairline,
    backgroundColor: Colors.separator,
  },
  // Highlight at once on touch down; fade out after release (ListRow's timing).
  highlight: {
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  pressed: {
    backgroundColor: Colors.cellPressed,
    transitionDuration: 0,
  },
  idle: {
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionDuration: 350,
  },
  // Marks
  monogram: {
    width: TILE_SIZE,
    height: TILE_SIZE,
    borderRadius: TILE_SIZE / 2,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.systemGray,
  },
  // Memory row
  row: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  body: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: TILE_GAP,
    paddingLeft: ROW_PADDING,
    paddingRight: ROW_PADDING,
    paddingVertical: 11,
  },
  bodyWithActions: {
    paddingRight: 8,
  },
  tile: {
    marginTop: 1,
  },
  texts: {
    flex: 1,
    gap: 3,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    columnGap: 6,
  },
  chevron: {
    alignSelf: 'center',
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 10,
    minWidth: 40,
    paddingRight: ROW_PADDING,
  },
  quickAccept: {
    backgroundColor: Colors.successLight,
  },
  quickRetract: {
    backgroundColor: Colors.errorLight,
  },
});

export default MemoryRow;
