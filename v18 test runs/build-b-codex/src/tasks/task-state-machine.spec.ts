import { BadRequestException, ForbiddenException } from '@nestjs/common';
import { validateTransition } from './task-state-machine';

describe('validateTransition', () => {
  it('allows TODO to IN_PROGRESS for the assignee', () => {
    expect(() =>
      validateTransition(
        'TODO',
        'IN_PROGRESS',
        { status: 'TODO', project_id: 'project-1', assignee_id: 'user-1', reporter_id: 'user-2' },
        { id: 'user-1', role: 'MEMBER' },
      ),
    ).not.toThrow();
  });

  it('allows IN_PROGRESS to IN_REVIEW for an admin', () => {
    expect(() =>
      validateTransition(
        'IN_PROGRESS',
        'IN_REVIEW',
        { status: 'IN_PROGRESS', project_id: 'project-1', assignee_id: 'user-1', reporter_id: 'user-2' },
        { id: 'admin', role: 'ADMIN' },
      ),
    ).not.toThrow();
  });

  it('allows IN_REVIEW to DONE for the reporter', () => {
    expect(() =>
      validateTransition(
        'IN_REVIEW',
        'DONE',
        { status: 'IN_REVIEW', project_id: 'project-1', assignee_id: 'user-1', reporter_id: 'user-2' },
        { id: 'user-2', role: 'MEMBER' },
      ),
    ).not.toThrow();
  });

  it('allows DONE to TODO for admin', () => {
    expect(() =>
      validateTransition(
        'DONE',
        'TODO',
        { status: 'DONE', project_id: 'project-1', assignee_id: 'user-1', reporter_id: 'user-2' },
        { id: 'admin', role: 'ADMIN' },
      ),
    ).not.toThrow();
  });

  it('rejects invalid transitions with details', () => {
    try {
      validateTransition(
        'TODO',
        'DONE',
        { status: 'TODO', project_id: 'project-1', assignee_id: 'user-1', reporter_id: 'user-2' },
        { id: 'user-1', role: 'MEMBER' },
      );
      fail('expected validation error');
    } catch (error) {
      expect(error).toBeInstanceOf(BadRequestException);
      expect((error as BadRequestException).getResponse()).toEqual({
        code: 'BAD_REQUEST',
        message: 'Invalid status transition from TODO to DONE',
        details: {
          current: 'TODO',
          requested: 'DONE',
          allowed: ['IN_PROGRESS'],
        },
      });
    }
  });

  it('rejects assignee-only transitions for non-assignees', () => {
    expect(() =>
      validateTransition(
        'TODO',
        'IN_PROGRESS',
        { status: 'TODO', project_id: 'project-1', assignee_id: 'user-1', reporter_id: 'user-2' },
        { id: 'user-3', role: 'MEMBER' },
      ),
    ).toThrow(ForbiddenException);
  });

  it('rejects reporter-only transitions for non-reporters', () => {
    expect(() =>
      validateTransition(
        'IN_REVIEW',
        'DONE',
        { status: 'IN_REVIEW', project_id: 'project-1', assignee_id: 'user-1', reporter_id: 'user-2' },
        { id: 'user-1', role: 'MEMBER' },
      ),
    ).toThrow(ForbiddenException);
  });
});
