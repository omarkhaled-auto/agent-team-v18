import { BadRequestException, ForbiddenException } from '@nestjs/common';

/**
 * Task status transition state machine.
 *
 * Valid transitions:
 *   TODO → IN_PROGRESS        (assignee or admin)
 *   IN_PROGRESS → IN_REVIEW   (assignee or admin)
 *   IN_REVIEW → DONE          (reporter or admin)
 *   IN_REVIEW → IN_PROGRESS   (reporter or admin — rejection)
 *   DONE → TODO               (admin only — reopen)
 */

type TaskStatus = 'TODO' | 'IN_PROGRESS' | 'IN_REVIEW' | 'DONE';
type RoleCheck = 'assignee_or_admin' | 'reporter_or_admin' | 'admin_only';

interface TransitionRule {
  to: TaskStatus;
  allowedBy: RoleCheck;
}

const TRANSITIONS: Record<TaskStatus, TransitionRule[]> = {
  TODO: [
    { to: 'IN_PROGRESS', allowedBy: 'assignee_or_admin' },
  ],
  IN_PROGRESS: [
    { to: 'IN_REVIEW', allowedBy: 'assignee_or_admin' },
  ],
  IN_REVIEW: [
    { to: 'DONE', allowedBy: 'reporter_or_admin' },
    { to: 'IN_PROGRESS', allowedBy: 'reporter_or_admin' },
  ],
  DONE: [
    { to: 'TODO', allowedBy: 'admin_only' },
  ],
};

export interface TaskContext {
  assignee_id: string | null;
  reporter_id: string;
}

export interface UserContext {
  id: string;
  role: string;
}

export function validateTransition(
  currentStatus: TaskStatus,
  newStatus: TaskStatus,
  task: TaskContext,
  user: UserContext,
): void {
  const allowedTransitions = TRANSITIONS[currentStatus];

  if (!allowedTransitions) {
    throw new BadRequestException(`Unknown task status: ${currentStatus}`);
  }

  const rule = allowedTransitions.find((t) => t.to === newStatus);

  if (!rule) {
    const validTargets = allowedTransitions.map((t) => t.to).join(', ');
    throw new BadRequestException(
      `Invalid status transition from ${currentStatus} to ${newStatus}. Allowed transitions: ${validTargets || 'none'}`,
    );
  }

  const isAdmin = user.role === 'ADMIN';
  const isAssignee = task.assignee_id === user.id;
  const isReporter = task.reporter_id === user.id;

  let authorized = false;

  switch (rule.allowedBy) {
    case 'assignee_or_admin':
      authorized = isAssignee || isAdmin;
      break;
    case 'reporter_or_admin':
      authorized = isReporter || isAdmin;
      break;
    case 'admin_only':
      authorized = isAdmin;
      break;
  }

  if (!authorized) {
    throw new ForbiddenException(
      `You are not authorized to transition this task from ${currentStatus} to ${newStatus}`,
    );
  }
}
