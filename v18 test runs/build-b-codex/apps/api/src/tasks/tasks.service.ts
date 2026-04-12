import {
  Injectable,
  NotFoundException,
  BadRequestException,
  Logger,
} from '@nestjs/common';
import { Prisma, TaskStatus } from '@prisma/client';
import { PrismaService } from '../common/prisma/prisma.service';
import { CreateTaskDto } from './dto/create-task.dto';
import { UpdateTaskDto } from './dto/update-task.dto';
import { TaskQueryDto } from './dto/task-query.dto';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { validateTransition, UserContext } from './task-state-machine';

const PRIORITY_ORDER: Record<string, number> = {
  LOW: 0,
  MEDIUM: 1,
  HIGH: 2,
  URGENT: 3,
};

@Injectable()
export class TasksService {
  private readonly logger = new Logger(TasksService.name);

  constructor(private readonly prisma: PrismaService) {}

  async findAllByProject(
    projectId: string,
    query: TaskQueryDto,
  ): Promise<PaginatedResponseDto<Record<string, unknown>>> {
    const project = await this.prisma.project.findFirst({
      where: { id: projectId, deleted_at: null },
      select: { id: true },
    });

    if (!project) {
      throw new NotFoundException('Project not found');
    }

    const { page, limit, status, priority, assignee_id, sort_by, sort_order } = query;
    const skip = (page - 1) * limit;

    const where: Prisma.TaskWhereInput = {
      project_id: projectId,
      deleted_at: null,
      ...(status && { status }),
      ...(priority && { priority }),
      ...(assignee_id && { assignee_id }),
    };

    let orderBy: Prisma.TaskOrderByWithRelationInput;
    const direction = sort_order || 'desc';

    switch (sort_by) {
      case 'due_date':
        orderBy = { due_date: { sort: direction, nulls: 'last' } };
        break;
      case 'priority':
        orderBy = { priority: direction };
        break;
      default:
        orderBy = { created_at: direction };
    }

    const [tasks, total] = await Promise.all([
      this.prisma.task.findMany({
        where,
        skip,
        take: limit,
        orderBy,
        include: {
          assignee: {
            select: { id: true, name: true, email: true, avatar_url: true },
          },
          reporter: {
            select: { id: true, name: true, email: true },
          },
          _count: {
            select: { comments: true },
          },
        },
      }),
      this.prisma.task.count({ where }),
    ]);

    // If sorting by priority, apply numeric ordering in-memory for correct order
    let sortedTasks = tasks;
    if (sort_by === 'priority') {
      sortedTasks = [...tasks].sort((a, b) => {
        const diff = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
        return direction === 'asc' ? diff : -diff;
      });
    }

    const data = sortedTasks.map((task) => ({
      id: task.id,
      title: task.title,
      description: task.description,
      status: task.status,
      priority: task.priority,
      due_date: task.due_date,
      assignee: task.assignee,
      reporter: task.reporter,
      comment_count: task._count.comments,
      created_at: task.created_at,
      updated_at: task.updated_at,
    }));

    return {
      data,
      meta: { total, page, limit },
    };
  }

  async findOne(id: string): Promise<Record<string, unknown>> {
    const task = await this.prisma.task.findFirst({
      where: { id, deleted_at: null },
      include: {
        project: {
          select: { id: true, name: true },
        },
        assignee: {
          select: { id: true, name: true, email: true, avatar_url: true },
        },
        reporter: {
          select: { id: true, name: true, email: true },
        },
        comments: {
          orderBy: { created_at: 'asc' },
          include: {
            author: {
              select: { id: true, name: true, email: true, avatar_url: true },
            },
          },
        },
      },
    });

    if (!task) {
      throw new NotFoundException('Task not found');
    }

    return {
      id: task.id,
      title: task.title,
      description: task.description,
      status: task.status,
      priority: task.priority,
      due_date: task.due_date,
      project: task.project,
      assignee: task.assignee,
      reporter: task.reporter,
      comments: task.comments.map((c) => ({
        id: c.id,
        content: c.content,
        author: c.author,
        created_at: c.created_at,
      })),
      created_at: task.created_at,
      updated_at: task.updated_at,
    };
  }

  async create(
    projectId: string,
    dto: CreateTaskDto,
    reporterId: string,
  ): Promise<Record<string, unknown>> {
    const project = await this.prisma.project.findFirst({
      where: { id: projectId, deleted_at: null },
      select: { id: true },
    });

    if (!project) {
      throw new NotFoundException('Project not found');
    }

    if (dto.assignee_id) {
      const assignee = await this.prisma.user.findUnique({
        where: { id: dto.assignee_id },
        select: { id: true },
      });

      if (!assignee) {
        throw new BadRequestException('Assignee user not found');
      }
    }

    const task = await this.prisma.task.create({
      data: {
        title: dto.title,
        description: dto.description,
        priority: dto.priority || 'MEDIUM',
        due_date: dto.due_date ? new Date(dto.due_date) : null,
        project_id: projectId,
        assignee_id: dto.assignee_id || null,
        reporter_id: reporterId,
      },
      include: {
        assignee: {
          select: { id: true, name: true, email: true, avatar_url: true },
        },
        reporter: {
          select: { id: true, name: true, email: true },
        },
      },
    });

    this.logger.log(`Task created: ${task.id} in project ${projectId}`);

    return {
      id: task.id,
      title: task.title,
      description: task.description,
      status: task.status,
      priority: task.priority,
      due_date: task.due_date,
      assignee: task.assignee,
      reporter: task.reporter,
      comment_count: 0,
      created_at: task.created_at,
      updated_at: task.updated_at,
    };
  }

  async update(id: string, dto: UpdateTaskDto): Promise<Record<string, unknown>> {
    const task = await this.prisma.task.findFirst({
      where: { id, deleted_at: null },
      select: { id: true },
    });

    if (!task) {
      throw new NotFoundException('Task not found');
    }

    if (dto.assignee_id) {
      const assignee = await this.prisma.user.findUnique({
        where: { id: dto.assignee_id },
        select: { id: true },
      });

      if (!assignee) {
        throw new BadRequestException('Assignee user not found');
      }
    }

    const updated = await this.prisma.task.update({
      where: { id },
      data: {
        ...(dto.title !== undefined && { title: dto.title }),
        ...(dto.description !== undefined && { description: dto.description }),
        ...(dto.priority !== undefined && { priority: dto.priority }),
        ...(dto.due_date !== undefined && { due_date: dto.due_date ? new Date(dto.due_date) : null }),
        ...(dto.assignee_id !== undefined && { assignee_id: dto.assignee_id }),
      },
      include: {
        assignee: {
          select: { id: true, name: true, email: true, avatar_url: true },
        },
        reporter: {
          select: { id: true, name: true, email: true },
        },
        _count: {
          select: { comments: true },
        },
      },
    });

    this.logger.log(`Task updated: ${id}`);

    return {
      id: updated.id,
      title: updated.title,
      description: updated.description,
      status: updated.status,
      priority: updated.priority,
      due_date: updated.due_date,
      assignee: updated.assignee,
      reporter: updated.reporter,
      comment_count: updated._count.comments,
      created_at: updated.created_at,
      updated_at: updated.updated_at,
    };
  }

  async transitionStatus(
    id: string,
    newStatus: TaskStatus,
    user: UserContext,
  ): Promise<Record<string, unknown>> {
    const task = await this.prisma.task.findFirst({
      where: { id, deleted_at: null },
      select: {
        id: true,
        status: true,
        assignee_id: true,
        reporter_id: true,
      },
    });

    if (!task) {
      throw new NotFoundException('Task not found');
    }

    validateTransition(
      task.status as 'TODO' | 'IN_PROGRESS' | 'IN_REVIEW' | 'DONE',
      newStatus as 'TODO' | 'IN_PROGRESS' | 'IN_REVIEW' | 'DONE',
      { assignee_id: task.assignee_id, reporter_id: task.reporter_id },
      user,
    );

    const updated = await this.prisma.task.update({
      where: { id },
      data: { status: newStatus },
      include: {
        assignee: {
          select: { id: true, name: true, email: true, avatar_url: true },
        },
        reporter: {
          select: { id: true, name: true, email: true },
        },
        _count: {
          select: { comments: true },
        },
      },
    });

    this.logger.log(`Task ${id} transitioned from ${task.status} to ${newStatus}`);

    return {
      id: updated.id,
      title: updated.title,
      description: updated.description,
      status: updated.status,
      priority: updated.priority,
      due_date: updated.due_date,
      assignee: updated.assignee,
      reporter: updated.reporter,
      comment_count: updated._count.comments,
      created_at: updated.created_at,
      updated_at: updated.updated_at,
    };
  }

  async softDelete(id: string): Promise<{ message: string }> {
    const task = await this.prisma.task.findFirst({
      where: { id, deleted_at: null },
      select: { id: true },
    });

    if (!task) {
      throw new NotFoundException('Task not found');
    }

    await this.prisma.task.update({
      where: { id },
      data: { deleted_at: new Date() },
    });

    this.logger.log(`Task soft-deleted: ${id}`);

    return { message: 'Task deleted successfully' };
  }
}
