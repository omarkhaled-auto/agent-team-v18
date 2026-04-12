import type { ReactNode } from 'react';

import { cn } from '@/lib/classnames';

type BadgeVariant = 'accent' | 'success' | 'warning' | 'danger' | 'neutral';

interface BadgeProps {
  children: ReactNode;
  className?: string;
  variant?: BadgeVariant;
}

export function Badge({ children, className, variant = 'neutral' }: BadgeProps): JSX.Element {
  return <span className={cn('badge', `badge--${variant}`, className)}>{children}</span>;
}
