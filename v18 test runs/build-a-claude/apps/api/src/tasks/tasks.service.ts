import {
  Injectable,
  NotFoundException,
  BadRequestException,
  Logger,
} from '@nestjs/common';
import { TaskRepository } from '../repositories/task.repository';
import { ProjectRepository } from '../repositories/project.repository';
import { UserRepository } from '../repositories/user.repository';
import { EventsService } from '../events/events.service';
import { CreateTaskDto } from './dto/create-task.dto';
import { UpdateTaskDto } from './dto/update-task.dto';
import { UpdateTaskStatusDto } from './dto/update-task-status.dto';
import { TaskQueryDto } from './dto/task-query.dto';
import { PaginatedResponseDto } from '../common/dto/paginated-response.dto';
import { TaskStatus, Prisma } from '@prisma/client';

/**
 * Valid task status transitions (state machine).
 * Key = current status, Value = set of allowed next statuses.
 */
const STATUS_TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  [TaskStatus.TODO]: [TaskStatus.IN_PROGRESS],
  [TaskStatus.IN_PROGRESS]: [TaskStatus.IN_REVIEW, TaskStatus.TODO],
  [TaskStatus.IN_REVIEW]: [TaskStatus.DONE, TaskStatus.IN_PROGRESS],
  [TaskStatus.DONE]: [TaskStatus.IN_PROGRESS],
};

@Injectable()
export class TasksService {
  private readonly logger = new Logger(TasksService.name);

  constructor(
    private readonly taskRepository: TaskRepository,
    private readonly projectRepository: ProjectRepository,
    private readonly userRepository: UserRepository,
    private readonly eventsService: EventsService,
  ) {}

  async findAllByProject(projectId: string, query: TaskQueryDto) {
    const { page = 1, limit = 20, status, priority, assigneeId, sortBy = 'created_at', sortOrder = 'desc' } = query;

    // Verify project exists
    const project = await this.projectRepository.findById(projectId);
    if (!project) {
      throw new NotFoundException('Project not found');
    }

    const skip = (page - 1) * limit;

    const where: Prisma.TaskWhereInput = { projectId };
    if (status) {
      where.status = status;
    }
    if (priority) {
      where.priority = priority;
    }
    if (assigneeId) {
      where.assigneeId = assigneeId;
    }

    // Map sort field names to Prisma column names
    const sortFieldMap: Record<string, string> = {
      due_date: 'dueDate',
      priority: 'priority',
      created_at: 'createdAt',
    };
    const orderByField = sortFieldMap[sortBy] || 'createdAt';
    const orderBy: Prisma.TaskOrderByWithRelationInput = { [orderByField]: sortOrder };

    const [tasks, total] = await Promise.all([
      this.taskRepository.findAll({
        skip,
        take: limit,
        where,
        orderBy,
      }),
      this.taskRepository.count(where),
    ]);

    return new PaginatedResponseDto(tasks, total, page, limit);
  }

  async findById(id: string) {
    const task = await this.taskRepository.findById(id);
    if (!task) {
      throw new NotFoundException('Task not found');
    }
    return task;
  }

  async create(projectId: string, dto: CreateTaskDto, reporterId: string) {
    // Verify project exists
    const project = await this.projectRepository.findById(projectId);
    if (!project) {
      throw new NotFoundException('Project not found');
    }

    // Validate assignee exists if provided
    if (dto.assigneeId) {
      const assignee = await this.userRepository.findById(dto.assigneeId);
      if (!assignee) {
        throw new BadRequestException('Assignee not found');
      }
    }

    const task = await this.taskRepository.create({
      title: dto.title,
      description: dto.description,
      priority: dto.priority,
      dueDate: dto.dueDate ? new Date(dto.dueDate) : undefined,
      project: { connect: { id: projectId } },
      reporter: { connect: { id: reporterId } },
      ...(dto.assigneeId && { assignee: { connect: { id: dto.assigneeId } } }),
    });

    this.logger.log(`Task created: ${task.id} in project ${projectId}`);
    await this.eventsService.publish('task.created', {
      taskId: task.id,
      projectId,
      reporterId,
    });

    return task;
  }

  async update(id: string, dto: UpdateTaskDto) {
    const task = await this.taskRepository.findById(id);
    if (!task) {
      throw new NotFoundException('Task not found');
    }

    // Validate assignee exists if provided
    if (dto.assigneeId) {
      const assignee = await this.userRepository.findById(dto.assigneeId);
      if (!assignee) {
        throw new BadRequestException('Assignee not found');
      }
    }

    const updated = await this.taskRepository.update(id, {
      ...(dto.title !== undefined && { title: dto.title }),
      ...(dto.description !== undefined && { description: dto.description }),
      ...(dto.priority !== undefined && { priority: dto.priority }),
      ...(dto.dueDate !== undefined && { dueDate: new Date(dto.dueDate) }),
      ...(dto.assigneeId !== undefined && { assignee: { connect: { id: dto.assigneeId } } }),
    });

    this.logger.log(`Task updated: ${id}`);
    await this.eventsService.publish('task.updated', { taskId: id });

    return updated;
  }

  async transitionStatus(id: string, dto: UpdateTaskStatusDto) {
    const task = await this.taskRepository.findById(id);
    if (!task) {
      throw new NotFoundException('Task not found');
    }

    const currentStatus = task.status;
    const newStatus = dto.status;

    const allowedTransitions = STATUS_TRANSITIONS[currentStatus];
    if (!allowedTransitions.includes(newStatus)) {
      throw new BadRequestException(
        `Invalid status transition: ${currentStatus} → ${newStatus}. ` +
        `Allowed transitions from ${currentStatus}: ${allowedTransitions.join(', ')}`,
      );
    }

    const updated = await this.taskRepository.update(id, { status: newStatus });

    this.logger.log(`Task ${id} status transitioned: ${currentStatus} → ${newStatus}`);
    await this.eventsService.publish('task.status_changed', {
      taskId: id,
      from: currentStatus,
      to: newStatus,
    });

    return updated;
  }

  async softDelete(id: string) {
    const task = await this.taskRepository.findById(id);
    if (!task) {
      throw new NotFoundException('Task not found');
    }

    // Prisma middleware converts delete to soft-delete
    await this.taskRepository.update(id, {
      deletedAt: new Date(),
    });

    this.logger.log(`Task soft-deleted: ${id}`);
    await this.eventsService.publish('task.deleted', { taskId: id });
  }
}
