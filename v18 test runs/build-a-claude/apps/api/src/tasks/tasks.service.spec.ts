import { Test, TestingModule } from '@nestjs/testing';
import {
  NotFoundException,
  BadRequestException,
} from '@nestjs/common';
import { TasksService } from './tasks.service';
import { TaskRepository } from '../repositories/task.repository';
import { ProjectRepository } from '../repositories/project.repository';
import { UserRepository } from '../repositories/user.repository';
import { EventsService } from '../events/events.service';
import { TaskStatus } from '@prisma/client';

describe('TasksService', () => {
  let service: TasksService;
  let taskRepository: jest.Mocked<TaskRepository>;
  let projectRepository: jest.Mocked<ProjectRepository>;
  let userRepository: jest.Mocked<UserRepository>;
  let eventsService: jest.Mocked<EventsService>;

  const mockProject = {
    id: 'project-uuid-1',
    name: 'Test Project',
    description: null,
    status: 'ACTIVE' as const,
    ownerId: 'user-uuid-1',
    createdAt: new Date(),
    updatedAt: new Date(),
    deletedAt: null,
  };

  const mockTask = {
    id: 'task-uuid-1',
    title: 'Test Task',
    description: null,
    status: TaskStatus.TODO,
    priority: 'MEDIUM' as const,
    dueDate: null,
    projectId: 'project-uuid-1',
    assigneeId: null,
    reporterId: 'user-uuid-1',
    createdAt: new Date(),
    updatedAt: new Date(),
    deletedAt: null,
  };

  const mockUser = {
    id: 'user-uuid-1',
    email: 'test@taskflow.com',
    name: 'Test User',
    passwordHash: 'hashed',
    role: 'MEMBER' as const,
    avatarUrl: null,
    createdAt: new Date(),
    updatedAt: new Date(),
  };

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        TasksService,
        {
          provide: TaskRepository,
          useValue: {
            findById: jest.fn(),
            findAll: jest.fn(),
            create: jest.fn(),
            update: jest.fn(),
            count: jest.fn(),
          },
        },
        {
          provide: ProjectRepository,
          useValue: {
            findById: jest.fn(),
          },
        },
        {
          provide: UserRepository,
          useValue: {
            findById: jest.fn(),
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

    service = module.get<TasksService>(TasksService);
    taskRepository = module.get(TaskRepository);
    projectRepository = module.get(ProjectRepository);
    userRepository = module.get(UserRepository);
    eventsService = module.get(EventsService);
  });

  describe('findAllByProject', () => {
    it('should return paginated tasks for a project', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);
      taskRepository.findAll.mockResolvedValue([mockTask]);
      taskRepository.count.mockResolvedValue(1);

      const result = await service.findAllByProject('project-uuid-1', {
        page: 1,
        limit: 20,
      });

      expect(result.data).toEqual([mockTask]);
      expect(result.meta.total).toBe(1);
    });

    it('should throw NotFoundException when project does not exist', async () => {
      projectRepository.findById.mockResolvedValue(null);

      await expect(
        service.findAllByProject('bad-uuid', { page: 1, limit: 20 }),
      ).rejects.toThrow(NotFoundException);
    });
  });

  describe('create', () => {
    it('should create task and publish event', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);
      taskRepository.create.mockResolvedValue(mockTask);

      const result = await service.create(
        'project-uuid-1',
        { title: 'Test Task' },
        'user-uuid-1',
      );

      expect(result).toEqual(mockTask);
      expect(eventsService.publish).toHaveBeenCalledWith('task.created', {
        taskId: mockTask.id,
        projectId: 'project-uuid-1',
        reporterId: 'user-uuid-1',
      });
    });

    it('should validate assignee exists when provided', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);
      userRepository.findById.mockResolvedValue(null);

      await expect(
        service.create(
          'project-uuid-1',
          { title: 'Test Task', assigneeId: 'bad-user-uuid' },
          'user-uuid-1',
        ),
      ).rejects.toThrow(BadRequestException);
    });

    it('should accept valid assignee', async () => {
      projectRepository.findById.mockResolvedValue(mockProject);
      userRepository.findById.mockResolvedValue(mockUser);
      taskRepository.create.mockResolvedValue({
        ...mockTask,
        assigneeId: 'user-uuid-1',
      });

      const result = await service.create(
        'project-uuid-1',
        { title: 'Test Task', assigneeId: 'user-uuid-1' },
        'user-uuid-1',
      );

      expect(result.assigneeId).toBe('user-uuid-1');
    });
  });

  describe('transitionStatus', () => {
    it('should allow TODO → IN_PROGRESS', async () => {
      taskRepository.findById.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.TODO,
      });
      taskRepository.update.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.IN_PROGRESS,
      });

      const result = await service.transitionStatus('task-uuid-1', {
        status: TaskStatus.IN_PROGRESS,
      });

      expect(result.status).toBe(TaskStatus.IN_PROGRESS);
    });

    it('should allow IN_PROGRESS → IN_REVIEW', async () => {
      taskRepository.findById.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.IN_PROGRESS,
      });
      taskRepository.update.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.IN_REVIEW,
      });

      const result = await service.transitionStatus('task-uuid-1', {
        status: TaskStatus.IN_REVIEW,
      });

      expect(result.status).toBe(TaskStatus.IN_REVIEW);
    });

    it('should allow IN_REVIEW → DONE', async () => {
      taskRepository.findById.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.IN_REVIEW,
      });
      taskRepository.update.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.DONE,
      });

      const result = await service.transitionStatus('task-uuid-1', {
        status: TaskStatus.DONE,
      });

      expect(result.status).toBe(TaskStatus.DONE);
    });

    it('should allow DONE → IN_PROGRESS (reopen)', async () => {
      taskRepository.findById.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.DONE,
      });
      taskRepository.update.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.IN_PROGRESS,
      });

      const result = await service.transitionStatus('task-uuid-1', {
        status: TaskStatus.IN_PROGRESS,
      });

      expect(result.status).toBe(TaskStatus.IN_PROGRESS);
    });

    it('should reject TODO → DONE (invalid transition)', async () => {
      taskRepository.findById.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.TODO,
      });

      await expect(
        service.transitionStatus('task-uuid-1', {
          status: TaskStatus.DONE,
        }),
      ).rejects.toThrow(BadRequestException);
    });

    it('should reject TODO → IN_REVIEW (invalid transition)', async () => {
      taskRepository.findById.mockResolvedValue({
        ...mockTask,
        status: TaskStatus.TODO,
      });

      await expect(
        service.transitionStatus('task-uuid-1', {
          status: TaskStatus.IN_REVIEW,
        }),
      ).rejects.toThrow(BadRequestException);
    });

    it('should throw NotFoundException for non-existent task', async () => {
      taskRepository.findById.mockResolvedValue(null);

      await expect(
        service.transitionStatus('bad-uuid', {
          status: TaskStatus.IN_PROGRESS,
        }),
      ).rejects.toThrow(NotFoundException);
    });
  });

  describe('softDelete', () => {
    it('should soft-delete task and publish event', async () => {
      taskRepository.findById.mockResolvedValue(mockTask);
      taskRepository.update.mockResolvedValue(mockTask);

      await service.softDelete('task-uuid-1');

      expect(taskRepository.update).toHaveBeenCalledWith(
        'task-uuid-1',
        expect.objectContaining({ deletedAt: expect.any(Date) }),
      );
      expect(eventsService.publish).toHaveBeenCalledWith('task.deleted', {
        taskId: 'task-uuid-1',
      });
    });

    it('should throw NotFoundException for non-existent task', async () => {
      taskRepository.findById.mockResolvedValue(null);

      await expect(service.softDelete('bad-uuid')).rejects.toThrow(
        NotFoundException,
      );
    });
  });
});
