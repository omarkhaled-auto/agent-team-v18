'use client';

import { Button } from '@/components/ui/Button';
import { useTranslations } from '@/i18n/use-translations';

interface LocaleErrorPageProps {
  error: Error;
  reset: () => void;
}

export default function LocaleErrorPage({ error, reset }: LocaleErrorPageProps): JSX.Element {
  const t = useTranslations();

  return (
    <main className="page-shell page-shell--auth">
      <section className="system-card" aria-live="polite">
        <p className="section-eyebrow">{t('common.unavailable')}</p>
        <h1 className="system-card__title">{t('system.errorTitle')}</h1>
        <p className="system-card__body">{t('system.errorBody')}</p>
        <p className="field__hint">{error.message}</p>
        <div className="system-card__actions">
          <Button type="button" onClick={reset}>
            {t('common.retry')}
          </Button>
        </div>
      </section>
    </main>
  );
}
