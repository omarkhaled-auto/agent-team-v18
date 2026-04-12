import type { Metadata } from 'next';
import { headers } from 'next/headers';
import type { ReactNode } from 'react';

import { defaultLocale, getDirection, isLocale, localeHeader } from '@/i18n/locales';

import './globals.css';

export const metadata: Metadata = {
  title: 'Signal Desk',
  description: 'Task and project workspace scaffold',
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps): JSX.Element {
  const requestedLocale = headers().get(localeHeader);
  const locale = requestedLocale && isLocale(requestedLocale) ? requestedLocale : defaultLocale;

  return (
    <html lang={locale} dir={getDirection(locale)}>
      <body>{children}</body>
    </html>
  );
}
