'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { useLocale } from '@/i18n/provider';
import { localeLabels, locales } from '@/i18n/locales';
import { useTranslations } from '@/i18n/use-translations';
import { cn } from '@/lib/classnames';
import { getLocalizedPath } from '@/lib/navigation';

export function LanguageSwitcher(): JSX.Element {
  const pathname = usePathname();
  const currentLocale = useLocale();
  const t = useTranslations();

  return (
    <nav className="language-switcher" aria-label={t('shell.language')}>
      {locales.map((locale) => (
        <Link
          key={locale}
          href={getLocalizedPath(pathname, locale)}
          className={cn(
            'language-switcher__link',
            currentLocale === locale && 'language-switcher__link--active',
          )}
          locale={false}
        >
          {localeLabels[locale]}
        </Link>
      ))}
    </nav>
  );
}
