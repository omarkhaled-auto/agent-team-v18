import { Injectable } from '@nestjs/common';
import { Prisma, TaskPriority, TaskStatus } from '@prisma/client';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { PrismaService } from '../common/prisma/prisma.service';
import { mapComment, mapTask, mapTaskDetail } from '../common/utils/response-mappers';
import { CreateTaskDto } from './dto/create-task.dto';
import { TaskQueryDto } from './dto/task-query.dto';
import { TaskDeleteResponseDto, TaskDetailResponseDto, TaskResponseDto } from './dto/task-response.dto';
import { UpdateTaskDto } from './dto/update-task.dto';
import { TaskStateContext } from './task-state-machine';

const userSummarySelect = {
  id: true,
  name: true,
  avatar_url: true,
} as const;

@Injectable()
export class TasksRepository {
  constructor(private readonly prisma: PrismaService) {}

  async findProjectStatus(projectId: string): Promise<'ACTIVE' | 'ARCHIVED' | null> {
    const project = await this.prisma.project.findUnique({
      where: { id: projectId },
      select: { status: true },
    });

    return project?.status ?? null;
  }

  async userExists(userId: string): Promise<boolean> {
    const user = await this.prisma.user.findUnique({ where: { id: userId }, select: { id: true } });
    return Boolean(user);
  }

  async findManyByProject(projectId: string, query: TaskQueryDto): Promise<PaginatedResponseDto<TaskResponseDto>> {
    const page = query.page;
    const limit = query.limit;
    const skip = (page - 1) * limit;
    const order = query.order ?? 'desc';
    const where: Prisma.TaskWhereInput = {
      project_id: projectId,
      ...(query.status ? { status: query.status } : {}),
      ...(query.priority ? { priority: query.priority } : {}),
      ...(query.assignee_id ? { assignee_id: query.assignee_id } : {}),
    };

    const orderBy: Prisma.TaskOrderByWithRelationInput =
      query.sort === 'due_date'
        ? { due_date: { sort: order, nulls: 'last' } }
        : query.sort === 'priority'
          ? { priority: order }
          : { created_at: order };

    const [tasks, total] = await Promise.all([
      this.prisma.task.findMany({
        where,
        skip,
        take: limit,
        orderBy,
        include: {
          assignee: { select: userSummarySelect },
          reporter: { select: userSummarySelect },
        },
      }),
      this.prisma.task.count({ where }),
    ]);

    return {
      data: tasks.map((task) => mapTask(task)),
      meta: { total, page, limit },
    };
  }

  async findDetailById(id: string): Promise<TaskDetailResponseDto | null> {
    const task = await this.prisma.task.findFirst({
      where: { id },
      include: {
        assignee: { select: userSummarySelect },
        reporter: { select: userSummarySelect },
        comments: {
          orderBy: { created_at: 'asc' },
          include: {
            author: { select: userSummarySelect },
          },
        },
      },
    });

    return task ? mapTaskDetail(task, task.comments.map((comment) => mapComment(comment))) : null;
  }

  async findStateContextById(id: string): Promise<TaskStateContext | null> {
    return this.prisma.task.findFirst({
      where: { id },
      select: {
        status: true,
        project_id: true,
        assignee_id: true,
        reporter_id: true,
      },
    }) as Promise<TaskStateContext | null>;
  }

  async create(projectId: string, reporterId: string, dto: CreateTaskDto): Promise<TaskResponseDto> {
    const task = await this.prisma.task.create({
      data: {
        title: dto.title,
        description: dto.description ?? null,
        priority: dto.priority ?? TaskPriority.MEDIUM,
        due_date: dto.due_date ? new Date(dto.due_date) : null,
        project_id: projectId,
        assignee_id: dto.assignee_id ?? null,
        reporter_id: reporterId,
      },
      include: {
        assignee: { select: userSummarySelect },
        reporter: { select: userSummarySelect },
      },
    });

    return mapTask(task);
  }

  async update(id: string, dto: UpdateTaskDto): Promise<TaskResponseDto> {
    const data: Prisma.TaskUncheckedUpdateInput = {};

    if ('title' in dto && dto.title !== undefined) {
      data.title = dto.title;
    }
    if ('description' in dto) {
      data.description = dto.description ?? null;
    }
    if ('priority' in dto && dto.priority !== undefined) {
      data.priority = dto.priority;
    }
    if ('due_date' in dto) {
      data.due_date = dto.due_date ? new Date(dto.due_date) : null;
    }
    if ('assignee_id' in dto) {
      data.assignee_id = dto.assignee_id ?? null;
    }

    const task = await this.prisma.task.update({
      where: { id },
      data,
      include: {
        assignee: { select: userSummarySelect },
        reporter: { select: userSummarySelect },
      },
    });

    return mapTask(task);
  }

  async updateStatus(id: string, status: TaskStatus): Promise<TaskResponseDto> {
    const task = await this.prisma.task.update({
      where: { id },
      data: { status },
      include: {
        assignee: { select: userSummarySelect },
        reporter: { select: userSummarySelect },
      },
    });

    return mapTask(task);
  }

  async softDelete(id: string): Promise<TaskDeleteResponseDto> {
    const task = await this.prisma.task.update({
      where: { id },
      data: { deleted_at: new Date() },
      select: { id: true },
    });

    return { id: task.id, deleted: true };
  }
}
