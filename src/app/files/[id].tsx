/**
 * File Screen ('/files/[id]')
 *
 * One of the user's documents: its title, whether the assistant can attach it, the text
 * the assistant reads, and the actions on it: open or share the file, use it as (or no
 * longer as) the resume, and delete it.
 */

import { useCallback, useState } from 'react';
import { ActivityIndicator, RefreshControl, StyleSheet, View } from 'react-native';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import Animated from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';
import { File01Icon } from '@hugeicons/core-free-icons';
import {
  AppSwitch,
  AppText,
  Button,
  Card,
  EmptyState,
  LargeTitle,
  ListRow,
  ListSection,
  ScreenHeader,
  useScrollY,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { ApiError, getErrorMessage, isAbortError } from '@/lib/api/client';
import { deleteDocument, getDocument, updateDocument } from '@/lib/api/documents';
import type { DocumentDetail } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { shareDocumentFile } from '@/lib/documentFiles';
import { documentKind, documentMeta, formatFileSize } from '@/lib/documents';
import { haptic } from '@/lib/haptics';

type Action = 'resume' | 'delete' | 'share';

// Long documents show their start until asked for the rest.
const PREVIEW_CHARS = 1500;

export default function FileScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const { profile } = useAgentProfile();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { scrollY, onScroll } = useScrollY();
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [busy, setBusy] = useState<Action | null>(null);
  const [showAllText, setShowAllText] = useState(false);

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!id) return Promise.resolve();
      return getDocument(id, signal)
        .then((loaded) => {
          setDocument(loaded);
          setStatus('ready');
        })
        .catch((error) => {
          if (isAbortError(error, signal)) return;
          if (error instanceof ApiError && error.status === 404) {
            setStatus('missing');
            return;
          }
          setErrorMessage(getErrorMessage(error, 'Could not load this file'));
          setStatus((current) => (current === 'ready' ? current : 'error'));
        });
    },
    [id]
  );

  useFocusEffect(
    useCallback(() => {
      if (!hasSession) return undefined;
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [hasSession, load])
  );

  const act = async (action: Action, work: () => Promise<void>) => {
    if (busy) return;
    setBusy(action);
    try {
      await work();
    } catch (error) {
      haptic.error();
      showToast(getErrorMessage(error, 'Something went wrong'), 3500);
    } finally {
      setBusy(null);
    }
  };

  const setResume = (marking: boolean) =>
    act('resume', async () => {
      if (!document) return;
      // Shown at once; the server's answer confirms it.
      setDocument({ ...document, is_resume: marking });
      try {
        await updateDocument(document.id, { is_resume: marking });
      } catch (error) {
        setDocument(document);
        throw error;
      }
      await load();
      showToast(marking ? `${profile.name} will use this as your resume` : 'No longer your resume');
    });

  const share = () =>
    act('share', async () => {
      if (!document) return;
      await shareDocumentFile(document);
    });

  const handleDelete = () =>
    act('delete', async () => {
      if (!document) return;
      const confirmed = await confirmAsync({
        title: 'Delete this file?',
        message: `"${document.title}" will be deleted. ${profile.name} won't be able to read or send it any more. This can't be undone.`,
        confirmText: 'Delete',
        destructive: true,
      });
      if (!confirmed) return;
      await deleteDocument(document.id);
      haptic.medium();
      showToast('File deleted');
      if (router.canGoBack()) router.back();
      else router.replace('/files');
    });

  if (!hasSession) {
    return <View style={styles.safeArea} />;
  }

  const text = document?.text ?? '';
  const textCut = !showAllText && text.length > PREVIEW_CHARS;

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      <ScreenHeader title={document?.title ?? 'File'} fallbackHref="/files" scrollY={scrollY} />

      {status === 'loading' ? (
        <ActivityIndicator style={styles.spinner} color={Colors.systemGray} />
      ) : status === 'missing' ? (
        <EmptyState icon={File01Icon} title="This file no longer exists" message="It may have been deleted." />
      ) : status === 'error' || !document ? (
        <EmptyState
          icon={File01Icon}
          title="Couldn't load this file"
          message={errorMessage}
          actionTitle="Try Again"
          onAction={() => {
            setStatus('loading');
            void load();
          }}
        />
      ) : (
        <Animated.ScrollView
          onScroll={onScroll}
          scrollEventThrottle={16}
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={() => {
                setIsRefreshing(true);
                void load().finally(() => setIsRefreshing(false));
              }}
              tintColor={Colors.systemGray}
            />
          }>
          <LargeTitle title={document.title} subtitle={`${document.file_name} · ${documentMeta(document)}`} />

          <ListSection
            footer={
              document.has_file
                ? `${profile.name} can attach this file to emails you approve, like a job application.`
                : `Only the text of this file was kept, so ${profile.name} can't attach it. Upload the same file again in Files & links to keep it.`
            }>
            <ListRow title="Kind" value={documentKind(document.media_type)} />
            <ListRow title="Size" value={formatFileSize(document.size_bytes)} />
            <ListRow title="Attach to emails" value={document.has_file ? 'Ready' : 'Text only'} />
            {document.has_file ? (
              <ListRow
                title={busy === 'share' ? 'Opening…' : 'Open or Share'}
                action
                disabled={busy !== null}
                onPress={() => void share()}
              />
            ) : null}
          </ListSection>

          <ListSection
            footer={`${profile.name} reads your resume for job applications and questions about your work. Choosing this file replaces your previous resume.`}>
            <ListRow
              title="Use as My Resume"
              accessory={
                <AppSwitch
                  value={document.is_resume}
                  disabled={busy !== null}
                  onValueChange={(value) => void setResume(value)}
                  accessibilityLabel="Use as my resume"
                />
              }
            />
          </ListSection>

          <ListSection header={`What ${profile.name} reads`}>
            <Card style={styles.textCard}>
              <AppText variant="subheadline" selectable>
                {textCut ? `${text.slice(0, PREVIEW_CHARS).trimEnd()}…` : text}
              </AppText>
              {text.length > PREVIEW_CHARS ? (
                <Button
                  title={showAllText ? 'Show Less' : 'Show All'}
                  variant="plain"
                  size="small"
                  onPress={() => setShowAllText((value) => !value)}
                  containerStyle={styles.showAll}
                />
              ) : null}
            </Card>
          </ListSection>

          <ListSection>
            <ListRow
              title={busy === 'delete' ? 'Deleting…' : 'Delete File'}
              destructive
              action
              disabled={busy !== null}
              onPress={() => void handleDelete()}
            />
          </ListSection>
        </Animated.ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  spinner: {
    marginTop: 40,
  },
  content: {
    paddingBottom: 48,
  },
  textCard: {
    borderRadius: 0,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  showAll: {
    alignSelf: 'flex-start',
    marginTop: 6,
  },
});
