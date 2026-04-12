'use client';

import { useTranslations } from 'next-intl';
import { Link, usePathname } from '../../i18n/navigation';
import { cn } from '../../lib/utils';

const navItems = [
  {
    key: 'dashboard' as const,
    href: '/dashboard' as const,
    icon: DashboardIcon,
  },
] as const;

export function Sidebar() {
  const t = useTranslations('nav');
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex flex-col w-[220px] bg-surface-900 text-surface-300 shrink-0">
      {/* Brand */}
      <div className="flex items-center gap-sm px-lg h-16 border-b border-surface-800">
        <div className="w-8 h-8 rounded bg-brand-500 flex items-center justify-center">
          <span className="text-white font-heading font-bold text-caption">TF</span>
        </div>
        <span className="font-heading font-bold text-body-lg text-surface-0">TaskFlow</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-sm py-lg" aria-label="Main navigation">
        <ul className="flex flex-col gap-xs" role="list">
          {navItems.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <li key={item.key}>
                <Link
                  href={item.href}
                  className={cn(
                    'flex items-center gap-sm px-sm py-2 rounded text-body transition-colors duration-150',
                    isActive
                      ? 'bg-surface-800 text-surface-0 font-semibold'
                      : 'hover:bg-surface-800/50 hover:text-surface-100',
                  )}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <item.icon className="w-5 h-5 shrink-0" aria-hidden="true" />
                  <span>{t(item.key)}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}

/* Inline icons — keeps the component self-contained without an icon library */
function DashboardIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
      <path d="M3 4a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm8 0a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V4zM3 12a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H4a1 1 0 01-1-1v-4zm8 0a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
    </svg>
  );
}
