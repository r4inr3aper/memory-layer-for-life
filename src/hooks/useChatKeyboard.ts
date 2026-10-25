/**
 * Chat Keyboard
 *
 * Keeps a chat's input on top of the keyboard, moving with the keyboard's own animation
 * frame by frame, as messaging apps do, and keeps the newest message in view.
 *
 * - `lift` is how far the keyboard reaches above the bottom of the chat area. The tab bar
 *   and the system navigation bar sit between the two; the keyboard covers them.
 * - The input bar moves up by `lift` with a transform: no layout and no JavaScript per frame.
 * - The message list gets a spacer of the same height after its last message, so every
 *   message can still be scrolled above the input. If the list showed its newest message
 *   when the keyboard started to open, it scrolls along so that message stays just above
 *   the input. A list the user had scrolled up stays put, and the input slides over it.
 *
 * Positions are compared in one coordinate system: the root view's, which covers the whole
 * screen because apps are drawn edge-to-edge (so Android no longer resizes the window for
 * the keyboard). The chat area is measured from the layout tree with Reanimated's
 * `measure`. Not with `measureInWindow`: on Android that counts from below the status bar,
 * which once left the input half under the keyboard.
 *
 * Where the keyboard is:
 * - Reanimated's keyboard height, frame by frame on the UI thread. It is read with the
 *   navigation bar included (`isNavigationBarTranslucentAndroid`), so it is the distance
 *   from the bottom of the window to the top of the keyboard. Both translucent flags must
 *   be set: otherwise Reanimated adds system-bar margins to the app's root view.
 * - On Android, React Native's keyboard events as a fallback: a host app (Expo Go among
 *   them) can take over the window's inset callbacks Reanimated listens to, leaving it at
 *   0. Until Reanimated has reported a keyboard once, the input is moved to React Native's
 *   reported keyboard top with a short animation instead.
 *
 * `useAnimatedKeyboard` is deprecated in favour of react-native-keyboard-controller, which
 * Expo Go does not include. Move to its `KeyboardStickyView` once the app runs as a
 * development build.
 */

import { useEffect } from 'react';
import { Keyboard, Platform, type KeyboardEvent, type LayoutChangeEvent } from 'react-native';
import Animated, {
  Easing,
  measure,
  scrollTo,
  useAnimatedKeyboard,
  useAnimatedReaction,
  useAnimatedRef,
  useAnimatedStyle,
  useDerivedValue,
  useScrollOffset,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaFrame } from 'react-native-safe-area-context';

/** How close to its end, in points, the list counts as showing the newest message. */
const AT_END_THRESHOLD = 48;

const KEYBOARD_OPTIONS = {
  isStatusBarTranslucentAndroid: true,
  isNavigationBarTranslucentAndroid: true,
};

/** Close to the system keyboard animation, for the fallback. */
const FALLBACK_ANIMATION = { duration: 250, easing: Easing.out(Easing.cubic) };

export function useChatKeyboard() {
  const scrollRef = useAnimatedRef<Animated.ScrollView>();
  const areaRef = useAnimatedRef<Animated.View>();
  const keyboard = useAnimatedKeyboard(KEYBOARD_OPTIONS);
  const { height: windowHeight } = useSafeAreaFrame();

  // The root view's height: the whole screen, as the app is drawn edge-to-edge.
  const rootHeight = useSharedValue(windowHeight);
  // The keyboard's reach from the bottom of the window, from React Native's events, and
  // whether Reanimated has ever reported a keyboard (then the fallback is never used).
  const fallbackHeight = useSharedValue(0);
  const reanimatedReports = useSharedValue(false);
  const viewportHeight = useSharedValue(0);
  const contentHeight = useSharedValue(0);
  const scrollOffset = useScrollOffset(scrollRef);
  // Whether the list scrolls along with the keyboard, decided as the keyboard starts to open.
  const following = useSharedValue(false);
  const followFrom = useSharedValue(0);

  useEffect(() => {
    rootHeight.set(windowHeight);
  }, [rootHeight, windowHeight]);

  const lift = useDerivedValue(() => {
    const reach =
      reanimatedReports.value || keyboard.height.value > 0
        ? keyboard.height.value
        : fallbackHeight.value;
    if (reach <= 0) {
      return 0;
    }
    // Measured on every frame the keyboard moves, so it always matches the current layout.
    const area = measure(areaRef);
    if (area === null) {
      return 0;
    }
    const gapBelow = rootHeight.value - (area.pageY + area.height);
    return Math.max(0, reach - gapBelow);
  });

  useAnimatedReaction(
    () => keyboard.height.value > 0,
    (open) => {
      if (open) {
        reanimatedReports.value = true;
      }
    }
  );

  useAnimatedReaction(
    () => lift.value,
    (current, previous) => {
      if (previous === null || current === previous) {
        return;
      }
      if (previous === 0) {
        // The keyboard started to open; the spacer is still empty.
        const end = Math.max(0, contentHeight.value - viewportHeight.value);
        following.value = scrollOffset.value >= end - AT_END_THRESHOLD;
        followFrom.value = end;
      }
      if (current === 0) {
        following.value = false;
      } else if (following.value && current > previous) {
        scrollTo(scrollRef, 0, followFrom.value + current, false);
      }
    }
  );

  // The scroll in the reaction above can trail the spacer by a frame; settle exactly.
  useEffect(() => {
    const subscription = Keyboard.addListener('keyboardDidShow', () => {
      if (following.get()) {
        setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
      }
    });
    return () => subscription.remove();
  }, [following, scrollRef]);

  // The Android fallback (see the top of this file).
  useEffect(() => {
    if (Platform.OS !== 'android') {
      return;
    }
    const onShow = (event: KeyboardEvent) => {
      const reach = Math.max(0, windowHeight - event.endCoordinates.screenY);
      fallbackHeight.set(withTiming(reach, FALLBACK_ANIMATION));
    };
    const onHide = () => {
      fallbackHeight.set(withTiming(0, FALLBACK_ANIMATION));
    };
    const subscriptions = [
      Keyboard.addListener('keyboardDidShow', onShow),
      Keyboard.addListener('keyboardDidHide', onHide),
    ];
    return () => subscriptions.forEach((subscription) => subscription.remove());
  }, [fallbackHeight, windowHeight]);

  const inputStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: -lift.value }],
  }));

  const spacerStyle = useAnimatedStyle(() => ({
    height: lift.value,
  }));

  return {
    /** For the message list, an `Animated.ScrollView`. */
    scrollRef,
    /** For the `Animated.View` that holds the list and the input. */
    areaRef,
    onScrollViewLayout: (event: LayoutChangeEvent) => {
      viewportHeight.set(event.nativeEvent.layout.height);
    },
    /** Call from the list's `onContentSizeChange`. */
    trackContentHeight: (height: number) => {
      contentHeight.set(height);
    },
    /** For the input bar, an `Animated.View`. */
    inputStyle,
    /** For an `Animated.View` after the list's last message. */
    spacerStyle,
  };
}
