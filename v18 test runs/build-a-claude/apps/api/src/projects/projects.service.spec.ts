import { Test, TestingModule } from '@nestjs/testing';
import { NotFoundException, ForbiddenException } from '@nestjs/common';
import { ProjectsService } from './projects.service';
import { ProjectRepository } from '../repositories/project.repository';
import { TaskRepository } from '../repositories/task.repository';
import { EventsService } from '../events/events.service';

describe('ProjectsService', () => {
  let service: ProjectsService;
  let projectRepository: jest.Mocked<ProjectRepository>;
  let taskRepository: jest.Mocked<TaskRepository>;
  let eventsService: jest.Mocked<EventsService>;

  const mockProject = {
    id: 'project-uuid-1',
    name: 'Test Project',
    description: 'A test project',
    status: 'ACTIVE' as const,
    ownerId: 'user-uuid-1',
    createdAt: new Date(),
    updatedAt: new Date(),
    deletedAt: null,
  };

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        ProjectsService,
        {
          provide: ProjectRepository,
          useValue: {
            findById: jest.fn(),
            findAll: jest.fn(),
            create: jest.fn(),
            update: jest.fn(),
            count: jest.fn(),
          },
        },
        {
          provide: TaskRepository,
          useValue: {
            count: jest.fn(),
          },
        },
        {
          provide: EventsService,
          useValue: {
            publish: jest.fn(),
          },
        },
      ],
    }).compile();

    service = module.get<ProjectsService>(ProjectsService);
    projectRepository = module.get(ProjectRepository);
    taskRepository = module.get(TaskRepository);
    eventsService = module.get(EventsService);
  });

  describe('findAll', () => {
    it('should return paginated projects', async () => {
      const projects = [mockProject];
      projectRepository.findAll.mockResolvedValue(projects);
      projectRepository.count.mockResolvedValue(1);

      const result = await service.findAll({ page: 1, limit: 20 });

      expect(result.data).toEqual(projects);
      expect(result.meta).toEqual({
        total: 1,
        page: 1,
        limit: 20,
        totalPages: 1,
      });
    });

    it('should filter by status when provided', async () => {
      projectRepository.findAll.mockResolvedValue([]);
      projectRepository.count.mockResolvedValue(0);

      await service.findAll({ page: 1, limit: 20, status: 'ACTIVE' as any });

      expect(projectRepository.findAll).toHaveBeenCalledWith(
        expect.objectContaining({
          where: { status: 'ACTIVE' },
        }),
      );
    });
  });

  describe('findById', () => {
    it('should return project with task summary', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);
      taskRepository.count
        .mockResolvedValueOnce(3) // TODO
        .mockResolvedValueOnce(2) // IN_PROGRESS
        .mockResolvedValueOnce(1) // IN_REVIEW
        .mockResolvedValueOnce(4); // DONE

      const result = await service.findById('project-uuid-1');

      expect(result.taskSummary).toEqual({
        todo: 3,
        inProgress: 2,
        inReview: 1,
        done: 4,
        total: 10,
      });
    });

    it('should throw NotFoundException for non-existent project', async () => {
      projectRepository.findById.mockResolvedValue(null);

      await expect(service.findById('bad-uuid')).rejects.toThrow(
        NotFoundException,
      );
    });
  });

  describe('create', () => {
    it('should create project and publish event', async () => {
      projectRepository.create.mockResolvedValue(mockProject);

      const result = await service.create(
        { name: 'Test Project', description: 'A test project' },
        'user-uuid-1',
      );

      expect(result).toEqual(mockProject);
      expect(eventsService.publish).toHaveBeenCalledWith('project.created', {
        projectId: mockProject.id,
        ownerId: 'user-uuid-1',
      });
    });
  });

  describe('update', () => {
    it('should update project when user is owner', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);
      projectRepository.update.mockResolvedValue({
        ...mockProject,
        name: 'Updated',
      });

      const result = await service.update(
        'project-uuid-1',
        { name: 'Updated' },
        'user-uuid-1',
      );

      expect(result.name).toBe('Updated');
    });

    it('should throw ForbiddenException when user is not owner', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);

      await expect(
        service.update('project-uuid-1', { name: 'Updated' }, 'other-user'),
      ).rejects.toThrow(ForbiddenException);
    });

    it('should throw NotFoundException for non-existent project', async () => {
      projectRepository.findById.mockResolvedValue(null);

      await expect(
        service.update('bad-uuid', { name: 'Updated' }, 'user-uuid-1'),
      ).rejects.toThrow(NotFoundException);
    });
  });

  describe('softDelete', () => {
    it('should soft-delete project when user is owner', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);
      projectRepository.update.mockResolvedValue({
        ...mockProject,
        status: 'ARCHIVED' as any,
      });

      await service.softDelete('project-uuid-1', 'user-uuid-1');

      expect(projectRepository.update).toHaveBeenCalledWith(
        'project-uuid-1',
        expect.objectContaining({ status: 'ARCHIVED' }),
      );
      expect(eventsService.publish).toHaveBeenCalledWith('project.deleted', {
        projectId: 'project-uuid-1',
        userId: 'user-uuid-1',
      });
    });

    it('should throw ForbiddenException when user is not owner', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);

      await expect(
        service.softDelete('project-uuid-1', 'other-user'),
      ).rejects.toThrow(ForbiddenException);
    });
  });
});
