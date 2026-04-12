import type { ReactNode } from 'react';

/**
 * Auth layout — centered single-column for login/register pages.
 * No sidebar, no topbar.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-md py-3xl">
      <div className="w-full max-w-[420px]">{children}</div>
    </main>
  );
}
