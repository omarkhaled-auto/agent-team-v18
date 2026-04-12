'use client';

import type { ReactNode } from 'react';
import { useEffect, useRef } from 'react';

import { useTranslations } from '@/i18n/use-translations';

interface ModalProps {
  children: ReactNode;
  description?: string;
  footer?: ReactNode;
  isOpen: boolean;
  onClose: () => void;
  title: string;
}

export function Modal({
  children,
  description,
  footer,
  isOpen,
  onClose,
  title,
}: ModalProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const t = useTranslations();

  useEffect(() => {
    const dialog = dialogRef.current;

    if (!dialog) {
      return;
    }

    if (isOpen && !dialog.open) {
      dialog.showModal();
    }

    if (!isOpen && dialog.open) {
      dialog.close();
    }
  }, [isOpen]);

  useEffect(() => {
    const dialog = dialogRef.current;

    if (!dialog) {
      return;
    }

    const handleCancel = (event: Event): void => {
      event.preventDefault();
      onClose();
    };

    const handleClick = (event: MouseEvent): void => {
      if (event.target instanceof HTMLDialogElement) {
        onClose();
      }
    };

    dialog.addEventListener('cancel', handleCancel);
    dialog.addEventListener('click', handleClick);

    return () => {
      dialog.removeEventListener('cancel', handleCancel);
      dialog.removeEventListener('click', handleClick);
    };
  }, [onClose]);

  if (!isOpen) {
    return null;
  }

  return (
    <dialog className="modal" ref={dialogRef} aria-modal="true">
      <div className="modal__surface">
        <div className="modal__header">
          <div>
            <h2 className="empty-state__title">{title}</h2>
            {description ? <p className="section-description">{description}</p> : null}
          </div>
          <button type="button" className="modal__close" onClick={onClose} aria-label={t('common.close')}>
            X
          </button>
        </div>
        <div>{children}</div>
        {footer ? <div className="modal__footer">{footer}</div> : null}
      </div>
    </dialog>
  );
}
