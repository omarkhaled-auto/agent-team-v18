'use client';

import { useCallback, useState, type FormEvent } from 'react';
import { useTranslations } from 'next-intl';
import { useAuth } from '../../lib/auth-context';
import { useRouter } from '../../i18n/navigation';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { ApiRequestError } from '@project/api-client';
import { Link } from '../../i18n/navigation';

export function RegisterForm() {
  const t = useTranslations('auth');
  const { register } = useAuth();
  const router = useRouter();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [fieldErrors, setFieldErrors] = useState<{
    name?: string;
    email?: string;
    password?: string;
  }>({});

  const validate = useCallback((): boolean => {
    const errors: { name?: string; email?: string; password?: string } = {};

    if (!name.trim()) {
      errors.name = t('nameRequired');
    }

    if (!email.trim()) {
      errors.email = t('emailRequired');
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      errors.email = t('emailInvalid');
    }

    if (!password || password.length < 8) {
      errors.password = t('passwordMinLength');
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }, [name, email, password, t]);

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      setError(null);

      if (!validate()) return;

      setIsSubmitting(true);
      try {
        await register(email.trim(), name.trim(), password);
        router.push('/dashboard');
      } catch (err) {
        if (err instanceof ApiRequestError && err.status === 409) {
          setError(t('emailTaken'));
        } else {
          setError(t('registrationFailed'));
        }
      } finally {
        setIsSubmitting(false);
      }
    },
    [name, email, password, register, router, validate, t],
  );

  return (
    <div>
      <header className="mb-2xl text-center">
        <h1 className="font-heading text-display text-surface-900">{t('registerHeading')}</h1>
        <p className="mt-sm text-body-lg text-surface-500">{t('registerSubheading')}</p>
      </header>

      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-lg">
        {error && (
          <div className="rounded bg-danger-50 border border-danger-500/20 px-md py-sm text-body text-danger-700" role="alert">
            {error}
          </div>
        )}

        <Input
          label={t('name')}
          type="text"
          autoComplete="name"
          placeholder={t('namePlaceholder')}
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={fieldErrors.name}
          required
        />

        <Input
          label={t('email')}
          type="email"
          autoComplete="email"
          placeholder={t('emailPlaceholder')}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fieldErrors.email}
          required
        />

        <Input
          label={t('password')}
          type="password"
          autoComplete="new-password"
          placeholder={t('passwordPlaceholder')}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors.password}
          hint={t('passwordMinLength')}
          required
        />

        <Button type="submit" loading={isSubmitting} className="w-full mt-sm">
          {t('register')}
        </Button>
      </form>

      <p className="mt-lg text-center text-body text-surface-500">
        {t('hasAccount')}{' '}
        <Link href="/login" className="font-semibold text-brand-600 hover:text-brand-700 underline-offset-2 hover:underline">
          {t('login')}
        </Link>
      </p>
    </div>
  );
}
