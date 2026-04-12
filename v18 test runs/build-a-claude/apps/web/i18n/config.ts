export const locales = ['en', 'ar', 'id'] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = 'en';

export const rtlLocales: Locale[] = ['ar'];

export function isRtl(locale: Locale): boolean {
  return rtlLocales.includes(locale);
}

export const localeNames: Record<Locale, string> = {
  en: 'English',
  ar: '\u0627\u0644\u0639\u0631\u0628\u064A\u0629',
  id: 'Bahasa Indonesia',
};
