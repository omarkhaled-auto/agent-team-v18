import {
  Injectable,
  NotFoundException,
  ForbiddenException,
  Logger,
} from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { PrismaService } from '../common/prisma/prisma.service';
import { CreateProjectDto } from './dto/create-project.dto';
import { UpdateProjectDto } from './dto/update-project.dto';
import { ProjectQueryDto } from './dto/project-query.dto';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';

@Injectable()
export class ProjectsService {
  private readonly logger = new Logger(ProjectsService.name);

  constructor(private readonly prisma: PrismaService) {}

  async findAll(query: ProjectQueryDto): Promise<PaginatedResponseDto<Record<string, unknown>>> {
    const { page, limit, status } = query;
    const skip = (page - 1) * limit;

    const where: Prisma.ProjectWhereInput = {
      deleted_at: null,
      ...(status && { status }),
    };

    const [projects, total] = await Promise.all([
      this.prisma.project.findMany({
        where,
        skip,
        take: limit,
        orderBy: { created_at: 'desc' },
        include: {
          owner: {
            select: { id: true, name: true, email: true },
          },
          _count: {
            select: { tasks: { where: { deleted_at: null } } },
          },
        },
      }),
      this.prisma.project.count({ where }),
    ]);

    const data = projects.map((project) => ({
      id: project.id,
      name: project.name,
      description: project.description,
      status: project.status,
      owner: project.owner,
      task_count: project._count.tasks,
      created_at: project.created_at,
      updated_at: project.updated_at,
    }));

    return {
      data,
      meta: { total, page, limit },
    };
  }

  async findOne(id: string): Promise<Record<string, unknown>> {
    const project = await this.prisma.project.findFirst({
      where: { id, deleted_at: null },
      include: {
        owner: {
          select: { id: true, name: true, email: true },
        },
        _count: {
          select: {
            tasks: { where: { deleted_at: null } },
          },
        },
      },
    });

    if (!project) {
      throw new NotFoundException('Project not found');
    }

    const taskStatusCounts = await this.prisma.task.groupBy({
      by: ['status'],
      where: { project_id: id, deleted_at: null },
      _count: true,
    });

    const statusSummary = taskStatusCounts.reduce(
      (acc, item) => {
        acc[item.status] = item._count;
        return acc;
      },
      {} as Record<string, number>,
    );

    return {
      id: project.id,
      name: project.name,
      description: project.description,
      status: project.status,
      owner: project.owner,
      task_count: project._count.tasks,
      task_status_summary: statusSummary,
      created_at: project.created_at,
      updated_at: project.updated_at,
    };
  }

  async create(dto: CreateProjectDto, userId: string): Promise<Record<string, unknown>> {
    const project = await this.prisma.project.create({
      data: {
        name: dto.name,
        description: dto.description,
        owner_id: userId,
      },
      include: {
        owner: {
          select: { id: true, name: true, email: true },
        },
      },
    });

    this.logger.log(`Project created: ${project.id} by user ${userId}`);

    return {
      id: project.id,
      name: project.name,
      description: project.description,
      status: project.status,
      owner: project.owner,
      task_count: 0,
      created_at: project.created_at,
      updated_at: project.updated_at,
    };
  }

  async update(
    id: string,
    dto: UpdateProjectDto,
    userId: string,
    userRole: string,
  ): Promise<Record<string, unknown>> {
    const project = await this.prisma.project.findFirst({
      where: { id, deleted_at: null },
    });

    if (!project) {
      throw new NotFoundException('Project not found');
    }

    if (project.owner_id !== userId && userRole !== 'ADMIN') {
      throw new ForbiddenException('Only the project owner or an admin can update this project');
    }

    const updated = await this.prisma.project.update({
      where: { id },
      data: {
        ...(dto.name !== undefined && { name: dto.name }),
        ...(dto.description !== undefined && { description: dto.description }),
        ...(dto.status !== undefined && { status: dto.status }),
      },
      include: {
        owner: {
          select: { id: true, name: true, email: true },
        },
        _count: {
          select: { tasks: { where: { deleted_at: null } } },
        },
      },
    });

    this.logger.log(`Project updated: ${id} by user ${userId}`);

    return {
      id: updated.id,
      name: updated.name,
      description: updated.description,
      status: updated.status,
      owner: updated.owner,
      task_count: updated._count.tasks,
      created_at: updated.created_at,
      updated_at: updated.updated_at,
    };
  }

  async softDelete(id: string, userId: string, userRole: string): Promise<{ message: string }> {
    const project = await this.prisma.project.findFirst({
      where: { id, deleted_at: null },
    });

    if (!project) {
      throw new NotFoundException('Project not found');
    }

    if (project.owner_id !== userId && userRole !== 'ADMIN') {
      throw new ForbiddenException('Only the project owner or an admin can delete this project');
    }

    const now = new Date();

    await this.prisma.$transaction([
      this.prisma.project.update({
        where: { id },
        data: { deleted_at: now, status: 'ARCHIVED' },
      }),
      this.prisma.task.updateMany({
        where: { project_id: id, deleted_at: null },
        data: { deleted_at: now },
      }),
    ]);

    this.logger.log(`Project soft-deleted: ${id} by user ${userId}`);

    return { message: 'Project deleted successfully' };
  }
}
