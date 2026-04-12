'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import type { TranslationKey } from '@/i18n/messages/types';
import { useLocale } from '@/i18n/provider';
import { useTranslations } from '@/i18n/use-translations';
import { cn } from '@/lib/classnames';

interface SidebarProps {
  onClose: () => void;
}

const navigationItems: Array<{ href: string; labelKey: TranslationKey }> = [
  { href: '/projects', labelKey: 'nav.projects' },
  { href: '/team', labelKey: 'nav.team' },
];

export function Sidebar({ onClose }: SidebarProps): JSX.Element {
  const pathname = usePathname();
  const locale = useLocale();
  const t = useTranslations();

  return (
    <div className="sidebar">
      <div className="sidebar__brand">
        <button
          type="button"
          className="sidebar__close icon-button"
          onClick={onClose}
          aria-label={t('common.closeMenu')}
        >
          X
        </button>
        <p className="sidebar__eyebrow">{t('common.appName')}</p>
        <h2 className="sidebar__title">{t('shell.title')}</h2>
        <p className="sidebar__description">{t('shell.subtitle')}</p>
      </div>

      <nav className="sidebar__nav" aria-label={t('shell.title')}>
        {navigationItems.map((item) => {
          const href = `/${locale}${item.href}`;
          const isActive = pathname === href;

          return (
            <Link
              key={item.href}
              href={href}
              className={cn('sidebar__link', isActive && 'sidebar__link--active')}
              onClick={onClose}
            >
              <span>{t(item.labelKey)}</span>
              <span>{isActive ? '•' : ''}</span>
            </Link>
          );
        })}
      </nav>

      <div className="sidebar__footer">
        <span>{t('common.previewMode')}</span>
        <span>{t('auth.login.clientGapBody')}</span>
      </div>
    </div>
  );
}
