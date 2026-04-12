import { Injectable } from '@nestjs/common';
import { ProjectStatus, TaskStatus } from '@prisma/client';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { emptyProjectTaskCounts, mapProject } from '../common/utils/response-mappers';
import { PrismaService } from '../common/prisma/prisma.service';
import { CreateProjectDto } from './dto/create-project.dto';
import { ProjectArchiveResponseDto, ProjectResponseDto, ProjectTaskCountsDto } from './dto/project-response.dto';
import { ProjectQueryDto } from './dto/project-query.dto';
import { UpdateProjectDto } from './dto/update-project.dto';

const ownerSelect = {
  id: true,
  name: true,
  avatar_url: true,
} as const;

@Injectable()
export class ProjectsRepository {
  constructor(private readonly prisma: PrismaService) {}

  async findMany(query: ProjectQueryDto): Promise<PaginatedResponseDto<ProjectResponseDto>> {
    const page = query.page;
    const limit = query.limit;
    const status = query.status ?? ProjectStatus.ACTIVE;
    const skip = (page - 1) * limit;
    const where = { status };

    const [projects, total] = await Promise.all([
      this.prisma.project.findMany({
        where,
        skip,
        take: limit,
        orderBy: { created_at: 'desc' },
        include: { owner: { select: ownerSelect } },
      }),
      this.prisma.project.count({ where }),
    ]);

    return {
      data: projects.map((project) => mapProject(project)),
      meta: { total, page, limit },
    };
  }

  async findById(id: string): Promise<ProjectResponseDto | null> {
    const project = await this.prisma.project.findUnique({
      where: { id },
      include: { owner: { select: ownerSelect } },
    });

    return project ? mapProject(project) : null;
  }

  async create(ownerId: string, dto: CreateProjectDto): Promise<ProjectResponseDto> {
    const project = await this.prisma.project.create({
      data: {
        owner_id: ownerId,
        name: dto.name,
        description: dto.description ?? null,
      },
      include: { owner: { select: ownerSelect } },
    });

    return mapProject(project);
  }

  async update(id: string, dto: UpdateProjectDto): Promise<ProjectResponseDto> {
    const project = await this.prisma.project.update({
      where: { id },
      data: {
        ...(dto.name !== undefined ? { name: dto.name } : {}),
        ...(dto.description !== undefined ? { description: dto.description ?? null } : {}),
        ...(dto.status !== undefined ? { status: dto.status } : {}),
      },
      include: { owner: { select: ownerSelect } },
    });

    return mapProject(project);
  }

  async archive(id: string): Promise<ProjectArchiveResponseDto> {
    const archivedAt = new Date();
    return this.prisma.$transaction(async (transaction) => {
      const project = await transaction.project.update({
        where: { id },
        data: { status: ProjectStatus.ARCHIVED },
      });

      await transaction.task.updateMany({
        where: { project_id: id, deleted_at: null },
        data: { deleted_at: archivedAt },
      });

      return { id: project.id, status: ProjectStatus.ARCHIVED };
    });
  }

  async getTaskCounts(projectId: string): Promise<ProjectTaskCountsDto> {
    const groups = await this.prisma.task.groupBy({
      by: ['status'],
      where: { project_id: projectId },
      _count: { status: true },
    });

    const counts = emptyProjectTaskCounts();
    groups.forEach((group) => {
      if (group.status === TaskStatus.TODO) {
        counts.todo = group._count.status;
      }
      if (group.status === TaskStatus.IN_PROGRESS) {
        counts.in_progress = group._count.status;
      }
      if (group.status === TaskStatus.IN_REVIEW) {
        counts.in_review = group._count.status;
      }
      if (group.status === TaskStatus.DONE) {
        counts.done = group._count.status;
      }
      counts.total += group._count.status;
    });

    return counts;
  }
}
