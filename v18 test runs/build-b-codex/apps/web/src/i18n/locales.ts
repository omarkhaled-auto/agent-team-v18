export const locales = ['en', 'ar', 'id'] as const;
export const rtlLocales = ['ar'] as const;
export const defaultLocale = 'en';
export const localeHeader = 'x-signal-desk-locale';

export type Locale = (typeof locales)[number];
export type Direction = 'ltr' | 'rtl';

export const localeLabels: Record<Locale, string> = {
  en: 'EN',
  ar: 'AR',
  id: 'ID',
};

export function isLocale(value: string): value is Locale {
  return locales.some((locale) => locale === value);
}

export function getDirection(locale: Locale): Direction {
  return rtlLocales.some((candidate) => candidate === locale) ? 'rtl' : 'ltr';
}

export function getLocaleFromPath(pathname: string): Locale | null {
  const [, maybeLocale] = pathname.split('/');
  return maybeLocale && isLocale(maybeLocale) ? maybeLocale : null;
}
