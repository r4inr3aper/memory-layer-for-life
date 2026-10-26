/**
 * ScreenHeader Component
 *
 * The navigation bar of screens pushed over the tabs: a round back button, the title in
 * the middle, and an optional action at the right, as in iOS.
 *
 * With a large title, the screen shows the title big at the top of its content
 * (`LargeTitle`) and passes its scroll position (`useScrollY`); the bar's small title and
 * its hairline appear only once the large one has scrolled under the bar.
 *
 *   const { scrollY, onScroll } = useScrollY();
 *   <ScreenHeader title="Files & links" scrollY={scrollY} />
 *   <Animated.ScrollView onScroll={onScroll} scrollEventThrottle={16}>
 *     <LargeTitle title="Files & links" />
 */

import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useRouter, type Href } from 'expo-router';
import Animated, {
  Extrapolation,
  interpolate,
  useAnimatedScrollHandler,
  useAnimatedStyle,
  useSharedValue,
  type SharedValue,
} from 'react-native-reanimated';
import { ArrowLeft01Icon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { Hairline, ScreenMargin, Typography } from '@/constants/theme';
import { AppText } from '@/components/ui/AppText';
import { IconButton } from '@/components/ui/IconButton';

export interface ScreenHeaderProps {
  title: string;
  /** Where Back goes when there is no screen to go back to. */
  fallbackHref?: Href;
  /** An action shown at the right end, such as an add button. */
  right?: React.ReactNode;
  /** The content's scroll position, when the screen shows a `LargeTitle`. */
  scrollY?: SharedValue<number>;
  /** The bar's background: the grouped gray of list screens, or plain white. */
  background?: 'grouped' | 'plain';
}

// How far the content scrolls before the large title is under the bar.
const LARGE_TITLE_SCROLL = 44;

export const ScreenHeader: React.FC<ScreenHeaderProps> = ({
  title,
  fallbackHref = '/(tabs)/settings',
  right,
  scrollY,
  background = 'grouped',
}) => {
  const router = useRouter();

  const goBack = () => {
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace(fallbackHref);
    }
  };

  const titleStyle = useAnimatedStyle(() => {
    if (!scrollY) return { opacity: 1 };
    return {
      opacity: interpolate(
        scrollY.get(),
        [LARGE_TITLE_SCROLL - 12, LARGE_TITLE_SCROLL],
        [0, 1],
        Extrapolation.CLAMP
      ),
    };
  });
  const edgeStyle = useAnimatedStyle(() => {
    if (!scrollY) return { opacity: 0 };
    return {
      opacity: interpolate(
        scrollY.get(),
        [LARGE_TITLE_SCROLL - 4, LARGE_TITLE_SCROLL + 8],
        [0, 1],
        Extrapolation.CLAMP
      ),
    };
  });

  const backgroundColor = background === 'grouped' ? Colors.groupedBackground : Colors.systemBackground;

  return (
    <View style={[styles.header, { backgroundColor }]}>
      <View style={styles.side}>
        <IconButton icon={ArrowLeft01Icon} onPress={goBack} accessibilityLabel="Go back" />
      </View>
      <Animated.View style={[styles.titleWrap, titleStyle]} pointerEvents="none">
        <AppText style={Typography.headline} numberOfLines={1}>
          {title}
        </AppText>
      </Animated.View>
      <View style={[styles.side, styles.sideRight]}>{right}</View>
      <Animated.View style={[styles.edge, edgeStyle]} pointerEvents="none" />
    </View>
  );
};

export interface LargeTitleProps {
  title: string;
  subtitle?: string;
}

/** The large title at the top of a screen's content (see ScreenHeader). */
export function LargeTitle({ title, subtitle }: LargeTitleProps) {
  return (
    <View style={styles.largeTitle}>
      <AppText variant="largeTitle" numberOfLines={2}>
        {title}
      </AppText>
      {subtitle ? (
        <AppText variant="subheadline" color="secondary" style={styles.largeSubtitle}>
          {subtitle}
        </AppText>
      ) : null}
    </View>
  );
}

/** The scroll position of a screen's content, for its ScreenHeader. Pass `onScroll` to
 * an Animated.ScrollView or Animated.FlatList with `scrollEventThrottle={16}`. */
export function useScrollY() {
  const scrollY = useSharedValue(0);
  const onScroll = useAnimatedScrollHandler((event) => {
    scrollY.set(event.contentOffset.y);
  });
  return { scrollY, onScroll };
}

const styles = StyleSheet.create({
  header: {
    height: 52,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: ScreenMargin,
    zIndex: 10,
  },
  side: {
    minWidth: 44,
    flexDirection: 'row',
    alignItems: 'center',
    zIndex: 1,
  },
  sideRight: {
    marginLeft: 'auto',
    justifyContent: 'flex-end',
    gap: 8,
  },
  titleWrap: {
    position: 'absolute',
    left: 72,
    right: 72,
    alignItems: 'center',
  },
  edge: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    height: Hairline,
    backgroundColor: Colors.separator,
  },
  largeTitle: {
    paddingHorizontal: ScreenMargin + 4,
    paddingTop: 2,
    paddingBottom: 14,
  },
  largeSubtitle: {
    marginTop: 4,
  },
});

export default ScreenHeader;
