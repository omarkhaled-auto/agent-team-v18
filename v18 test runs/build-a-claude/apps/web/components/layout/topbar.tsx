'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter, usePathname } from '../../i18n/navigation';
import { useAuth } from '../../lib/auth-context';
import { locales, localeNames, type Locale } from '../../i18n/config';
import { cn } from '../../lib/utils';

export function Topbar() {
  const t = useTranslations();
  const { user, logout, isAuthenticated } = useAuth();
  const locale = useLocale() as Locale;
  const router = useRouter();
  const pathname = usePathname();

  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showLangMenu, setShowLangMenu] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const langMenuRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
      if (langMenuRef.current && !langMenuRef.current.contains(e.target as Node)) {
        setShowLangMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleLocaleSwitch = useCallback(
    (newLocale: Locale) => {
      setShowLangMenu(false);
      router.replace(pathname, { locale: newLocale });
    },
    [router, pathname],
  );

  const handleLogout = useCallback(() => {
    setShowUserMenu(false);
    logout();
    router.push('/login');
  }, [logout, router]);

  return (
    <header className="h-16 bg-surface-0 border-b border-surface-200 flex items-center justify-end px-lg gap-md">
      {/* Language switcher */}
      <div className="relative" ref={langMenuRef}>
        <button
          type="button"
          className="btn-ghost h-9 px-sm text-caption"
          onClick={() => setShowLangMenu((v) => !v)}
          aria-haspopup="listbox"
          aria-expanded={showLangMenu}
          aria-label={t('locale.switchLanguage')}
        >
          <GlobeIcon className="w-4 h-4" />
          <span className="hidden sm:inline ms-1">{localeNames[locale]}</span>
        </button>

        {showLangMenu && (
          <ul
            role="listbox"
            aria-label={t('locale.switchLanguage')}
            className="absolute end-0 top-full mt-1 w-44 bg-surface-0 border border-surface-200 rounded shadow-elevated z-50 py-1"
          >
            {locales.map((loc) => (
              <li key={loc} role="option" aria-selected={loc === locale}>
                <button
                  type="button"
                  className={cn(
                    'w-full text-start px-md py-2 text-body transition-colors',
                    loc === locale
                      ? 'bg-brand-50 text-brand-700 font-semibold'
                      : 'hover:bg-surface-50 text-surface-700',
                  )}
                  onClick={() => handleLocaleSwitch(loc)}
                >
                  {localeNames[loc]}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* User menu */}
      {isAuthenticated && user && (
        <div className="relative" ref={userMenuRef}>
          <button
            type="button"
            className="flex items-center gap-sm btn-ghost h-9 px-sm"
            onClick={() => setShowUserMenu((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={showUserMenu}
          >
            <div className="w-7 h-7 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-caption font-bold">
              {user.name.charAt(0).toUpperCase()}
            </div>
            <span className="hidden sm:inline text-body text-surface-700">{user.name}</span>
          </button>

          {showUserMenu && (
            <div
              role="menu"
              className="absolute end-0 top-full mt-1 w-48 bg-surface-0 border border-surface-200 rounded shadow-elevated z-50 py-1"
            >
              <div className="px-md py-2 border-b border-surface-100">
                <p className="text-body font-semibold text-surface-900 truncate">{user.name}</p>
                <p className="text-caption text-surface-500 truncate">{user.email}</p>
              </div>
              <button
                type="button"
                role="menuitem"
                className="w-full text-start px-md py-2 text-body text-danger-600 hover:bg-danger-50 transition-colors"
                onClick={handleLogout}
              >
                {t('auth.logout')}
              </button>
            </div>
          )}
        </div>
      )}
    </header>
  );
}

function GlobeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
      <path
        fillRule="evenodd"
        d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
        clipRule="evenodd"
      />
    </svg>
  );
}
