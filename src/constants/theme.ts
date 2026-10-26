/**
 * Zoop - Theme, Typography, Motion & Layout Constants
 *
 * The app follows Apple's iOS design language: the system font with iOS text styles,
 * continuous ("squircle") corners, hairline separators, and motion that answers the finger
 * at once and settles without bouncing (docs: AGENTS.md, "Design system").
 */

import { Platform, StyleSheet, type TextStyle, type ViewStyle } from "react-native";
import { Easing } from "react-native-reanimated";
import { Colors } from "./colors";

export { Colors } from "./colors";

/**
 * Valid theme keys supported by light and dark color palettes.
 */
export type ThemeColor = keyof typeof Colors.light & keyof typeof Colors.dark;

/**
 * Cross-platform font family mappings:
 * - iOS: native Apple San Francisco system design fonts
 * - Android/Default: robust platform fallbacks
 * - Web: clean modern sans-serif typography stack
 */
export const Fonts = Platform.select({
  ios: {
    sans: "system-ui",
    serif: "ui-serif",
    rounded: "ui-rounded",
    mono: "ui-monospace",
  },
  default: {
    sans: "normal",
    serif: "serif",
    rounded: "normal",
    mono: "monospace",
  },
  web: {
    sans: '-apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, system-ui, "Segoe UI", Roboto, sans-serif',
    serif: 'Georgia, "Times New Roman", serif',
    rounded: '"SF Pro Rounded", "Hiragino Maru Gothic ProN", sans-serif',
    mono: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  },
});

/**
 * Tracking is size-specific: San Francisco ships its own table (large sizes open up,
 * body text closes in), while Roboto and the web stack want large text tightened and
 * body text left alone.
 */
function tracking(ios: number, other: number): number {
  return Platform.OS === "ios" ? ios : other;
}

/**
 * iOS text styles at the default ("Large") Dynamic Type size. Hierarchy comes from size,
 * weight, and leading together; emphasize with weight, never with a new size.
 */
export const Typography = {
  largeTitle: { fontSize: 34, lineHeight: 41, fontWeight: "700", letterSpacing: tracking(0.37, -0.6) },
  title1: { fontSize: 28, lineHeight: 34, fontWeight: "700", letterSpacing: tracking(0.36, -0.5) },
  title2: { fontSize: 22, lineHeight: 28, fontWeight: "700", letterSpacing: tracking(0.35, -0.35) },
  title3: { fontSize: 20, lineHeight: 25, fontWeight: "600", letterSpacing: tracking(0.38, -0.25) },
  headline: { fontSize: 17, lineHeight: 22, fontWeight: "600", letterSpacing: tracking(-0.43, -0.1) },
  body: { fontSize: 17, lineHeight: 22, fontWeight: "400", letterSpacing: tracking(-0.43, 0) },
  callout: { fontSize: 16, lineHeight: 21, fontWeight: "400", letterSpacing: tracking(-0.31, 0) },
  subheadline: { fontSize: 15, lineHeight: 20, fontWeight: "400", letterSpacing: tracking(-0.23, 0) },
  footnote: { fontSize: 13, lineHeight: 18, fontWeight: "400", letterSpacing: tracking(-0.08, 0.1) },
  caption1: { fontSize: 12, lineHeight: 16, fontWeight: "400", letterSpacing: tracking(0, 0.2) },
  caption2: { fontSize: 11, lineHeight: 13, fontWeight: "400", letterSpacing: tracking(0.06, 0.25) },
} as const satisfies Record<string, TextStyle>;

export type TypographyVariant = keyof typeof Typography;

/**
 * Corner radii. Pair every radius with `borderCurve: 'continuous'` (Radius.curve) for
 * Apple's squircle corners; Android ignores it and draws circular ones.
 */
export const Radius = {
  xs: 6,
  sm: 8,
  md: 12,
  // Inset-grouped lists and cards.
  lg: 16,
  xl: 22,
  // Sheets.
  sheet: 24,
  pill: 999,
} as const;

export const continuous = { borderCurve: "continuous" } as const satisfies ViewStyle;

/** One physical pixel: separators and outlines. */
export const Hairline = StyleSheet.hairlineWidth;

/**
 * Consistent 8-point spacing grid used for padding, margins, and gaps.
 */
export const Spacing = {
  half: 2,
  one: 4,
  two: 8,
  three: 16,
  four: 24,
  five: 32,
  six: 64,
} as const;

/** The side margin of screens and inset lists. */
export const ScreenMargin = 16;

/**
 * Motion. Press feedback answers in the same frame and lasts 120 ms; anything a finger
 * moved settles on a spring that carries its velocity; nothing UI eases in.
 */
export const Motion = {
  // Strong ease-out for anything entering, leaving, or answering a press.
  easeOut: Easing.bezier(0.23, 1, 0.32, 1),
  // Movement across the screen (a segmented thumb).
  easeInOut: Easing.bezier(0.77, 0, 0.175, 1),
  // The iOS sheet curve.
  easeSheet: Easing.bezier(0.32, 0.72, 0, 1),
  // The same curves for Reanimated CSS transitions.
  css: {
    easeOut: "cubic-bezier(0.23, 1, 0.32, 1)",
    easeInOut: "cubic-bezier(0.77, 0, 0.175, 1)",
  },
  duration: {
    press: 120,
    small: 180,
    toastIn: 280,
    toastOut: 220,
  },
  // Springs in Apple's terms: perceptual duration and damping ratio.
  spring: {
    settle: { duration: 400, dampingRatio: 1 },
    snapBack: { duration: 400, dampingRatio: 0.8 },
    sheet: { duration: 320, dampingRatio: 0.86 },
  },
  pressedScale: 0.97,
} as const;

/** Soft, layered elevation for floating surfaces (menus, sheets, the toast). */
export const Elevation = {
  floating: Platform.select<ViewStyle>({
    ios: {
      shadowColor: "#000",
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.12,
      shadowRadius: 24,
    },
    android: { elevation: 8 },
    default: { boxShadow: "0 8px 30px rgba(0, 0, 0, 0.12)" },
  }),
  raised: Platform.select<ViewStyle>({
    ios: {
      shadowColor: "#000",
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.08,
      shadowRadius: 3,
    },
    android: { elevation: 1 },
    default: { boxShadow: "0 1px 3px rgba(0, 0, 0, 0.08)" },
  }),
} as const;

/**
 * Platform-dependent safe insets for bottom floating tab bar dock.
 */
export const BottomTabInset = Platform.select({ ios: 50, android: 80 }) ?? 0;

/**
 * Maximum content container width for responsive web / tablet rendering.
 */
export const MaxContentWidth = 800;
