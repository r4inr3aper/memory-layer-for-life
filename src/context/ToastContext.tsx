/**
 * Toast Context & Provider
 *
 * A short message in a dark capsule under the status bar, as iOS shows "Copied". It slides
 * down into place and leaves the way it came, about 20% faster than it arrived (the user
 * has read it). A new message replaces the one showing. Toasts are uninvited, so they
 * carry no haptic and never take touches.
 */

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, { FadeInUp, FadeOutUp } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Colors } from '@/constants/colors';
import { Elevation, Motion, Typography, continuous } from '@/constants/theme';

interface ToastContextType {
  showToast: (message: string, duration?: number) => void;
}

const ToastContext = createContext<ToastContextType>({
  showToast: () => {},
});

// Standalone global trigger support
let globalToastHandler: ((message: string, duration?: number) => void) | null = null;

export const showToast = (message: string, duration?: number) => {
  if (globalToastHandler) {
    globalToastHandler(message, duration);
  }
};

// Layout-animation builders live at module scope: built once, not on every render.
const TOAST_ENTER = FadeInUp.duration(Motion.duration.toastIn).easing(Motion.easeOut);
const TOAST_EXIT = FadeOutUp.duration(Motion.duration.toastOut).easing(Motion.easeOut);

interface Toast {
  id: number;
  message: string;
}

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toast, setToast] = useState<Toast | null>(null);
  const nextId = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const insets = useSafeAreaInsets();

  const triggerToast = useCallback((message: string, duration = 2000) => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    nextId.current += 1;
    setToast({ id: nextId.current, message });
    timeoutRef.current = setTimeout(() => setToast(null), duration);
  }, []);

  // Connect global handler
  useEffect(() => {
    globalToastHandler = triggerToast;
    return () => {
      globalToastHandler = null;
    };
  }, [triggerToast]);

  useEffect(
    () => () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    },
    []
  );

  return (
    <ToastContext.Provider value={{ showToast: triggerToast }}>
      {children}
      <View pointerEvents="none" style={[styles.toastWrapper, { top: insets.top + 8 }]}>
        {toast ? (
          <Animated.View
            key={toast.id}
            entering={TOAST_ENTER}
            exiting={TOAST_EXIT}
            style={[styles.toastContainer, continuous]}
            accessibilityLiveRegion="polite"
            accessibilityRole="alert">
            <Text style={styles.toastText} numberOfLines={3}>
              {toast.message}
            </Text>
          </Animated.View>
        ) : null}
      </View>
    </ToastContext.Provider>
  );
};

export const useToast = () => useContext(ToastContext);

const styles = StyleSheet.create({
  toastWrapper: {
    position: 'absolute',
    left: 16,
    right: 16,
    alignItems: 'center',
    zIndex: 99999,
    elevation: 99999,
  },
  toastContainer: {
    maxWidth: 420,
    backgroundColor: Colors.hud,
    paddingHorizontal: 18,
    paddingVertical: 11,
    borderRadius: 22,
    ...Elevation.floating,
  },
  toastText: {
    ...Typography.subheadline,
    fontWeight: '600',
    color: Colors.white,
    textAlign: 'center',
  },
});
