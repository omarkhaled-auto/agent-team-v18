import { Injectable, NotFoundException, Optional } from '@nestjs/common';
import { TaskStatus } from '@prisma/client';
import { CurrentUserPayload } from '../common/decorators/current-user.decorator';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { EventsService } from '../events/events.service';
import { CreateTaskDto } from './dto/create-task.dto';
import { TaskQueryDto } from './dto/task-query.dto';
import { TaskDeleteResponseDto, TaskDetailResponseDto, TaskResponseDto } from './dto/task-response.dto';
import { TransitionStatusDto } from './dto/transition-status.dto';
import { UpdateTaskDto } from './dto/update-task.dto';
import { validateTransition } from './task-state-machine';
import { TasksRepository } from './tasks.repository';

@Injectable()
export class TasksService {
  constructor(
    private readonly tasksRepository: TasksRepository,
    @Optional() private readonly eventsService?: EventsService,
  ) {}

  async findAllByProject(projectId: string, query: TaskQueryDto): Promise<PaginatedResponseDto<TaskResponseDto>> {
    const status = await this.tasksRepository.findProjectStatus(projectId);
    if (!status) {
      throw new NotFoundException('Project not found');
    }

    return this.tasksRepository.findManyByProject(projectId, query);
  }

  async create(projectId: string, dto: CreateTaskDto, reporterId: string): Promise<TaskResponseDto> {
    const status = await this.tasksRepository.findProjectStatus(projectId);
    if (!status) {
      throw new NotFoundException('Project not found');
    }

    if (dto.assignee_id && !(await this.tasksRepository.userExists(dto.assignee_id))) {
      throw new NotFoundException('Assignee not found');
    }

    const task = await this.tasksRepository.create(projectId, reporterId, dto);

    await this.eventsService?.publish('task.events', {
      type: 'task.created',
      payload: {
        taskId: task.id,
        projectId,
        reporterId,
      },
    });

    return task;
  }

  async findOne(id: string): Promise<TaskDetailResponseDto> {
    const task = await this.tasksRepository.findDetailById(id);
    if (!task) {
      throw new NotFoundException('Task not found');
    }

    return task;
  }

  async update(id: string, dto: UpdateTaskDto): Promise<TaskResponseDto> {
    const state = await this.tasksRepository.findStateContextById(id);
    if (!state) {
      throw new NotFoundException('Task not found');
    }

    if (dto.assignee_id && !(await this.tasksRepository.userExists(dto.assignee_id))) {
      throw new NotFoundException('Assignee not found');
    }

    return this.tasksRepository.update(id, dto);
  }

  async transitionStatus(id: string, dto: TransitionStatusDto, user: CurrentUserPayload): Promise<TaskResponseDto> {
    const task = await this.tasksRepository.findStateContextById(id);
    if (!task) {
      throw new NotFoundException('Task not found');
    }

    validateTransition(task.status, dto.status, task, user);
    const updatedTask = await this.tasksRepository.updateStatus(id, dto.status as TaskStatus);

    await this.eventsService?.publish('task.events', {
      type: 'task.status_changed',
      payload: {
        taskId: id,
        projectId: task.project_id,
        previousStatus: task.status,
        status: dto.status,
      },
    });

    return updatedTask;
  }

  async remove(id: string): Promise<TaskDeleteResponseDto> {
    const state = await this.tasksRepository.findStateContextById(id);
    if (!state) {
      throw new NotFoundException('Task not found');
    }

    return this.tasksRepository.softDelete(id);
  }
}
