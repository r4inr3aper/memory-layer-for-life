/**
 * MarkdownText Component
 *
 * Renders an assistant reply as Markdown, in the iOS body style the chat bubbles use
 * (17 pt in the label color; headings step up through the iOS text styles). Uses
 * `react-native-marked`'s `useMarkdown` hook, which returns plain elements; its default
 * component is a FlatList, which must not be nested in the chat's ScrollView.
 * Links open in the browser.
 */

import { Colors } from '@/constants/colors';
import { Fonts, Hairline, Radius, Typography, continuous } from '@/constants/theme';
import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useMarkdown, type MarkedStyles, type useMarkdownHookOptions } from 'react-native-marked';

const BODY_TEXT = {
  ...Typography.body,
  color: Colors.label,
} as const;

const MONO_TEXT = {
  ...BODY_TEXT,
  fontFamily: Fonts.mono,
  fontStyle: 'normal',
  letterSpacing: 0,
} as const;

const MARKDOWN_STYLES: MarkedStyles = {
  text: BODY_TEXT,
  paragraph: { paddingVertical: 2 },
  strong: { ...BODY_TEXT, fontWeight: '600' },
  em: { ...BODY_TEXT, fontStyle: 'italic' },
  strikethrough: { ...BODY_TEXT, textDecorationLine: 'line-through' },
  link: {
    ...BODY_TEXT,
    color: Colors.tint,
    fontStyle: 'normal',
    textDecorationLine: 'underline',
  },
  h1: {
    ...BODY_TEXT,
    ...Typography.title3,
    fontWeight: '700',
    marginVertical: 4,
    paddingBottom: 0,
    borderBottomWidth: 0,
  },
  h2: {
    ...BODY_TEXT,
    ...Typography.headline,
    marginVertical: 4,
    paddingBottom: 0,
    borderBottomWidth: 0,
  },
  h3: { ...BODY_TEXT, ...Typography.headline, marginVertical: 3 },
  h4: { ...BODY_TEXT, fontWeight: '600', marginVertical: 2 },
  h5: { ...BODY_TEXT, fontWeight: '600', marginVertical: 2 },
  h6: { ...BODY_TEXT, ...Typography.subheadline, fontWeight: '600', marginVertical: 2 },
  codespan: {
    ...MONO_TEXT,
    fontSize: 15,
    fontWeight: '400',
    backgroundColor: Colors.systemBackground,
  },
  code: {
    ...continuous,
    padding: 10,
    marginVertical: 4,
    borderRadius: Radius.sm,
    backgroundColor: Colors.systemBackground,
  },
  codeText: { ...MONO_TEXT, fontSize: 14, lineHeight: 19 },
  blockquote: {
    borderLeftColor: Colors.separator,
    borderLeftWidth: 3,
    paddingLeft: 10,
    opacity: 0.9,
  },
  hr: { borderBottomColor: Colors.separator, borderBottomWidth: Hairline, marginVertical: 6 },
  li: BODY_TEXT,
  list: { marginVertical: 2 },
  table: { borderColor: Colors.separator, marginVertical: 4 },
  tableCell: { padding: 6 },
};

const MARKDOWN_OPTIONS: useMarkdownHookOptions = {
  colorScheme: 'light',
  styles: MARKDOWN_STYLES,
  theme: {
    colors: {
      text: Colors.label,
      link: Colors.tint,
      code: Colors.systemBackground,
      border: Colors.separator,
    },
  },
  // The bubble itself is pressable; selectable text would fight its touch handling.
  selectable: false,
};

export function MarkdownText({ text }: { text: string }) {
  const elements = useMarkdown(text, MARKDOWN_OPTIONS);
  return <View style={styles.container}>{elements}</View>;
}

const styles = StyleSheet.create({
  container: {
    flexShrink: 1,
  },
});

export default MarkdownText;
