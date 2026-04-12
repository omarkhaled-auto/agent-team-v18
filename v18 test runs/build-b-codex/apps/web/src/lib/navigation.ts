import type { Locale } from '@/i18n/locales';
import { defaultLocale, isLocale } from '@/i18n/locales';

export function getLocalizedPath(pathname: string, locale: Locale): string {
  if (!pathname) {
    return `/${locale}`;
  }

  const segments = pathname.split('/');
  const [, maybeLocale, ...rest] = segments;

  if (maybeLocale && isLocale(maybeLocale)) {
    return `/${locale}${rest.length > 0 ? `/${rest.join('/')}` : ''}`;
  }

  const normalizedPathname = pathname.startsWith('/') ? pathname : `/${pathname}`;
  return `/${locale}${normalizedPathname === '/' ? '' : normalizedPathname}`;
}

export function getDefaultLocalizedPath(pathname: string): string {
  return getLocalizedPath(pathname, defaultLocale);
}
