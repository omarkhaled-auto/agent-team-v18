import { UserRole } from '@prisma/client';
import { CommentResponseDto } from '../../comments/dto/comment-response.dto';
import { ProjectDetailResponseDto, ProjectResponseDto, ProjectTaskCountsDto } from '../../projects/dto/project-response.dto';
import { TaskDetailResponseDto, TaskResponseDto } from '../../tasks/dto/task-response.dto';
import { UserDetailResponseDto, UserTaskStatsDto } from '../../users/dto/user-response.dto';
import { UserResponseDto, UserSummaryDto } from '../dto/user.dto';

interface UserSummarySource {
  id: string;
  name: string;
  avatar_url: string | null;
}

interface UserSource extends UserSummarySource {
  email: string;
  role: UserRole;
  created_at: Date;
  updated_at: Date;
}

interface ProjectSource {
  id: string;
  name: string;
  description: string | null;
  status: 'ACTIVE' | 'ARCHIVED';
  owner_id: string;
  owner: UserSummarySource;
  created_at: Date;
  updated_at: Date;
}

interface CommentSource {
  id: string;
  content: string;
  task_id: string;
  author_id: string;
  author: UserSummarySource;
  created_at: Date;
}

interface TaskSource {
  id: string;
  title: string;
  description: string | null;
  status: 'TODO' | 'IN_PROGRESS' | 'IN_REVIEW' | 'DONE';
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT';
  due_date: Date | null;
  project_id: string;
  assignee_id: string | null;
  reporter_id: string;
  assignee: UserSummarySource | null;
  reporter: UserSummarySource;
  created_at: Date;
  updated_at: Date;
}

export function mapUserSummary(user: UserSummarySource): UserSummaryDto {
  return {
    id: user.id,
    name: user.name,
    avatar_url: user.avatar_url,
  };
}

export function mapUser(user: UserSource): UserResponseDto {
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    role: user.role,
    avatar_url: user.avatar_url,
    created_at: formatTimestamp(user.created_at),
    updated_at: formatTimestamp(user.updated_at),
  };
}

export function mapProject(project: ProjectSource): ProjectResponseDto {
  return {
    id: project.id,
    name: project.name,
    description: project.description,
    status: project.status,
    owner_id: project.owner_id,
    owner: mapUserSummary(project.owner),
    created_at: formatTimestamp(project.created_at),
    updated_at: formatTimestamp(project.updated_at),
  };
}

export function mapProjectDetail(project: ProjectSource, taskCounts: ProjectTaskCountsDto): ProjectDetailResponseDto {
  return {
    ...mapProject(project),
    taskCounts,
  };
}

export function mapComment(comment: CommentSource): CommentResponseDto {
  return {
    id: comment.id,
    content: comment.content,
    task_id: comment.task_id,
    author_id: comment.author_id,
    author: mapUserSummary(comment.author),
    created_at: formatTimestamp(comment.created_at),
  };
}

export function mapTask(task: TaskSource): TaskResponseDto {
  return {
    id: task.id,
    title: task.title,
    description: task.description,
    status: task.status,
    priority: task.priority,
    due_date: formatDateOnly(task.due_date),
    project_id: task.project_id,
    assignee_id: task.assignee_id,
    reporter_id: task.reporter_id,
    assignee: task.assignee ? mapUserSummary(task.assignee) : null,
    reporter: mapUserSummary(task.reporter),
    created_at: formatTimestamp(task.created_at),
    updated_at: formatTimestamp(task.updated_at),
  };
}

export function mapTaskDetail(task: TaskSource, comments: CommentResponseDto[]): TaskDetailResponseDto {
  return {
    ...mapTask(task),
    comments,
  };
}

export function mapUserDetail(user: UserSource, taskStats: UserTaskStatsDto): UserDetailResponseDto {
  return {
    ...mapUser(user),
    taskStats,
  };
}

export function emptyProjectTaskCounts(): ProjectTaskCountsDto {
  return {
    todo: 0,
    in_progress: 0,
    in_review: 0,
    done: 0,
    total: 0,
  };
}

export function emptyUserTaskStats(): UserTaskStatsDto {
  return {
    assigned: 0,
    todo: 0,
    in_progress: 0,
    in_review: 0,
    done: 0,
  };
}

export function formatTimestamp(value: Date): string {
  return value.toISOString();
}

export function formatDateOnly(value: Date | null): string | null {
  if (!value) {
    return null;
  }

  const year = value.getUTCFullYear();
  const month = `${value.getUTCMonth() + 1}`.padStart(2, '0');
  const day = `${value.getUTCDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}
