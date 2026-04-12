import {
  Injectable,
  NotFoundException,
  ForbiddenException,
  Logger,
} from '@nestjs/common';
import { ProjectRepository } from '../repositories/project.repository';
import { TaskRepository } from '../repositories/task.repository';
import { EventsService } from '../events/events.service';
import { CreateProjectDto } from './dto/create-project.dto';
import { UpdateProjectDto } from './dto/update-project.dto';
import { ProjectQueryDto } from './dto/project-query.dto';
import { PaginatedResponseDto } from '../common/dto/paginated-response.dto';
import { ProjectStatus, Prisma } from '@prisma/client';

@Injectable()
export class ProjectsService {
  private readonly logger = new Logger(ProjectsService.name);

  constructor(
    private readonly projectRepository: ProjectRepository,
    private readonly taskRepository: TaskRepository,
    private readonly eventsService: EventsService,
  ) {}

  async findAll(query: ProjectQueryDto) {
    const { page = 1, limit = 20, status } = query;
    const skip = (page - 1) * limit;

    const where: Prisma.ProjectWhereInput = {};
    if (status) {
      where.status = status;
    }

    const [projects, total] = await Promise.all([
      this.projectRepository.findAll({
        skip,
        take: limit,
        where,
        orderBy: { createdAt: 'desc' },
      }),
      this.projectRepository.count(where),
    ]);

    return new PaginatedResponseDto(projects, total, page, limit);
  }

  async findById(id: string) {
    const project = await this.projectRepository.findById(id);
    if (!project) {
      throw new NotFoundException('Project not found');
    }

    // Get task count summary grouped by status
    const taskCounts = await Promise.all([
      this.taskRepository.count({ projectId: id, status: 'TODO' }),
      this.taskRepository.count({ projectId: id, status: 'IN_PROGRESS' }),
      this.taskRepository.count({ projectId: id, status: 'IN_REVIEW' }),
      this.taskRepository.count({ projectId: id, status: 'DONE' }),
    ]);

    return {
      ...project,
      taskSummary: {
        todo: taskCounts[0],
        inProgress: taskCounts[1],
        inReview: taskCounts[2],
        done: taskCounts[3],
        total: taskCounts.reduce((a, b) => a + b, 0),
      },
    };
  }

  async create(dto: CreateProjectDto, ownerId: string) {
    const project = await this.projectRepository.create({
      name: dto.name,
      description: dto.description,
      owner: { connect: { id: ownerId } },
    });

    this.logger.log(`Project created: ${project.id} by user ${ownerId}`);
    await this.eventsService.publish('project.created', {
      projectId: project.id,
      ownerId,
    });

    return project;
  }

  async update(id: string, dto: UpdateProjectDto, userId: string) {
    const project = await this.projectRepository.findById(id);
    if (!project) {
      throw new NotFoundException('Project not found');
    }

    if (project.ownerId !== userId) {
      throw new ForbiddenException('Only the project owner can update this project');
    }

    const updated = await this.projectRepository.update(id, {
      ...(dto.name !== undefined && { name: dto.name }),
      ...(dto.description !== undefined && { description: dto.description }),
      ...(dto.status !== undefined && { status: dto.status }),
    });

    this.logger.log(`Project updated: ${id} by user ${userId}`);
    await this.eventsService.publish('project.updated', {
      projectId: id,
      userId,
    });

    return updated;
  }

  async softDelete(id: string, userId: string) {
    const project = await this.projectRepository.findById(id);
    if (!project) {
      throw new NotFoundException('Project not found');
    }

    if (project.ownerId !== userId) {
      throw new ForbiddenException('Only the project owner can delete this project');
    }

    // Soft delete sets status to ARCHIVED and deletedAt via Prisma middleware
    await this.projectRepository.update(id, {
      status: ProjectStatus.ARCHIVED,
      deletedAt: new Date(),
    });

    this.logger.log(`Project soft-deleted: ${id} by user ${userId}`);
    await this.eventsService.publish('project.deleted', {
      projectId: id,
      userId,
    });
  }
}
