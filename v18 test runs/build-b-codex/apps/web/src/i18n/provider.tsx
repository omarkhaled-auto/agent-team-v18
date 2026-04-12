'use client';

import { createContext, useContext } from 'react';
import type { ReactNode } from 'react';

import type { MessageDictionary } from '@/i18n/messages/types';
import type { Direction, Locale } from '@/i18n/locales';
import { getDirection } from '@/i18n/locales';

interface I18nContextValue {
  direction: Direction;
  locale: Locale;
  messages: MessageDictionary;
}

const I18nContext = createContext<I18nContextValue | null>(null);

interface I18nProviderProps {
  children: ReactNode;
  locale: Locale;
  messages: MessageDictionary;
}

export function I18nProvider({ children, locale, messages }: I18nProviderProps): JSX.Element {
  return (
    <I18nContext.Provider
      value={{
        direction: getDirection(locale),
        locale,
        messages,
      }}
    >
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);

  if (!context) {
    throw new Error('I18nProvider is required for translated components.');
  }

  return context;
}

export function useLocale(): Locale {
  return useI18n().locale;
}

export function useDirection(): Direction {
  return useI18n().direction;
}
