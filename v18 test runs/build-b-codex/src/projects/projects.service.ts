import { ForbiddenException, Injectable, NotFoundException, Optional } from '@nestjs/common';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { EventsService } from '../events/events.service';
import { CreateProjectDto } from './dto/create-project.dto';
import { ProjectArchiveResponseDto, ProjectDetailResponseDto, ProjectResponseDto } from './dto/project-response.dto';
import { ProjectQueryDto } from './dto/project-query.dto';
import { UpdateProjectDto } from './dto/update-project.dto';
import { ProjectsRepository } from './projects.repository';

@Injectable()
export class ProjectsService {
  constructor(
    private readonly projectsRepository: ProjectsRepository,
    @Optional() private readonly eventsService?: EventsService,
  ) {}

  findAll(query: ProjectQueryDto): Promise<PaginatedResponseDto<ProjectResponseDto>> {
    return this.projectsRepository.findMany(query);
  }

  async findOne(id: string): Promise<ProjectDetailResponseDto> {
    const project = await this.projectsRepository.findById(id);
    if (!project) {
      throw new NotFoundException('Project not found');
    }

    const taskCounts = await this.projectsRepository.getTaskCounts(id);
    return { ...project, taskCounts };
  }

  create(dto: CreateProjectDto, userId: string): Promise<ProjectResponseDto> {
    return this.projectsRepository.create(userId, dto);
  }

  async update(id: string, dto: UpdateProjectDto, userId: string, userRole: string): Promise<ProjectResponseDto> {
    const project = await this.projectsRepository.findById(id);
    if (!project) {
      throw new NotFoundException('Project not found');
    }

    if (project.owner_id !== userId && userRole !== 'ADMIN') {
      throw new ForbiddenException('Only the project owner or an admin can update this project');
    }

    return this.projectsRepository.update(id, dto);
  }

  async remove(id: string, userId: string, userRole: string): Promise<ProjectArchiveResponseDto> {
    const project = await this.projectsRepository.findById(id);
    if (!project) {
      throw new NotFoundException('Project not found');
    }

    if (project.owner_id !== userId && userRole !== 'ADMIN') {
      throw new ForbiddenException('Only the project owner or an admin can delete this project');
    }

    const archivedProject = await this.projectsRepository.archive(id);

    await this.eventsService?.publish('project.events', {
      type: 'project.archived',
      payload: {
        projectId: id,
        archivedBy: userId,
      },
    });

    return archivedProject;
  }
}
