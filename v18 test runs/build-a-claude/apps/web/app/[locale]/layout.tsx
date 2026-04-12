import type { ReactNode } from 'react';
import type { Metadata } from 'next';
import { NextIntlClientProvider } from 'next-intl';
import { getMessages } from 'next-intl/server';
import { spaceGrotesk, plusJakarta, jetbrainsMono } from '../../lib/fonts';
import { isRtl, type Locale } from '../../i18n/config';
import { AuthProvider } from '../../lib/auth-context';
import '../globals.css';

export const metadata: Metadata = {
  title: 'TaskFlow',
  description: 'Project and task management',
};

interface Props {
  children: ReactNode;
  params: { locale: string };
}

export default async function LocaleLayout({ children, params: { locale } }: Props) {
  const messages = await getMessages();
  const dir = isRtl(locale as Locale) ? 'rtl' : 'ltr';

  return (
    <html
      lang={locale}
      dir={dir}
      className={`${spaceGrotesk.variable} ${plusJakarta.variable} ${jetbrainsMono.variable}`}
    >
      <body className="min-h-screen bg-surface-50 font-body antialiased">
        <NextIntlClientProvider messages={messages}>
          <AuthProvider>{children}</AuthProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
