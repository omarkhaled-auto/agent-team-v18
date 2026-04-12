import { arMessages } from '@/i18n/messages/ar';
import { enMessages } from '@/i18n/messages/en';
import { idMessages } from '@/i18n/messages/id';
import type { MessageDictionary } from '@/i18n/messages/types';
import type { Locale } from '@/i18n/locales';

export function getMessages(locale: Locale): MessageDictionary {
  switch (locale) {
    case 'ar':
      return arMessages;
    case 'id':
      return idMessages;
    case 'en':
    default:
      return enMessages;
  }
}
