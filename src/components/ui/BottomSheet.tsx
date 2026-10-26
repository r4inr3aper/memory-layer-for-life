/**
 * BottomSheet: an iOS sheet for a short task inside the current screen (an editor, a
 * picker, a menu of actions).
 *
 * - It rises on a critically damped spring (no bounce: nothing was thrown) and the
 *   backdrop dims in step, derived from the same value, so they never drift apart.
 * - The grabber and the title bar drag it. The finger moves it 1:1; past the top it
 *   resists (rubber band); on release, momentum decides: a quick flick dismisses even
 *   from a few points down, a slow drag springs home with the finger's velocity and a
 *   light tap.
 * - Interruptible: grabbing it while it moves continues from where it is on screen.
 * - With Reduce Motion on, it cross-fades instead of sliding.
 * - Cancel and the action (Save, Done) sit in its title bar, as in iOS.
 * - While `dismissible` is false (a save in flight), it stays put: no drag, no tap on the
 *   backdrop, no back button.
 */

import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  useWindowDimensions,
  type LayoutChangeEvent,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import {
  GestureDetector,
  GestureHandlerRootView,
  usePanGesture,
} from 'react-native-gesture-handler';
import Animated, {
  Extrapolation,
  interpolate,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { scheduleOnRN } from 'react-native-worklets';
import { Colors } from '@/constants/colors';
import { Motion, Radius, continuous } from '@/constants/theme';
import { haptic } from '@/lib/haptics';
import { AppText } from './AppText';

export interface SheetAction {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  loading?: boolean;
}

export interface BottomSheetProps {
  visible: boolean;
  onClose: () => void;
  title?: string;
  /** At the left of the title bar; usually Cancel. */
  leftAction?: SheetAction;
  /** At the right of the title bar, in bold; usually Save or Done. */
  rightAction?: SheetAction;
  children: React.ReactNode;
  /** `auto` fits the content (up to nearly full height); `large` is nearly full height. */
  detent?: 'auto' | 'large';
  /** Wrap the content in a scroll view (long forms). */
  scrollable?: boolean;
  /** False keeps it open whatever the user does, while its work finishes. */
  dismissible?: boolean;
  contentStyle?: StyleProp<ViewStyle>;
  testID?: string;
}

// Where a flick would come to rest if the finger kept decelerating (Apple's projection).
function project(velocity: number, decelerationRate = 0.998): number {
  'worklet';
  return ((velocity / 1000) * decelerationRate) / (1 - decelerationRate);
}

// The further past the edge, the less it follows.
function rubberband(overshoot: number, dimension: number, constant = 0.55): number {
  'worklet';
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}

const TOP_GAP = 12;

export function BottomSheet({
  visible,
  onClose,
  title,
  leftAction,
  rightAction,
  children,
  detent = 'auto',
  scrollable = false,
  dismissible = true,
  contentStyle,
  testID,
}: BottomSheetProps) {
  const { height: windowHeight } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const reducedMotion = useReducedMotion();

  // Mounted from the moment it should show until it has finished leaving.
  const [rendered, setRendered] = useState(visible);
  if (visible && !rendered) {
    setRendered(true);
  }

  const translateY = useSharedValue(windowHeight);
  const sheetHeight = useSharedValue(windowHeight);
  const fade = useSharedValue(0);
  const dragStart = useSharedValue(0);
  const presented = useSharedValue(false);

  // Hiding plays the exit, then unmounts.
  useEffect(() => {
    if (visible || !rendered) return;
    const unmount = () => {
      presented.set(false);
      setRendered(false);
    };
    if (reducedMotion) {
      fade.set(
        withTiming(0, { duration: Motion.duration.toastOut }, (finished) => {
          if (finished) scheduleOnRN(unmount);
        })
      );
    } else {
      translateY.set(
        withSpring(sheetHeight.get(), { ...Motion.spring.settle, overshootClamping: true }, (finished) => {
          if (finished) scheduleOnRN(unmount);
        })
      );
    }
  }, [visible, rendered, reducedMotion, fade, translateY, sheetHeight, presented]);

  const onSheetLayout = (event: LayoutChangeEvent) => {
    const height = event.nativeEvent.layout.height;
    sheetHeight.set(height);
    if (presented.get() || !visible) return;
    presented.set(true);
    if (reducedMotion) {
      translateY.set(0);
      fade.set(withTiming(1, { duration: Motion.duration.toastIn, easing: Motion.easeOut }));
    } else {
      fade.set(1);
      translateY.set(height);
      translateY.set(withSpring(0, Motion.spring.settle));
    }
  };

  const requestClose = () => {
    if (dismissible) onClose();
  };

  const pan = usePanGesture({
    enabled: dismissible,
    activeOffsetY: [-8, 8],
    onActivate: () => {
      'worklet';
      dragStart.set(translateY.get());
    },
    onUpdate: (event) => {
      'worklet';
      const next = dragStart.get() + event.translationY;
      translateY.set(next >= 0 ? next : rubberband(next, sheetHeight.get()));
    },
    onDeactivate: (event) => {
      'worklet';
      const height = sheetHeight.get();
      const projected = translateY.get() + project(event.velocityY);
      if (projected > height * 0.4) {
        translateY.set(
          withSpring(
            height,
            { ...Motion.spring.settle, velocity: event.velocityY, overshootClamping: true },
            (finished) => {
              if (finished) scheduleOnRN(onClose);
            }
          )
        );
      } else {
        translateY.set(withSpring(0, { ...Motion.spring.snapBack, velocity: event.velocityY }));
        scheduleOnRN(haptic.light);
      }
    },
  });

  const sheetStyle = useAnimatedStyle(() => ({
    opacity: fade.get(),
    transform: [{ translateY: Math.max(translateY.get(), -40) }],
  }));
  const backdropStyle = useAnimatedStyle(() => ({
    opacity:
      fade.get() *
      interpolate(translateY.get(), [0, sheetHeight.get()], [1, 0], Extrapolation.CLAMP),
  }));

  const maxHeight = windowHeight - insets.top - TOP_GAP;
  const hasTitleBar = Boolean(title || leftAction || rightAction);

  const body = scrollable ? (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={[styles.content, contentStyle]}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}>
      {children}
    </ScrollView>
  ) : (
    <View style={[styles.content, contentStyle]}>{children}</View>
  );

  return (
    <Modal
      visible={rendered}
      transparent
      animationType="none"
      statusBarTranslucent
      navigationBarTranslucent
      onRequestClose={requestClose}>
      <GestureHandlerRootView style={styles.root}>
        <Animated.View style={[StyleSheet.absoluteFill, styles.backdrop, backdropStyle]}>
          <Pressable
            style={StyleSheet.absoluteFill}
            onPress={requestClose}
            accessibilityRole="button"
            accessibilityLabel="Close"
          />
        </Animated.View>
        <KeyboardAvoidingView behavior="padding" style={styles.keyboard} pointerEvents="box-none">
          <Animated.View
            testID={testID}
            onLayout={onSheetLayout}
            style={[
              styles.sheet,
              continuous,
              { maxHeight, paddingBottom: Math.max(insets.bottom, 12) },
              detent === 'large' && { height: maxHeight },
              sheetStyle,
            ]}>
            <GestureDetector gesture={pan}>
              <View style={styles.dragRegion}>
                <View style={styles.grabber} />
                {hasTitleBar ? (
                  <View style={styles.titleBar}>
                    <View style={styles.titleSide}>
                      {leftAction ? <BarButton action={leftAction} /> : null}
                    </View>
                    <AppText variant="headline" numberOfLines={1} style={styles.title}>
                      {title ?? ''}
                    </AppText>
                    <View style={[styles.titleSide, styles.titleSideRight]}>
                      {rightAction ? <BarButton action={rightAction} prominent /> : null}
                    </View>
                  </View>
                ) : null}
              </View>
            </GestureDetector>
            {body}
          </Animated.View>
        </KeyboardAvoidingView>
      </GestureHandlerRootView>
    </Modal>
  );
}

function BarButton({ action, prominent = false }: { action: SheetAction; prominent?: boolean }) {
  if (action.loading) {
    return <ActivityIndicator size="small" color={Colors.tint} />;
  }
  return (
    <Pressable
      onPress={action.onPress}
      disabled={action.disabled}
      hitSlop={12}
      accessibilityRole="button"
      accessibilityState={{ disabled: action.disabled }}
      style={({ pressed }) => [pressed && styles.barButtonPressed]}>
      <AppText
        variant={prominent ? 'headline' : 'body'}
        color={action.disabled ? 'tertiary' : 'tint'}
        numberOfLines={1}>
        {action.label}
      </AppText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  backdrop: {
    backgroundColor: Colors.scrim,
  },
  keyboard: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: Colors.groupedBackground,
    borderTopLeftRadius: Radius.sheet,
    borderTopRightRadius: Radius.sheet,
    overflow: 'hidden',
  },
  dragRegion: {
    paddingTop: 6,
  },
  grabber: {
    alignSelf: 'center',
    width: 36,
    height: 5,
    borderRadius: 2.5,
    backgroundColor: Colors.systemGray3,
    marginBottom: 4,
  },
  titleBar: {
    height: 48,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
  },
  titleSide: {
    width: 84,
    alignItems: 'flex-start',
  },
  titleSideRight: {
    alignItems: 'flex-end',
  },
  title: {
    flex: 1,
    textAlign: 'center',
  },
  barButtonPressed: {
    opacity: 0.4,
  },
  scroll: {
    flexGrow: 0,
  },
  content: {
    paddingTop: 8,
  },
});

export default BottomSheet;
