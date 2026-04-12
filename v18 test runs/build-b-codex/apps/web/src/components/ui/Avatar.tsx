import { cn } from '@/lib/classnames';

interface AvatarProps {
  className?: string;
  name: string;
  src?: string | null;
}

function getInitials(name: string): string {
  const segments = name.trim().split(/\s+/).filter(Boolean);

  if (segments.length === 0) {
    return 'SD';
  }

  return segments
    .slice(0, 2)
    .map((segment) => segment[0]?.toUpperCase() ?? '')
    .join('');
}

export function Avatar({ className, name, src }: AvatarProps): JSX.Element {
  return (
    <span className={cn('avatar', className)} aria-label={name}>
      {src ? <img src={src} alt={name} /> : getInitials(name)}
    </span>
  );
}
