import { BadRequestException, ForbiddenException } from '@nestjs/common';

export type TaskStatusValue = 'TODO' | 'IN_PROGRESS' | 'IN_REVIEW' | 'DONE';

interface TransitionRule {
  to: TaskStatusValue[];
  allowedBy: 'assignee' | 'reporter' | 'admin';
}

const TRANSITIONS: Record<TaskStatusValue, TransitionRule> = {
  TODO: { to: ['IN_PROGRESS'], allowedBy: 'assignee' },
  IN_PROGRESS: { to: ['IN_REVIEW'], allowedBy: 'assignee' },
  IN_REVIEW: { to: ['DONE', 'IN_PROGRESS'], allowedBy: 'reporter' },
  DONE: { to: ['TODO'], allowedBy: 'admin' },
};

export interface TaskStateContext {
  status: TaskStatusValue;
  project_id: string;
  assignee_id: string | null;
  reporter_id: string;
}

export interface TransitionUserContext {
  id: string;
  role: string;
}

export function validateTransition(
  currentStatus: TaskStatusValue,
  requestedStatus: TaskStatusValue,
  task: TaskStateContext,
  user: TransitionUserContext,
): void {
  const rule = TRANSITIONS[currentStatus];
  if (!rule.to.includes(requestedStatus)) {
    throw new BadRequestException({
      code: 'BAD_REQUEST',
      message: `Invalid status transition from ${currentStatus} to ${requestedStatus}`,
      details: {
        current: currentStatus,
        requested: requestedStatus,
        allowed: rule.to,
      },
    });
  }

  const isAdmin = user.role === 'ADMIN';
  const isAssignee = task.assignee_id === user.id;
  const isReporter = task.reporter_id === user.id;

  const authorized =
    rule.allowedBy === 'admin'
      ? isAdmin
      : rule.allowedBy === 'assignee'
        ? isAdmin || isAssignee
        : isAdmin || isReporter;

  if (!authorized) {
    throw new ForbiddenException('You are not authorized to transition this task');
  }
}
