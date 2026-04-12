import type { TranslationKey } from '@/i18n/messages/types';
import { useI18n } from '@/i18n/provider';

function resolveTranslation(messages: unknown, key: string): string {
  const parts = key.split('.');
  let current: unknown = messages;

  for (const part of parts) {
    if (!current || typeof current !== 'object' || !(part in current)) {
      return key;
    }

    current = (current as Record<string, unknown>)[part];
  }

  return typeof current === 'string' ? current : key;
}

export function useTranslations(): (key: TranslationKey) => string {
  const { messages } = useI18n();

  return (key: TranslationKey) => resolveTranslation(messages, key);
}
