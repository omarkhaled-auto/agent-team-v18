'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { LanguageSwitcher } from '@/components/layout/LanguageSwitcher';
import { useLocale } from '@/i18n/provider';
import { useTranslations } from '@/i18n/use-translations';
import { useAuth } from '@/lib/auth-context';

interface HeaderProps {
  isMenuOpen: boolean;
  onMenuToggle: () => void;
}

function getRoleTranslationKey(role: string): 'shell.roleAdmin' | 'shell.roleMember' | null {
  if (role === 'ADMIN') {
    return 'shell.roleAdmin';
  }

  if (role === 'MEMBER') {
    return 'shell.roleMember';
  }

  return null;
}

export function Header({ isMenuOpen, onMenuToggle }: HeaderProps): JSX.Element {
  const locale = useLocale();
  const router = useRouter();
  const t = useTranslations();
  const { session, logout } = useAuth();
  const roleKey = session ? getRoleTranslationKey(session.user.role) : null;

  const handleLogout = (): void => {
    logout();
    router.push(`/${locale}/login`);
  };

  return (
    <header className="header">
      <div className="header__intro">
        <p className="section-eyebrow">{t('shell.eyebrow')}</p>
        <h1 className="header__title">{t('shell.title')}</h1>
        <p className="header__subtitle">{t('shell.subtitle')}</p>
      </div>

      <div className="header__actions">
        <button
          type="button"
          className="icon-button"
          aria-label={isMenuOpen ? t('common.closeMenu') : t('common.openMenu')}
          onClick={onMenuToggle}
        >
          {isMenuOpen ? 'X' : '|||'}
        </button>

        <LanguageSwitcher />

        {session ? (
          <details className="profile-menu">
            <summary className="profile-menu__summary" aria-label={t('shell.userMenu')}>
              <Avatar name={session.user.name} />
              <span className="profile-menu__meta">
                <span className="profile-menu__name">{session.user.name}</span>
                <span className="profile-menu__role">
                  {roleKey ? t(roleKey) : session.user.role}
                </span>
              </span>
            </summary>

            <div className="profile-menu__panel">
              <div>
                <p className="list-card__item-title">{session.user.email}</p>
                <p className="list-card__item-body">
                  {roleKey ? t(roleKey) : session.user.role}
                </p>
              </div>
              <Button type="button" variant="ghost" onClick={handleLogout}>
                {t('shell.logout')}
              </Button>
            </div>
          </details>
        ) : (
          <>
            <Badge variant="warning">{t('common.previewMode')}</Badge>
            <Link href={`/${locale}/login`} className="button button--secondary">
              {t('nav.login')}
            </Link>
          </>
        )}
      </div>
    </header>
  );
}
