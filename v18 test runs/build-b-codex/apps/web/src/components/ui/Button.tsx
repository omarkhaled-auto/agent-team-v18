import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { cn } from '@/lib/classnames';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'destructive';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  className?: string;
  isLoading?: boolean;
  size?: ButtonSize;
  variant?: ButtonVariant;
}

export function Button({
  children,
  className,
  disabled,
  isLoading = false,
  size = 'md',
  type = 'button',
  variant = 'primary',
  ...props
}: ButtonProps): JSX.Element {
  return (
    <button
      {...props}
      type={type}
      disabled={disabled || isLoading}
      aria-busy={isLoading || undefined}
      className={cn('button', `button--${variant}`, `button--${size}`, className)}
    >
      {isLoading ? <LoadingSpinner size="sm" /> : null}
      <span>{children}</span>
    </button>
  );
}
