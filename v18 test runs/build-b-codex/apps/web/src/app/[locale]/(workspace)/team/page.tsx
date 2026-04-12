'use client';

import { EmptyState } from '@/components/ui/EmptyState';
import { useTranslations } from '@/i18n/use-translations';

export default function TeamPage(): JSX.Element {
  const t = useTranslations();

  return (
    <section className="content-stack">
      <header className="section-header">
        <p className="section-eyebrow">{t('team.eyebrow')}</p>
        <h1 className="section-title">{t('team.title')}</h1>
        <p className="section-description">{t('team.description')}</p>
      </header>

      <div className="grid-panel">
        <EmptyState
          eyebrowKey="team.eyebrow"
          titleKey="team.emptyTitle"
          descriptionKey="team.emptyBody"
        />

        <section className="surface-card list-card">
          <div className="list-card__item">
            <div>
              <p className="list-card__item-title">{t('nav.team')}</p>
              <p className="list-card__item-body">{t('common.comingSoon')}</p>
            </div>
          </div>
          <div className="list-card__item">
            <div>
              <p className="list-card__item-title">{t('shell.language')}</p>
              <p className="list-card__item-body">{t('shell.subtitle')}</p>
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}
