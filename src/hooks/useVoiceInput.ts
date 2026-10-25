/**
 * useVoiceInput
 *
 * Dictation for the chat input: `toggle()` starts listening in the device's language and
 * reports the transcript (interim results included) until the user stops or pauses.
 */

import { showToast } from '@/context/ToastContext';
import {
  getSpeechLocale,
  loadSpeechRecognition,
  speechUnavailableMessage,
  type SpeechRecognitionModule,
} from '@/lib/speech';
import type { ExpoSpeechRecognitionErrorEvent } from 'expo-speech-recognition';
import { useCallback, useEffect, useRef, useState } from 'react';

interface Subscription {
  remove(): void;
}

export interface VoiceInput {
  isListening: boolean;
  /** Starts listening, or stops when already listening. */
  toggle: () => void;
}

/** `onTranscript` receives the whole transcript of the current session each time it grows. */
export function useVoiceInput(onTranscript: (transcript: string) => void): VoiceInput {
  const [isListening, setIsListening] = useState(false);
  const speechRef = useRef<SpeechRecognitionModule | null>(null);
  const subscriptionsRef = useRef<Subscription[]>([]);
  const isStartingRef = useRef(false);
  const onTranscriptRef = useRef(onTranscript);

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);

  const removeListeners = useCallback(() => {
    subscriptionsRef.current.forEach((subscription) => subscription.remove());
    subscriptionsRef.current = [];
  }, []);

  // Stop listening when the screen goes away.
  useEffect(
    () => () => {
      removeListeners();
      speechRef.current?.abort();
    },
    [removeListeners]
  );

  const start = useCallback(async () => {
    if (isStartingRef.current) return;
    isStartingRef.current = true;

    try {
      const speech = await loadSpeechRecognition();
      if (!speech) {
        showToast(speechUnavailableMessage(), 3500);
        return;
      }

      const permission = await speech.requestPermissionsAsync();
      if (!permission.granted) {
        showToast('Allow microphone and speech recognition access to use voice input.', 3500);
        return;
      }

      removeListeners();
      speechRef.current = speech;
      subscriptionsRef.current = [
        speech.addListener('start', () => setIsListening(true)),
        speech.addListener('result', (event) => {
          const transcript = event.results[0]?.transcript;
          if (transcript) {
            onTranscriptRef.current(transcript);
          }
        }),
        speech.addListener('error', (event) => {
          setIsListening(false);
          const message = errorMessage(event);
          if (message) showToast(message);
        }),
        speech.addListener('end', () => {
          setIsListening(false);
          removeListeners();
        }),
      ];

      setIsListening(true);
      speech.start({ lang: getSpeechLocale(), interimResults: true, continuous: false });
    } catch (error) {
      console.warn('[voice] Could not start speech recognition:', error);
      setIsListening(false);
      removeListeners();
      showToast('Could not start voice input. Please try again.');
    } finally {
      isStartingRef.current = false;
    }
  }, [removeListeners]);

  const toggle = useCallback(() => {
    if (isListening) {
      speechRef.current?.stop();
      setIsListening(false);
    } else {
      void start();
    }
  }, [isListening, start]);

  return { isListening, toggle };
}

function errorMessage(event: ExpoSpeechRecognitionErrorEvent): string | null {
  switch (event.error) {
    case 'aborted':
      return null;
    case 'no-speech':
    case 'speech-timeout':
      return "Didn't catch that. Tap the microphone and try again.";
    case 'not-allowed':
      return 'Allow microphone and speech recognition access to use voice input.';
    case 'network':
      return 'Voice input needs a connection. Check your network and try again.';
    case 'language-not-supported':
      return "Voice input doesn't support your device language yet.";
    default:
      return event.message || 'Voice input stopped unexpectedly.';
  }
}
