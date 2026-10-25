import { fireEvent, render, screen } from '@testing-library/react-native';
import { TodoEditorModal } from '@/components/tasks/TodoEditorModal';
import { createMemory } from '@/lib/api/memories';

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock('@hugeicons/react-native', () => ({ HugeiconsIcon: () => null }));
jest.mock('@hugeicons/core-free-icons', () => ({}));
jest.mock('@react-native-community/datetimepicker', () => () => null);
jest.mock('@/lib/api/client', () => ({
  getErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}));
jest.mock('@/lib/api/memories', () => ({
  createMemory: jest.fn(async (body: { content: string }) => ({ id: 'm1', ...body })),
}));

const create = createMemory as jest.MockedFunction<typeof createMemory>;

describe('TodoEditorModal', () => {
  beforeEach(() => create.mockClear());

  it('asks for something to do before saving', async () => {
    await render(<TodoEditorModal visible onClose={() => {}} onSaved={() => {}} />);

    await fireEvent.press(screen.getByText('Add'));

    expect(await screen.findByText('Write what to do.')).toBeTruthy();
    expect(create).not.toHaveBeenCalled();
  });

  it('saves a to-do due tomorrow without a reminder', async () => {
    const onSaved = jest.fn();
    await render(<TodoEditorModal visible onClose={() => {}} onSaved={onSaved} />);

    await fireEvent.changeText(screen.getByLabelText('What to do'), ' Renew the passport ');
    await fireEvent.press(screen.getByText('Tomorrow'));
    await fireEvent.press(screen.getByText('Add'));

    await screen.findByText('Add');
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    const due = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, '0')}-${String(tomorrow.getDate()).padStart(2, '0')}`;
    expect(create).toHaveBeenCalledWith({
      memory_type: 'task',
      content: 'Renew the passport',
      due_on: due,
      remind_at: null,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('saves a goal with no date', async () => {
    await render(<TodoEditorModal visible onClose={() => {}} onSaved={() => {}} />);

    await fireEvent.changeText(screen.getByLabelText('What to do'), 'Run a marathon');
    await fireEvent.press(screen.getByText('Goal'));
    await fireEvent.press(screen.getByText('Add'));

    await screen.findByText('Add');
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ memory_type: 'goal', due_on: null, remind_at: null })
    );
  });
});
