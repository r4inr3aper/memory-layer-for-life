import { Colors } from '@/constants/colors';
import { DEFAULT_AGENT_PROFILE, profileFromMe } from '@/context/AgentProfileContext';
import type { Me } from '@/lib/api/types';

jest.mock('@/lib/supabase', () => ({
  getAccessToken: jest.fn(async () => null),
  supabase: { auth: { getSession: jest.fn(), signOut: jest.fn(), onAuthStateChange: jest.fn() } },
}));

function me(overrides: Partial<Me> = {}): Me {
  return {
    id: 'u1',
    email: 'a@example.com',
    display_name: null,
    assistant_name: null,
    assistant_subtitle: null,
    assistant_icon: null,
    assistant_color: null,
    notifications_enabled: false,
    memory_capture_enabled: true,
    timezone: null,
    brief_enabled: false,
    brief_time: '08:00',
    reminders_enabled: true,
    quiet_hours_start: null,
    quiet_hours_end: null,
    created_at: '2026-10-19T08:00:00Z',
    ...overrides,
  };
}

describe('profileFromMe', () => {
  it('uses the defaults for unset fields', () => {
    expect(profileFromMe(me())).toEqual(DEFAULT_AGENT_PROFILE);
    expect(DEFAULT_AGENT_PROFILE).toMatchObject({ name: 'Cooper', icon: 'cooper' });
  });

  it('uses saved values that are valid', () => {
    expect(
      profileFromMe(
        me({
          assistant_name: ' Nova ',
          assistant_subtitle: 'Research buddy',
          assistant_icon: 'rocket',
          assistant_color: '#059669',
        })
      )
    ).toEqual({ name: 'Nova', subtitle: 'Research buddy', icon: 'rocket', color: '#059669' });
  });

  it('ignores icon keys and colors the app does not know', () => {
    const profile = profileFromMe(me({ assistant_icon: 'unicorn', assistant_color: 'blue' }));
    expect(profile.icon).toBe('cooper');
    expect(profile.color).toBe(Colors.primary);
  });
});
