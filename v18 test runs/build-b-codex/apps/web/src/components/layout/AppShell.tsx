'use client';

import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';

import { Header } from '@/components/layout/Header';
import { Sidebar } from '@/components/layout/Sidebar';
import { useTranslations } from '@/i18n/use-translations';

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps): JSX.Element {
  const pathname = usePathname();
  const t = useTranslations();
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  useEffect(() => {
    setIsMenuOpen(false);
  }, [pathname]);

  return (
    <div className="shell">
      {isMenuOpen ? (
        <button
          type="button"
          className="shell__backdrop"
          onClick={() => setIsMenuOpen(false)}
          aria-label={t('common.closeMenu')}
        />
      ) : null}

      <aside className="shell__sidebar" data-open={isMenuOpen}>
        <Sidebar onClose={() => setIsMenuOpen(false)} />
      </aside>

      <div className="shell__content">
        <Header isMenuOpen={isMenuOpen} onMenuToggle={() => setIsMenuOpen((current) => !current)} />
        {children}
      </div>
    </div>
  );
}
