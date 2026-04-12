import type { ReactNode } from 'react';

/**
 * Root layout — bare shell. The locale layout at [locale]/layout.tsx
 * handles fonts, providers, and dir/lang attributes.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
