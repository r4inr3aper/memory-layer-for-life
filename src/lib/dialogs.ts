/**
 * Cross-platform Dialogs
 *
 * React Native's `Alert` has no buttons on web (react-native-web renders nothing), so
 * confirmations there fall back to the browser's own `confirm` and `alert`.
 */

import { Alert, Platform } from 'react-native';

export interface ConfirmOptions {
  title: string;
  message: string;
  /** Label of the button that confirms. */
  confirmText: string;
  /** Shows the confirm button in red on iOS. */
  destructive?: boolean;
}

/** Asks the user to confirm. Resolves to `true` only when they pressed the confirm button. */
export function confirmAsync({
  title,
  message,
  confirmText,
  destructive = false,
}: ConfirmOptions): Promise<boolean> {
  if (Platform.OS === 'web') {
    return Promise.resolve(
      typeof window !== 'undefined' && window.confirm(`${title}\n\n${message}`)
    );
  }

  return new Promise((resolve) => {
    Alert.alert(
      title,
      message,
      [
        { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
        {
          text: confirmText,
          style: destructive ? 'destructive' : 'default',
          onPress: () => resolve(true),
        },
      ],
      { cancelable: true, onDismiss: () => resolve(false) }
    );
  });
}

/** Shows a message with an OK button. Resolves when it is dismissed. */
export function alertAsync(title: string, message: string): Promise<void> {
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined') {
      window.alert(`${title}\n\n${message}`);
    }
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    Alert.alert(title, message, [{ text: 'OK', onPress: () => resolve() }], {
      cancelable: true,
      onDismiss: () => resolve(),
    });
  });
}
