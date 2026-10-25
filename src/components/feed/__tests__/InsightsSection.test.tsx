import { fireEvent, render, screen } from '@testing-library/react-native';
import { InsightsSection } from '@/components/feed/InsightsSection';
import { listInsights, sendInsightFeedback } from '@/lib/api/insights';
import type { Insight } from '@/lib/api/types';

const mockPush = jest.fn();

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, navigate: jest.fn() }),
  // Runs the callback once, as the screen coming into focus would.
  useFocusEffect: (callback: () => void | (() => void)) =>
    jest.requireActual<typeof import('react')>('react').useEffect(callback, [callback]),
}));
jest.mock('@hugeicons/react-native', () => ({ HugeiconsIcon: () => null }));
jest.mock('@hugeicons/core-free-icons', () => ({}));
jest.mock('@/context/ToastContext', () => ({ showToast: jest.fn() }));
jest.mock('@/lib/api/client', () => ({
  getErrorMessage: (_error: unknown, fallback: string) => fallback,
  isAbortError: () => false,
}));
jest.mock('@/lib/api/insights', () => ({
  listInsights: jest.fn(),
  sendInsightFeedback: jest.fn(async () => undefined),
}));

const INSIGHTS: Insight[] = [
  {
    key: 'people.quiet:p1:2026-10',
    kind: 'people.quiet',
    title: "You haven't mentioned Mum in 7 weeks",
    body: 'Mum came up in 3 memories before that.',
    memory_ids: ['m1', 'm2', 'm3'],
    target: 'person',
    target_id: 'p1',
  },
  {
    key: 'money:2026-10:INR',
    kind: 'money',
    title: 'INR 1,250 noted this month',
    body: '3 money notes this month.',
    memory_ids: ['m4'],
    target: 'memories',
    target_id: null,
  },
];

describe('InsightsSection', () => {
  beforeEach(() => {
    mockPush.mockClear();
    (listInsights as jest.Mock).mockResolvedValue(INSIGHTS);
  });

  it('shows each insight with what it rests on, and opens what it is about', async () => {
    await render(<InsightsSection />);

    expect(await screen.findByText("You haven't mentioned Mum in 7 weeks")).toBeTruthy();
    expect(screen.getByText('Based on 3 memories')).toBeTruthy();
    expect(screen.getByText('Based on 1 memory')).toBeTruthy();

    await fireEvent.press(screen.getByText("You haven't mentioned Mum in 7 weeks"));
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/people/[id]', params: { id: 'p1' } });
  });

  it('hides an insight marked not useful and thanks for a useful one', async () => {
    await render(<InsightsSection />);
    await screen.findByText('INR 1,250 noted this month');

    await fireEvent.press(screen.getAllByLabelText('Not useful, hide it')[1]);
    await fireEvent.press(screen.getByLabelText('Useful'));

    expect(screen.queryByText('INR 1,250 noted this month')).toBeNull();
    expect(screen.getByText('Thanks')).toBeTruthy();
    expect(sendInsightFeedback).toHaveBeenCalledWith('money:2026-10:INR', 'money', false);
    expect(sendInsightFeedback).toHaveBeenCalledWith(
      'people.quiet:p1:2026-10',
      'people.quiet',
      true
    );
  });

  it('shows nothing when the memories say nothing yet', async () => {
    (listInsights as jest.Mock).mockResolvedValue([]);
    await render(<InsightsSection />);

    expect(screen.queryByText('For you')).toBeNull();
  });
});
