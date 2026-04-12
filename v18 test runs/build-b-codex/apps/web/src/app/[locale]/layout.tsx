import type { ReactNode } from 'react';
import { notFound } from 'next/navigation';

import { AppProviders } from '@/components/providers/AppProviders';
import { getMessages } from '@/i18n/get-messages';
import type { Locale } from '@/i18n/locales';
import { isLocale } from '@/i18n/locales';

interface LocaleLayoutProps {
  children: ReactNode;
  params: {
    locale: string;
  };
}

export default function LocaleLayout({ children, params }: LocaleLayoutProps): JSX.Element {
  if (!isLocale(params.locale)) {
    notFound();
  }

  const locale: Locale = params.locale;
  const messages = getMessages(locale);

  return (
    <AppProviders locale={locale} messages={messages}>
      {children}
    </AppProviders>
  );
}
