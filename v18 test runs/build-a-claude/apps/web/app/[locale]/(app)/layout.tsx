'use client';

import type { ReactNode } from 'react';
import { useAuth } from '../../../lib/auth-context';
import { useRouter } from '../../../i18n/navigation';
import { Sidebar } from '../../../components/layout/sidebar';
import { Topbar } from '../../../components/layout/topbar';
import { useEffect } from 'react';

/**
 * Authenticated app shell.
 * Redirects to /login if user is not authenticated (after loading finishes).
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center" aria-busy="true">
        <div className="flex flex-col items-center gap-md">
          <div className="w-10 h-10 border-4 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
          <p className="text-body text-surface-500">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 p-lg md:p-xl overflow-auto">{children}</main>
      </div>
    </div>
  );
}
