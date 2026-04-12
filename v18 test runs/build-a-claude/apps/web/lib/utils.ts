/**
 * Merge class names, filtering out falsy values.
 * Lightweight alternative to clsx/classnames.
 */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

/**
 * Format a date string to a locale-aware display format.
 */
export function formatDate(dateStr: string, locale: string = 'en'): string {
  const date = new Date(dateStr);
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(date);
}

/**
 * Format a relative time (e.g. "2 hours ago").
 */
export function formatRelativeTime(dateStr: string, locale: string = 'en'): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });

  if (diffDay > 0) return rtf.format(-diffDay, 'day');
  if (diffHour > 0) return rtf.format(-diffHour, 'hour');
  if (diffMin > 0) return rtf.format(-diffMin, 'minute');
  return rtf.format(-diffSec, 'second');
}
