'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { projects as projectsApi, type ProjectListResponse } from '@project/api-client';
import type { Project, ProjectStatus } from '@project/api-client';
import { useAuth } from '../../../../lib/auth-context';
import { apiOptions } from '../../../../lib/api';
import { Button } from '../../../../components/ui/button';
import { Card, CardTitle, CardDescription, CardFooter } from '../../../../components/ui/card';
import { cn, formatDate } from '../../../../lib/utils';
import { useLocale } from 'next-intl';
import { Link } from '../../../../i18n/navigation';

type StatusFilter = 'ALL' | ProjectStatus;

export default function DashboardPage() {
  const t = useTranslations('dashboard');
  const locale = useLocale();
  const { token } = useAuth();

  const [data, setData] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProjects = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const query: Record<string, unknown> = { page, limit: 12 };
      if (statusFilter !== 'ALL') {
        query.status = statusFilter;
      }
      const res = await projectsApi.findAll(
        { query: query as { status?: ProjectStatus; page?: number; limit?: number } },
        apiOptions(token),
      );
      setData(res.data);
      setTotal(res.meta.total);
    } catch {
      setError('Failed to load projects');
    } finally {
      setIsLoading(false);
    }
  }, [token, page, statusFilter]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const statusFilters: { key: StatusFilter; label: string }[] = [
    { key: 'ALL', label: t('allProjects') },
    { key: 'ACTIVE', label: t('active') },
    { key: 'ARCHIVED', label: t('archived') },
  ];

  return (
    <div>
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-md mb-xl">
        <div>
          <h1 className="font-heading text-heading text-surface-900">{t('heading')}</h1>
          <p className="text-body text-surface-500 mt-1">{t('subheading')}</p>
        </div>
        <Button size="md">
          <PlusIcon className="w-4 h-4" />
          {t('createProject')}
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-xs mb-lg" role="tablist" aria-label="Project status filter">
        {statusFilters.map((f) => (
          <button
            key={f.key}
            type="button"
            role="tab"
            aria-selected={statusFilter === f.key}
            className={cn(
              'px-3 py-1.5 rounded text-caption font-medium transition-colors',
              statusFilter === f.key
                ? 'bg-brand-50 text-brand-700'
                : 'text-surface-500 hover:bg-surface-100 hover:text-surface-700',
            )}
            onClick={() => {
              setStatusFilter(f.key);
              setPage(1);
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-md">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card p-md animate-pulse">
              <div className="h-5 bg-surface-200 rounded w-2/3 mb-3" />
              <div className="h-4 bg-surface-100 rounded w-full mb-2" />
              <div className="h-4 bg-surface-100 rounded w-1/2" />
            </div>
          ))}
        </div>
      )}

      {error && !isLoading && (
        <div className="card p-xl text-center">
          <p className="text-body text-danger-600 mb-md">{error}</p>
          <Button variant="secondary" onClick={fetchProjects}>
            Try again
          </Button>
        </div>
      )}

      {!isLoading && !error && data.length === 0 && (
        <div className="card p-3xl text-center">
          <EmptyFolderIcon className="w-16 h-16 mx-auto text-surface-300 mb-lg" />
          <h2 className="font-heading text-subheading text-surface-700">{t('noProjects')}</h2>
          <p className="text-body text-surface-500 mt-sm max-w-sm mx-auto">{t('noProjectsDescription')}</p>
          <Button className="mt-lg">
            <PlusIcon className="w-4 h-4" />
            {t('createProject')}
          </Button>
        </div>
      )}

      {!isLoading && !error && data.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-md">
          {data.map((project) => (
            <ProjectCard key={project.id} project={project} locale={locale} />
          ))}
        </div>
      )}

      {/* Pagination hint */}
      {!isLoading && total > 12 && (
        <div className="flex justify-center gap-sm mt-xl">
          <Button
            variant="secondary"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </Button>
          <span className="flex items-center text-caption text-surface-500 px-sm">
            Page {page} of {Math.ceil(total / 12)}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={page >= Math.ceil(total / 12)}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Sub-components (module-scope, not inside render)                    */
/* ------------------------------------------------------------------ */

function ProjectCard({ project, locale }: { project: Project; locale: string }) {
  const t = useTranslations('dashboard');

  const statusColor = project.status === 'ACTIVE'
    ? 'bg-brand-50 text-brand-700'
    : 'bg-surface-100 text-surface-500';

  return (
    <Card interactive>
      <div className="flex items-start justify-between mb-sm">
        <CardTitle>{project.name}</CardTitle>
        <span className={cn('text-caption font-medium px-2 py-0.5 rounded-full shrink-0', statusColor)}>
          {project.status === 'ACTIVE' ? t('active') : t('archived')}
        </span>
      </div>
      {project.description && (
        <CardDescription>{project.description}</CardDescription>
      )}
      <CardFooter>
        <span className="text-caption text-surface-400">
          {formatDate(project.createdAt, locale)}
        </span>
      </CardFooter>
    </Card>
  );
}

/* Inline icons */
function PlusIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
      <path d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" />
    </svg>
  );
}

function EmptyFolderIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" xmlns="http://www.w3.org/2000/svg">
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
    </svg>
  );
}
