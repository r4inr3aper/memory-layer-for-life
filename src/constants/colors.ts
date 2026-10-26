/**
 * Zoop - Centralized Design Tokens & Color Palette
 *
 * Apple's iOS system palette (light appearance): system blue as the tint, the grouped
 * background behind inset lists, labels in four strengths, hairline separators, and the
 * system colors for status. New UI uses the semantic tokens in the first block; the older
 * names below them map onto the same palette so every screen shares it.
 */

export const Colors = {
  // --- Semantic iOS tokens (use these in new UI) -------------------------------------
  // The app's tint: links, selected states, primary buttons.
  tint: "#007AFF",
  tintPressed: "#0062CC",
  // A tint wash behind tinted buttons and selected chips.
  tintFill: "#E5F1FF",

  // Backgrounds. Lists and settings sit on the grouped background, in white cells.
  systemBackground: "#FFFFFF",
  groupedBackground: "#F2F2F7",
  secondaryGroupedBackground: "#FFFFFF",
  // A cell while a finger is on it.
  cellPressed: "#E5E5EA",

  // Labels, strongest first.
  label: "#000000",
  secondaryLabel: "#6E6E73",
  tertiaryLabel: "#AEAEB2",
  quaternaryLabel: "#C7C7CC",
  placeholder: "#AEAEB2",

  // Fills for controls: segmented tracks, text fields, round buttons. Translucent, as in
  // iOS, so a control reads the same on white and on the grouped gray.
  fill: "rgba(120, 120, 128, 0.2)",
  secondaryFill: "rgba(120, 120, 128, 0.16)",
  tertiaryFill: "rgba(118, 118, 128, 0.12)",
  quaternaryFill: "rgba(116, 116, 128, 0.08)",

  // Hairlines between rows and under bars.
  separator: "#C6C6C8",
  separatorLight: "#E5E5EA",

  // System colors.
  systemBlue: "#007AFF",
  systemGreen: "#34C759",
  systemOrange: "#FF9500",
  systemRed: "#FF3B30",
  systemYellow: "#FFCC00",
  systemTeal: "#30B0C7",
  systemIndigo: "#5856D6",
  systemPurple: "#AF52DE",
  systemPink: "#FF2D55",
  systemGray: "#8E8E93",
  systemGray2: "#AEAEB2",
  systemGray3: "#C7C7CC",
  systemGray4: "#D1D1D6",
  systemGray5: "#E5E5EA",
  systemGray6: "#F2F2F7",

  // Floating bars: nearly opaque white, so content scrolling under them stays legible.
  barBackground: "rgba(255, 255, 255, 0.94)",
  // The dimming behind sheets and menus.
  scrim: "rgba(0, 0, 0, 0.32)",
  // The dark capsule of toasts.
  hud: "rgba(28, 28, 30, 0.94)",

  // --- Established names, on the same palette ----------------------------------------
  // Brand Primary
  primary: "#007AFF",
  primaryDark: "#0062CC",
  primaryLight: "#409CFF",
  primaryGradientStart: "#409CFF",
  primaryGradientEnd: "#0062CC",
  primarySubtle: "#E5F1FF",
  primaryGlow: "rgba(0, 122, 255, 0.12)",
  primaryBorder: "#B3D7FF",

  // Neutral / Layout Colors
  white: "#FFFFFF",
  black: "#000000",
  background: "#FFFFFF",
  surface: "#F2F2F7",
  surfaceElevated: "#FFFFFF",
  surfaceMuted: "#EFEFF0",
  surfaceInput: "#EFEFF0",

  // Text Colors
  text: "#000000",
  textPrimary: "#000000",
  textSecondary: "#6E6E73",
  textMuted: "#8E8E93",
  textDisabled: "#C7C7CC",
  textWhite: "#FFFFFF",
  textLink: "#007AFF",

  // Border & Dividers
  border: "#E5E5EA",
  borderLight: "#F2F2F7",
  borderFocus: "#007AFF",
  divider: "#E5E5EA",

  // Status & Feedback
  success: "#34C759",
  successLight: "#E9F8ED",
  warning: "#FF9500",
  warningLight: "#FFF4E5",
  error: "#FF3B30",
  errorLight: "#FFECEB",
  info: "#32ADE6",
  infoLight: "#EAF6FC",

  // Tab & Chat UI specific tokens
  tabInactive: "#8E8E93",
  tabActive: "#007AFF",
  // The oval pill behind the selected tab's icon.
  tabActiveBg: "#E9E9EE",
  // Messages: the user's in the tint, the assistant's in iMessage gray.
  chatBubbleUser: "#007AFF",
  chatBubbleUserText: "#FFFFFF",
  chatBubbleAi: "#E9E9EB",
  chatBubbleAiBorder: "transparent",
  dateBadgeBg: "#F2F2F7",
  dateBadgeText: "#8E8E93",
  overlay: "rgba(0, 0, 0, 0.32)",
  statusBlue: "#007AFF",
  iconDark: "#1C1C1E",
  iconMuted: "#8E8E93",
  inputBg: "#FFFFFF",
  inputBarBg: "#FFFFFF",
  inputBorder: "#D1D1D6",
  inputBarBorder: "#E5E5EA",
  dockBg: "#FFFFFF",
  avatarPreviewBg: "#F2F2F7",
  avatarOptionBg: "#F2F2F7",
  avatarOptionSelectedBg: "#E5F1FF",
  avatarOptionSelectedBorder: "#007AFF",
  avatarAccentIndigo: "#5856D6",
  avatarAccentEmerald: "#34C759",
  avatarAccentAmber: "#FF9500",
  avatarAccentViolet: "#AF52DE",
  avatarAccentRose: "#FF2D55",

  // Settings cards: white cells on the grouped background.
  cardSurface: "#FFFFFF",
  cardBorder: "#E5E5EA",

  // Charts (one series, one hue; the axis text keeps 4.5:1 on white)
  chartBar: "#007AFF",
  chartBarSelected: "#0062CC",
  chartGrid: "#E5E5EA",
  chartAxisText: "#6E6E73",

  browserPreviewBg: "#ffffff",
  // Google Branding
  googleBlue: "#4285F4",
  googleRed: "#EA4335",
  googleYellow: "#FBBC05",
  googleGreen: "#34A853",
  googleBorder: "#DADCE0",
  googleBgHover: "#F8FAFD",

  // Scheme palette (the app is light only; app.json userInterfaceStyle)
  light: {
    text: "#000000",
    background: "#FFFFFF",
    backgroundElement: "#F2F2F7",
    backgroundSelected: "#E5F1FF",
    textSecondary: "#6E6E73",
    tint: "#007AFF",
    card: "#FFFFFF",
    border: "#E5E5EA",
  },
  dark: {
    text: "#FFFFFF",
    background: "#000000",
    backgroundElement: "#1C1C1E",
    backgroundSelected: "#0A2A4D",
    textSecondary: "#98989F",
    tint: "#0A84FF",
    card: "#1C1C1E",
    border: "#38383A",
  },
} as const;

export type ColorType = typeof Colors;
export default Colors;
