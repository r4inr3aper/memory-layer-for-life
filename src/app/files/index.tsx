/**
 * Files & Links Screen ('/files')
 *
 * What the assistant can read and send for the user (ADR-049, ADR-050):
 * - Files: PDFs, Word documents, and text files. The assistant reads them when it helps
 *   and attaches them to emails the user approves, like the resume to a job application.
 *   The first file that looks like a resume becomes the resume; any file can be marked as
 *   it on its own screen. Files uploaded before files were kept are text only until the
 *   same file is uploaded again.
 * - Links: addresses the assistant shares as they are, like a resume on Google Drive, a
 *   portfolio, or a profile. At most one is the resume.
 *
 * Deleting either removes it at once: the assistant can no longer read or send it.
 */

import { useCallback, useState } from 'react';
import { ActivityIndicator, RefreshControl, StyleSheet, TextInput, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import Animated from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Briefcase01Icon,
  File01Icon,
  GithubIcon,
  Globe02Icon,
  Link01Icon,
  Linkedin01Icon,
  PaintBoardIcon,
} from '@hugeicons/core-free-icons';
import type { IconSvgElement } from '@hugeicons/react-native';
import {
  AppText,
  BottomSheet,
  LargeTitle,
  ListRow,
  ListSection,
  ScreenHeader,
  useScrollY,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Hairline, ScreenMargin, Typography } from '@/constants/theme';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { listDocuments, uploadDocument } from '@/lib/api/documents';
import { deleteLink, listLinks, saveLink, updateLink } from '@/lib/api/links';
import type { LinkKind, SavedLink, UserDocument } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { pickDocument } from '@/lib/documentPicker';
import { LINK_KINDS, displayUrl, documentMeta } from '@/lib/documents';
import { haptic } from '@/lib/haptics';

// iOS cannot present a sheet while another is still leaving, so the second waits.
const AFTER_SHEET_MS = 380;

const LINK_LOOK: Record<LinkKind, { icon: IconSvgElement; color: string }> = {
  resume: { icon: Briefcase01Icon, color: Colors.systemGreen },
  portfolio: { icon: PaintBoardIcon, color: Colors.systemPurple },
  linkedin: { icon: Linkedin01Icon, color: Colors.systemBlue },
  github: { icon: GithubIcon, color: Colors.iconDark },
  website: { icon: Globe02Icon, color: Colors.systemTeal },
  other: { icon: Link01Icon, color: Colors.systemGray },
};

type LinkEditor = { mode: 'add' } | { mode: 'edit'; link: SavedLink };

export default function FilesScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const { profile } = useAgentProfile();
  const { scrollY, onScroll } = useScrollY();

  const [documents, setDocuments] = useState<UserDocument[] | null>(null);
  const [links, setLinks] = useState<SavedLink[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const [linkActions, setLinkActions] = useState<SavedLink | null>(null);
  const [editor, setEditor] = useState<LinkEditor | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    return Promise.all([listDocuments(signal), listLinks(signal)])
      .then(([files, saved]) => {
        setDocuments(files);
        setLinks(saved);
        setError(null);
      })
      .catch((loadError) => {
        if (isAbortError(loadError, signal)) return;
        setError(getErrorMessage(loadError, "Couldn't load your files and links"));
      });
  }, []);

  useFocusEffect(
    useCallback(() => {
      if (!hasSession) return undefined;
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [hasSession, load])
  );

  // --- Files -------------------------------------------------------------------------

  const handleUpload = async () => {
    if (isUploading) return;
    let picked;
    try {
      picked = await pickDocument();
    } catch (pickError) {
      showToast(getErrorMessage(pickError, 'Could not open the file'), 4000);
      return;
    }
    if (!picked) return;

    setIsUploading(true);
    try {
      const document = await uploadDocument(picked);
      // The same file as one kept as text only: now its file is kept too.
      const before = documents?.find((item) => item.id === document.id);
      haptic.success();
      showToast(
        !document.created
          ? before && !before.has_file && document.has_file
            ? `Kept the file. ${profile.name} can now attach it to emails.`
            : 'This file is already in My files'
          : document.is_resume
            ? `Added as your resume. ${profile.name} will use it for applications.`
            : 'Added',
        3500
      );
      await load();
    } catch (uploadError) {
      haptic.error();
      showToast(getErrorMessage(uploadError, 'Could not add the file'), 4000);
    } finally {
      setIsUploading(false);
    }
  };

  // --- Links -------------------------------------------------------------------------

  const openLink = async (link: SavedLink) => {
    try {
      await WebBrowser.openBrowserAsync(link.url);
    } catch {
      showToast('Could not open the link', 3000);
    }
  };

  const afterSheet = (next: () => void) => {
    setLinkActions(null);
    setTimeout(next, AFTER_SHEET_MS);
  };

  const toggleResumeLink = async (link: SavedLink) => {
    const marking = link.kind !== 'resume';
    try {
      await updateLink(link.id, { kind: marking ? 'resume' : 'other' });
      haptic.success();
      showToast(marking ? `${profile.name} will share this as your resume` : 'No longer your resume link');
      await load();
    } catch (updateError) {
      showToast(getErrorMessage(updateError, 'Could not change the link'), 3500);
    }
  };

  const removeLink = async (link: SavedLink) => {
    const confirmed = await confirmAsync({
      title: 'Delete this link?',
      message: `"${link.title}" will be deleted. ${profile.name} won't share it any more.`,
      confirmText: 'Delete',
      destructive: true,
    });
    if (!confirmed) return;
    try {
      await deleteLink(link.id);
      haptic.medium();
      setLinks((current) => current?.filter((item) => item.id !== link.id) ?? null);
      showToast('Link deleted');
    } catch (deleteError) {
      showToast(getErrorMessage(deleteError, 'Could not delete the link'), 3500);
    }
  };

  if (!hasSession) {
    return <View style={styles.safeArea} />;
  }

  const loading = (documents === null || links === null) && !error;

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      <ScreenHeader title="Files & links" scrollY={scrollY} />

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
        <LargeTitle
          title="Files & links"
          subtitle={`What ${profile.name} can read and send for you, like your resume for job applications.`}
        />

        {error ? (
          <ListSection>
            <ListRow title={error} subtitle="Tap to try again" onPress={() => void load()} accessory="none" />
          </ListSection>
        ) : null}

        {loading ? (
          <ActivityIndicator style={styles.spinner} color={Colors.systemGray} />
        ) : (
          <>
            <ListSection
              header="Files"
              footer={`${profile.name} reads these when it helps and attaches them to emails you approve. Delete a file and ${profile.name} can no longer read or send it.`}>
              {(documents ?? []).map((document) => (
                <ListRow
                  key={document.id}
                  icon={File01Icon}
                  iconColor={document.is_resume ? Colors.systemGreen : Colors.systemBlue}
                  title={document.title}
                  subtitle={
                    document.has_file
                      ? documentMeta(document)
                      : `${documentMeta(document)} · Text only, upload again to attach`
                  }
                  value={document.is_resume ? 'Resume' : undefined}
                  onPress={() => router.push({ pathname: '/files/[id]', params: { id: document.id } })}
                />
              ))}
              <ListRow
                title={isUploading ? 'Adding…' : 'Add a File'}
                action
                disabled={isUploading}
                onPress={() => void handleUpload()}
                accessibilityLabel="Add a file"
              />
            </ListSection>

            <ListSection
              header="Links"
              footer={`${profile.name} shares these as they are, like your resume link in a job application. Nothing is fetched from them.`}>
              {(links ?? []).map((link) => {
                const look = LINK_LOOK[link.kind];
                return (
                  <ListRow
                    key={link.id}
                    icon={look.icon}
                    iconColor={look.color}
                    title={link.title}
                    subtitle={displayUrl(link)}
                    value={link.kind === 'resume' ? 'Resume' : undefined}
                    onPress={() => setLinkActions(link)}
                    onLongPress={() => void openLink(link)}
                  />
                );
              })}
              <ListRow title="Add a Link" action onPress={() => setEditor({ mode: 'add' })} />
            </ListSection>
          </>
        )}
      </Animated.ScrollView>

      {/* A link's actions */}
      <BottomSheet
        visible={linkActions !== null}
        onClose={() => setLinkActions(null)}
        title={linkActions?.title}>
        {linkActions ? (
          <View style={styles.sheetBody}>
            <AppText variant="footnote" color="secondary" numberOfLines={2} style={styles.sheetUrl}>
              {displayUrl(linkActions)}
            </AppText>
            <ListSection>
              <ListRow title="Open Link" accessory="none" onPress={() => {
                const link = linkActions;
                afterSheet(() => void openLink(link));
              }} />
              <ListRow title="Edit" accessory="none" onPress={() => {
                const link = linkActions;
                afterSheet(() => setEditor({ mode: 'edit', link }));
              }} />
              <ListRow
                title={linkActions.kind === 'resume' ? 'Not My Resume' : 'Use as My Resume'}
                accessory="none"
                onPress={() => {
                  const link = linkActions;
                  setLinkActions(null);
                  void toggleResumeLink(link);
                }}
              />
            </ListSection>
            <ListSection>
              <ListRow
                title="Delete Link"
                destructive
                accessory="none"
                onPress={() => {
                  const link = linkActions;
                  afterSheet(() => void removeLink(link));
                }}
              />
            </ListSection>
          </View>
        ) : null}
      </BottomSheet>

      <LinkEditorSheet
        editor={editor}
        onClose={() => setEditor(null)}
        onSaved={(message) => {
          setEditor(null);
          showToast(message);
          void load();
        }}
      />
    </SafeAreaView>
  );
}

/** Adds a link, or edits one: its address, title, and kind. */
function LinkEditorSheet({
  editor,
  onClose,
  onSaved,
}: {
  editor: LinkEditor | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const editing = editor?.mode === 'edit' ? editor.link : null;
  const [prefilledFor, setPrefilledFor] = useState<LinkEditor | null>(null);
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  // Null while adding: the server guesses the kind from the title and the site.
  const [kind, setKind] = useState<LinkKind | null>(null);
  const [saving, setSaving] = useState(false);

  // Fill the fields when the sheet opens for a link (or empty for a new one).
  if (editor !== prefilledFor) {
    setPrefilledFor(editor);
    if (editor) {
      setUrl(editing?.url ?? '');
      setTitle(editing?.title ?? '');
      setKind(editing?.kind ?? null);
    }
  }

  const save = async () => {
    const address = url.trim();
    if (!address || saving) return;
    setSaving(true);
    try {
      if (editing) {
        const changes: { url?: string; title?: string; kind?: LinkKind } = {};
        if (address !== editing.url) changes.url = address;
        if (title.trim() && title.trim() !== editing.title) changes.title = title.trim();
        if (kind && kind !== editing.kind) changes.kind = kind;
        if (Object.keys(changes).length > 0) {
          await updateLink(editing.id, changes);
        }
        haptic.success();
        onSaved('Link saved');
      } else {
        const saved = await saveLink({ url: address, title: title.trim() || null, kind });
        haptic.success();
        onSaved(
          saved.created
            ? saved.kind === 'resume'
              ? 'Saved as your resume link'
              : 'Link saved'
            : 'This link was already saved; updated it'
        );
      }
    } catch (saveError) {
      haptic.error();
      showToast(getErrorMessage(saveError, 'Could not save the link'), 4000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <BottomSheet
      visible={editor !== null}
      onClose={onClose}
      dismissible={!saving}
      title={editing ? 'Edit Link' : 'New Link'}
      leftAction={{ label: 'Cancel', onPress: onClose }}
      rightAction={{
        label: editing ? 'Save' : 'Add',
        onPress: () => void save(),
        disabled: !url.trim(),
        loading: saving,
      }}
      scrollable>
      <View style={styles.sheetBody}>
        <View style={styles.fieldGroup}>
          <TextInput
            value={url}
            onChangeText={setUrl}
            placeholder="Link, like drive.google.com/…"
            placeholderTextColor={Colors.placeholder}
            style={styles.field}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            textContentType="URL"
            autoFocus={!editing}
            returnKeyType="next"
            accessibilityLabel="Link"
          />
          <View style={styles.fieldSeparator} />
          <TextInput
            value={title}
            onChangeText={setTitle}
            placeholder="Title (optional)"
            placeholderTextColor={Colors.placeholder}
            style={styles.field}
            maxLength={120}
            returnKeyType="done"
            onSubmitEditing={() => void save()}
            accessibilityLabel="Title"
          />
        </View>

        <ListSection
          header="Kind"
          footer={
            editing
              ? 'Marking a link as your resume makes your previous resume link a plain link.'
              : 'Left unset, the kind is guessed from the title and the site.'
          }>
          {LINK_KINDS.map((item) => (
            <ListRow
              key={item.kind}
              title={item.label}
              icon={LINK_LOOK[item.kind].icon}
              iconColor={LINK_LOOK[item.kind].color}
              accessory={kind === item.kind ? 'check' : 'none'}
              onPress={() => {
                haptic.selection();
                setKind(kind === item.kind && !editing ? null : item.kind);
              }}
            />
          ))}
        </ListSection>
      </View>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  content: {
    paddingBottom: 48,
  },
  spinner: {
    marginTop: 32,
  },
  sheetBody: {
    paddingBottom: 8,
  },
  sheetUrl: {
    marginHorizontal: ScreenMargin + 16,
    marginBottom: 12,
    textAlign: 'center',
  },
  fieldGroup: {
    marginHorizontal: ScreenMargin,
    marginBottom: 28,
    borderRadius: 12,
    backgroundColor: Colors.secondaryGroupedBackground,
    overflow: 'hidden',
  },
  field: {
    ...Typography.body,
    minHeight: 48,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: Colors.label,
  },
  fieldSeparator: {
    height: Hairline,
    marginLeft: 16,
    backgroundColor: Colors.separator,
  },
});
