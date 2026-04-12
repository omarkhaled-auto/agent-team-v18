import type { InputHTMLAttributes } from 'react';

import { cn } from '@/lib/classnames';

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  className?: string;
  error?: string;
  hint?: string;
  label: string;
}

export function Input({ className, error, hint, id, label, required, ...props }: InputProps): JSX.Element {
  return (
    <label className="field" htmlFor={id}>
      <span className="field__label">
        {label}
        {required ? <span className="field__required">*</span> : null}
      </span>
      <input
        {...props}
        id={id}
        required={required}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cn('field__control', className)}
      />
      {error ? (
        <p className="field__error" id={`${id}-error`} role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="field__hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
    </label>
  );
}
