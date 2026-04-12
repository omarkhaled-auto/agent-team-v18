import { redirect } from 'next/navigation';

/**
 * Locale root — redirect to dashboard.
 * Auth guard is on the (app) layout.
 */
export default function LocaleRoot({ params: { locale } }: { params: { locale: string } }) {
  redirect(`/${locale}/dashboard`);
}
