import { cn } from '@/lib/classnames';

type SpinnerSize = 'sm' | 'md' | 'lg';

interface LoadingSpinnerProps {
  className?: string;
  size?: SpinnerSize;
}

export function LoadingSpinner({ className, size = 'md' }: LoadingSpinnerProps): JSX.Element {
  return <span className={cn('spinner', size !== 'md' && `spinner--${size}`, className)} aria-hidden="true" />;
}
