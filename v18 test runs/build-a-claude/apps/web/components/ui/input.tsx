'use client';

import { forwardRef, type InputHTMLAttributes, useId } from 'react';
import { cn } from '../../lib/utils';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className, id: externalId, ...props }, ref) => {
    const generatedId = useId();
    const id = externalId || generatedId;
    const errorId = `${id}-error`;
    const hintId = `${id}-hint`;

    return (
      <div className="flex flex-col gap-1.5">
        <label htmlFor={id} className="text-caption font-semibold text-surface-700">
          {label}
          {props.required && <span className="text-danger-500 ms-0.5" aria-hidden="true">*</span>}
        </label>
        <input
          ref={ref}
          id={id}
          className={cn(
            'input-base',
            error && 'border-danger-500 focus:border-danger-500 focus:ring-danger-500/20',
            className,
          )}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? errorId : hint ? hintId : undefined}
          {...props}
        />
        {error && (
          <p id={errorId} className="text-caption text-danger-600" role="alert">
            {error}
          </p>
        )}
        {hint && !error && (
          <p id={hintId} className="text-caption text-surface-500">
            {hint}
          </p>
        )}
      </div>
    );
  },
);

Input.displayName = 'Input';
export { Input };
