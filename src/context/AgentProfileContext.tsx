/**
 * Agent Profile Context
 *
 * The assistant's name, subtitle, avatar icon, and color, as saved on the backend (`/me`).
 * Loads once the user is signed in and falls back to the defaults (Cooper) until then,
 * when signed out, and for anything the user never changed.
 */

import { Colors } from '@/constants/colors';
import { DEFAULT_AGENT_ICON, isAgentIconKey } from '@/constants/agentIcons';
import { isAbortError } from '@/lib/api/client';
import { getMe, updateMe } from '@/lib/api/me';
import type { Me, UpdateMeBody } from '@/lib/api/types';
import { supabase } from '@/lib/supabase';
import type { AgentProfile } from '@/types';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

export const DEFAULT_AGENT_PROFILE: AgentProfile = {
  name: 'Cooper',
  subtitle: 'Autonomous Agent',
  icon: DEFAULT_AGENT_ICON,
  color: Colors.primary,
};

/** Limits enforced by the backend. */
export const AGENT_NAME_MAX_LENGTH = 40;
export const AGENT_SUBTITLE_MAX_LENGTH = 60;

const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/;

interface AgentProfileContextValue {
  profile: AgentProfile;
  /** Whether the saved profile has been loaded for the signed-in user. */
  isLoaded: boolean;
  /** Saves the given fields. Rejects with an `ApiError` when the server refuses them. */
  saveProfile: (changes: Partial<AgentProfile>) => Promise<void>;
}

const AgentProfileContext = createContext<AgentProfileContextValue>({
  profile: DEFAULT_AGENT_PROFILE,
  isLoaded: false,
  saveProfile: async () => {},
});

export function AgentProfileProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<AgentProfile>(DEFAULT_AGENT_PROFILE);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    let userId: string | null = null;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const load = () => {
      controller?.abort();
      const request = new AbortController();
      controller = request;
      getMe(request.signal)
        .then((me) => {
          setProfile(profileFromMe(me));
          setIsLoaded(true);
        })
        .catch((error) => {
          if (isAbortError(error, request.signal)) return;
          // Keep the defaults; the header still works and saving still updates the server.
          console.warn('[agentProfile] Could not load the agent profile:', error);
        });
    };

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      const nextUserId = session?.user.id ?? null;
      if (nextUserId === userId) return;
      userId = nextUserId;

      if (timer) clearTimeout(timer);
      if (nextUserId) {
        // Supabase asks not to call its methods (the API client reads the session) from
        // inside this callback, so the request starts right after it returns.
        timer = setTimeout(load, 0);
      } else {
        controller?.abort();
        setProfile(DEFAULT_AGENT_PROFILE);
        setIsLoaded(false);
      }
    });

    return () => {
      subscription.unsubscribe();
      if (timer) clearTimeout(timer);
      controller?.abort();
    };
  }, []);

  const saveProfile = useCallback(async (changes: Partial<AgentProfile>) => {
    const body = toUpdateBody(changes);
    if (Object.keys(body).length === 0) return;
    const me = await updateMe(body);
    setProfile(profileFromMe(me));
    setIsLoaded(true);
  }, []);

  const value = useMemo(
    () => ({ profile, isLoaded, saveProfile }),
    [profile, isLoaded, saveProfile]
  );

  return <AgentProfileContext.Provider value={value}>{children}</AgentProfileContext.Provider>;
}

export function useAgentProfile(): AgentProfileContextValue {
  return useContext(AgentProfileContext);
}

/** The profile a `/me` response describes, with defaults for unset or unknown values. */
export function profileFromMe(me: Me): AgentProfile {
  return {
    name: me.assistant_name?.trim() || DEFAULT_AGENT_PROFILE.name,
    subtitle: me.assistant_subtitle?.trim() || DEFAULT_AGENT_PROFILE.subtitle,
    icon: isAgentIconKey(me.assistant_icon) ? me.assistant_icon : DEFAULT_AGENT_PROFILE.icon,
    color:
      me.assistant_color && HEX_COLOR.test(me.assistant_color)
        ? me.assistant_color
        : DEFAULT_AGENT_PROFILE.color,
  };
}

/** Only the given fields are sent; an empty name or subtitle resets it to the default. */
function toUpdateBody(changes: Partial<AgentProfile>): UpdateMeBody {
  const body: UpdateMeBody = {};
  if (changes.name !== undefined) {
    body.assistant_name = changes.name.trim().slice(0, AGENT_NAME_MAX_LENGTH) || null;
  }
  if (changes.subtitle !== undefined) {
    body.assistant_subtitle = changes.subtitle.trim().slice(0, AGENT_SUBTITLE_MAX_LENGTH) || null;
  }
  if (changes.icon !== undefined) {
    body.assistant_icon = isAgentIconKey(changes.icon) ? changes.icon : DEFAULT_AGENT_ICON;
  }
  if (changes.color !== undefined) {
    body.assistant_color = HEX_COLOR.test(changes.color) ? changes.color : null;
  }
  return body;
}
