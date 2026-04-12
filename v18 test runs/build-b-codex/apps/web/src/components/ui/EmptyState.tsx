import type { ReactNode } from 'react';

import type { TranslationKey } from '@/i18n/messages/types';
import { useTranslations } from '@/i18n/use-translations';

interface EmptyStateProps {
  action?: ReactNode;
  descriptionKey: TranslationKey;
  eyebrowKey?: TranslationKey;
  titleKey: TranslationKey;
}

export function EmptyState({
  action,
  descriptionKey,
  eyebrowKey,
  titleKey,
}: EmptyStateProps): JSX.Element {
  const t = useTranslations();

  return (
    <section className="empty-state">
      {eyebrowKey ? <p className="section-eyebrow">{t(eyebrowKey)}</p> : null}
      <h2 className="empty-state__title">{t(titleKey)}</h2>
      <p className="empty-state__description">{t(descriptionKey)}</p>
      {action}
    </section>
  );
}
