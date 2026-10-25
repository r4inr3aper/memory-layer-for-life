/**
 * MarkdownText Component
 *
 * Renders an assistant reply as Markdown, styled like the plain chat bubble text. Uses
 * `react-native-marked`'s `useMarkdown` hook, which returns plain elements; its default
 * component is a FlatList, which must not be nested in the chat's ScrollView.
 * Links open in the browser.
 */

import { Colors } from '@/constants/colors';
import { Fonts } from '@/constants/theme';
import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useMarkdown, type MarkedStyles, type useMarkdownHookOptions } from 'react-native-marked';

const BODY_TEXT = {
  fontSize: 15.5,
  lineHeight: 22,
  letterSpacing: -0.1,
  color: Colors.iconDark,
  fontWeight: '400',
} as const;

const MARKDOWN_STYLES: MarkedStyles = {
  text: BODY_TEXT,
  paragraph: { paddingVertical: 2 },
  strong: { ...BODY_TEXT, fontWeight: '700' },
  em: { ...BODY_TEXT, fontStyle: 'italic' },
  strikethrough: { ...BODY_TEXT, textDecorationLine: 'line-through' },
  link: {
    ...BODY_TEXT,
    color: Colors.primary,
    fontStyle: 'normal',
    textDecorationLine: 'underline',
  },
  h1: {
    ...BODY_TEXT,
    fontSize: 20,
    lineHeight: 26,
    fontWeight: '700',
    marginVertical: 4,
    paddingBottom: 0,
    borderBottomWidth: 0,
  },
  h2: {
    ...BODY_TEXT,
    fontSize: 18,
    lineHeight: 24,
    fontWeight: '700',
    marginVertical: 4,
    paddingBottom: 0,
    borderBottomWidth: 0,
  },
  h3: { ...BODY_TEXT, fontSize: 16.5, lineHeight: 23, fontWeight: '700', marginVertical: 3 },
  h4: { ...BODY_TEXT, fontWeight: '700', marginVertical: 2 },
  h5: { ...BODY_TEXT, fontWeight: '700', marginVertical: 2 },
  h6: { ...BODY_TEXT, fontWeight: '600', marginVertical: 2 },
  codespan: {
    ...BODY_TEXT,
    fontFamily: Fonts.mono,
    fontSize: 14,
    fontStyle: 'normal',
    backgroundColor: Colors.white,
  },
  code: {
    padding: 10,
    marginVertical: 4,
    borderRadius: 10,
    backgroundColor: Colors.white,
  },
  codeText: { ...BODY_TEXT, fontFamily: Fonts.mono, fontSize: 13.5, lineHeight: 19 },
  blockquote: { borderLeftColor: Colors.border, borderLeftWidth: 3, paddingLeft: 10, opacity: 0.9 },
  hr: { borderBottomColor: Colors.border, marginVertical: 6 },
  li: BODY_TEXT,
  list: { marginVertical: 2 },
  table: { borderColor: Colors.border, marginVertical: 4 },
  tableCell: { padding: 6 },
};

const MARKDOWN_OPTIONS: useMarkdownHookOptions = {
  colorScheme: 'light',
  styles: MARKDOWN_STYLES,
  theme: {
    colors: {
      text: Colors.iconDark,
      link: Colors.primary,
      code: Colors.white,
      border: Colors.border,
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
