import type { ReactNode } from 'react';

import { AppShell } from '@/components/layout/AppShell';

interface WorkspaceLayoutProps {
  children: ReactNode;
}

export default function WorkspaceLayout({ children }: WorkspaceLayoutProps): JSX.Element {
  return <AppShell>{children}</AppShell>;
}
