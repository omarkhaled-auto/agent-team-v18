'use client';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { useTranslations } from '@/i18n/use-translations';
import { useAuth } from '@/lib/auth-context';

export default function ProjectsPage(): JSX.Element {
  const t = useTranslations();
  const { session } = useAuth();

  return (
    <section className="content-stack">
      <header className="section-header">
        <p className="section-eyebrow">{t('projects.eyebrow')}</p>
        <div className="toolbar">
          <div>
            <h1 className="section-title">{t('projects.title')}</h1>
            <p className="section-description">{t('projects.description')}</p>
          </div>
          <div className="button-row">
            {!session ? <Badge variant="warning">{t('common.previewMode')}</Badge> : null}
            <Button type="button" variant="secondary">
              {t('projects.newProject')}
            </Button>
          </div>
        </div>
      </header>

      <div className="grid-panel">
        <EmptyState
          eyebrowKey="projects.eyebrow"
          titleKey="projects.emptyTitle"
          descriptionKey="projects.emptyBody"
          action={
            <Button type="button" variant="primary">
              {t('projects.newProject')}
            </Button>
          }
        />

        <section className="surface-card list-card">
          <h2 className="empty-state__title">{t('shell.title')}</h2>
          <div className="list-card__item">
            <div>
              <p className="list-card__item-title">{t('shell.sessionReady')}</p>
              <p className="list-card__item-body">
                {session ? session.user.email : t('shell.sessionMissing')}
              </p>
            </div>
            <Badge variant={session ? 'success' : 'warning'}>
              {session ? t('common.signIn') : t('common.previewMode')}
            </Badge>
          </div>
          <div className="list-card__item">
            <div>
              <p className="list-card__item-title">{t('auth.login.clientGapTitle')}</p>
              <p className="list-card__item-body">{t('auth.login.clientGapBody')}</p>
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}
