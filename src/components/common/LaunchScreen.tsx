/**
 * LaunchScreen Component
 *
 * What shows while the app works out where to go on open (restoring the saved sign-in).
 * It matches the native splash screen (Cooper on white, at the same size and position), so
 * the hand-over from the splash is seamless, and adds the name and a spinner below.
 */

import React from 'react';
import { ActivityIndicator, Image, StyleSheet, Text, View } from 'react-native';
import { Colors } from '@/constants/colors';

// The splash image's width in app.json (expo-splash-screen `imageWidth`).
const SPLASH_IMAGE_SIZE = 160;

export function LaunchScreen() {
  return (
    <View style={styles.container} accessibilityLabel="Zoop is starting">
      <Image
        source={require('../../../assets/images/splash-icon.png')}
        style={styles.image}
        accessibilityIgnoresInvertColors
      />
      <View style={styles.below}>
        <Text style={styles.name}>Zoop</Text>
        <ActivityIndicator color={Colors.primary} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  image: {
    width: SPLASH_IMAGE_SIZE,
    height: SPLASH_IMAGE_SIZE,
  },
  // Below the image without moving it from the centre, where the splash put it.
  below: {
    position: 'absolute',
    top: '50%',
    marginTop: SPLASH_IMAGE_SIZE / 2 + 24,
    alignItems: 'center',
    gap: 16,
  },
  name: {
    fontSize: 22,
    fontWeight: '800',
    color: Colors.iconDark,
    letterSpacing: -0.4,
  },
});

export default LaunchScreen;
