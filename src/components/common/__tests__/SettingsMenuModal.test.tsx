import { render, screen } from '@testing-library/react-native';
import { SettingsMenuModal } from '@/components/common/SettingsMenuModal';

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock('@hugeicons/react-native', () => ({ HugeiconsIcon: () => null }));
jest.mock('@hugeicons/core-free-icons', () => ({}));

const noop = () => {};

// Testing Library 14 renders asynchronously.
async function renderMenu(props: { showChatActions?: boolean; canDeleteChat?: boolean }) {
  await render(
    <SettingsMenuModal
      visible
      onClose={noop}
      onEditAvatar={noop}
      onRename={noop}
      onClearChat={noop}
      onDeleteChat={noop}
      onShareChat={noop}
      {...props}
    />
  );
}

describe('SettingsMenuModal', () => {
  it('offers only the agent items when no chat is on screen', async () => {
    await renderMenu({ showChatActions: false, canDeleteChat: true });

    expect(await screen.findByText('Edit Mascot & Avatar')).toBeTruthy();
    expect(screen.getByText('Rename Agent')).toBeTruthy();
    expect(screen.queryByText('Share Chat')).toBeNull();
    expect(screen.queryByText('Clear Messages')).toBeNull();
    expect(screen.queryByText('Delete Chat')).toBeNull();
  });

  it('offers the chat actions while a chat is open', async () => {
    await renderMenu({ showChatActions: true, canDeleteChat: false });

    expect(await screen.findByText('Share Chat')).toBeTruthy();
    expect(screen.getByText('Clear Messages')).toBeTruthy();
    // The main chat can only be cleared.
    expect(screen.queryByText('Delete Chat')).toBeNull();
  });

  it('offers Delete for a side chat', async () => {
    await renderMenu({ showChatActions: true, canDeleteChat: true });

    expect(await screen.findByText('Delete Chat')).toBeTruthy();
  });
});
