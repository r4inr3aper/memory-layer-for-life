import { fireEvent, render, screen } from '@testing-library/react-native';
import { MemoryEditorModal } from '@/components/memories/MemoryEditorModal';

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock('@hugeicons/react-native', () => ({ HugeiconsIcon: () => null }));
jest.mock('@hugeicons/core-free-icons', () => ({}));
jest.mock('@/lib/api/client', () => ({
  getErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}));

const initial = { content: '', memory_type: 'note', sensitive: false };

describe('MemoryEditorModal', () => {
  it('refuses empty text without calling the save', async () => {
    const onSubmit = jest.fn(() => Promise.resolve());
    await render(
      <MemoryEditorModal
        visible
        title="Write a memory"
        confirmText="Save"
        initial={initial}
        onClose={() => {}}
        onSubmit={onSubmit}
      />
    );

    await fireEvent.press(screen.getByText('Save'));

    expect(await screen.findByText('Write what Cooper should remember.')).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('saves the trimmed text with the chosen kind and sensitivity', async () => {
    const onSubmit = jest.fn(() => Promise.resolve());
    await render(
      <MemoryEditorModal
        visible
        title="Write a memory"
        confirmText="Save"
        initial={initial}
        onClose={() => {}}
        onSubmit={onSubmit}
      />
    );

    await fireEvent.changeText(screen.getByLabelText('Memory text'), '  I prefer window seats  ');
    await fireEvent.press(screen.getByText('Preference'));
    await fireEvent(screen.getByLabelText('Sensitive'), 'valueChange', true);
    await fireEvent.press(screen.getByText('Save'));

    await screen.findByText('Save');
    expect(onSubmit).toHaveBeenCalledWith({
      content: 'I prefer window seats',
      memory_type: 'preference',
      sensitive: true,
    });
  });

  it('shows why a save failed and keeps what was typed', async () => {
    const onSubmit = jest.fn(() => Promise.reject(new Error('The server is down')));
    await render(
      <MemoryEditorModal
        visible
        title="Edit memory"
        confirmText="Save"
        initial={{ content: 'Priya lives in Pune', memory_type: 'semantic_fact', sensitive: false }}
        onClose={() => {}}
        onSubmit={onSubmit}
      />
    );

    await fireEvent.press(screen.getByText('Save'));

    expect(await screen.findByText('The server is down')).toBeTruthy();
    expect(screen.getByDisplayValue('Priya lives in Pune')).toBeTruthy();
    // The memory's own kind is offered even though it is a fact.
    expect(screen.getByText('Fact')).toBeTruthy();
  });
});
