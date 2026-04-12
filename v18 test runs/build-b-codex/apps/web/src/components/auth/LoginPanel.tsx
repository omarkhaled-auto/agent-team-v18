'use client';

import type { ChangeEvent, FormEvent } from 'react';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { useLocale } from '@/i18n/provider';
import { useTranslations } from '@/i18n/use-translations';
import { AuthClientUnavailableError } from '@/lib/auth';
import { useAuth } from '@/lib/auth-context';

interface LoginValues {
  email: string;
  password: string;
}

type LoginErrors = Partial<Record<keyof LoginValues, string>>;

const initialValues: LoginValues = {
  email: '',
  password: '',
};

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function validate(values: LoginValues, t: ReturnType<typeof useTranslations>): LoginErrors {
  const errors: LoginErrors = {};

  if (!values.email.trim()) {
    errors.email = t('errors.required');
  } else if (!isValidEmail(values.email.trim())) {
    errors.email = t('errors.email');
  } else if (values.email.trim().length > 254) {
    errors.email = t('errors.maxLength');
  }

  if (!values.password) {
    errors.password = t('errors.required');
  } else if (values.password.length < 8) {
    errors.password = t('errors.minLength');
  } else if (values.password.length > 128) {
    errors.password = t('errors.maxLength');
  }

  return errors;
}

export function LoginPanel(): JSX.Element {
  const t = useTranslations();
  const locale = useLocale();
  const router = useRouter();
  const { login, session, isHydrating } = useAuth();
  const [values, setValues] = useState<LoginValues>(initialValues);
  const [errors, setErrors] = useState<LoginErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!isHydrating && session) {
      router.replace(`/${locale}/projects`);
    }
  }, [isHydrating, locale, router, session]);

  const handleChange =
    (field: keyof LoginValues) =>
    (event: ChangeEvent<HTMLInputElement>): void => {
      const nextValues = {
        ...values,
        [field]: event.target.value,
      };

      setValues(nextValues);
      if (errors[field]) {
        setErrors(validate(nextValues, t));
      }
      if (submitError) {
        setSubmitError(null);
      }
    };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();

    const nextErrors = validate(values, t);
    setErrors(nextErrors);
    setSubmitError(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setIsSubmitting(true);

    try {
      await login({
        email: values.email.trim(),
        password: values.password,
      });
      router.replace(`/${locale}/projects`);
    } catch (error) {
      if (error instanceof AuthClientUnavailableError) {
        setSubmitError(t('errors.clientUnavailable'));
      } else {
        setSubmitError(t('auth.login.invalid'));
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="page-shell page-shell--auth">
      <div className="auth-grid">
        <section className="auth-aside" aria-labelledby="login-title">
          <p className="auth-aside__eyebrow">{t('auth.login.eyebrow')}</p>
          <h1 className="auth-aside__title" id="login-title">
            {t('auth.login.title')}
          </h1>
          <p className="auth-aside__description">{t('auth.login.description')}</p>

          <div className="auth-aside__metrics">
            <article className="metric-card">
              <p className="metric-card__label">{t('nav.projects')}</p>
              <p className="metric-card__value">04</p>
            </article>
            <article className="metric-card">
              <p className="metric-card__label">{t('nav.team')}</p>
              <p className="metric-card__value">16</p>
            </article>
            <article className="metric-card">
              <p className="metric-card__label">{t('shell.language')}</p>
              <p className="metric-card__value">03</p>
            </article>
          </div>
        </section>

        <section className="surface-card" aria-labelledby="login-form-title">
          <p className="section-eyebrow">{t('common.appName')}</p>
          <h2 className="empty-state__title" id="login-form-title">
            {t('common.signIn')}
          </h2>
          <p className="section-description">{t('auth.login.helper')}</p>

          <div className="notice-card" role="status" aria-live="polite">
            <h3 className="notice-card__title">{t('auth.login.clientGapTitle')}</h3>
            <p className="notice-card__body">{t('auth.login.clientGapBody')}</p>
          </div>

          <form className="form-stack" onSubmit={handleSubmit} noValidate>
            <Input
              id="email"
              name="email"
              type="email"
              label={t('auth.login.email')}
              value={values.email}
              onChange={handleChange('email')}
              error={errors.email}
              autoComplete="email"
              maxLength={254}
              required
            />
            <Input
              id="password"
              name="password"
              type="password"
              label={t('auth.login.password')}
              value={values.password}
              onChange={handleChange('password')}
              error={errors.password}
              autoComplete="current-password"
              maxLength={128}
              required
            />

            {submitError ? (
              <p className="field__error" role="alert">
                {submitError}
              </p>
            ) : null}

            <Button type="submit" isLoading={isSubmitting} size="lg">
              {t('auth.login.submit')}
            </Button>
          </form>
        </section>
      </div>
    </main>
  );
}
