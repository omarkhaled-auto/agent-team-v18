'use client';

import type { ReactNode } from 'react';

import type { MessageDictionary } from '@/i18n/messages/types';
import type { Locale } from '@/i18n/locales';
import { I18nProvider } from '@/i18n/provider';
import { AuthProvider } from '@/lib/auth-context';

interface AppProvidersProps {
  children: ReactNode;
  locale: Locale;
  messages: MessageDictionary;
}

export function AppProviders({ children, locale, messages }: AppProvidersProps): JSX.Element {
  return (
    <I18nProvider locale={locale} messages={messages}>
      <AuthProvider>{children}</AuthProvider>
    </I18nProvider>
  );
}
