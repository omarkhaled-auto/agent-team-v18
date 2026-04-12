import { NotFoundException } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { EventsService } from '../events/events.service';
import { TasksRepository } from './tasks.repository';
import { TasksService } from './tasks.service';

describe('TasksService', () => {
  let tasksService: TasksService;
  const tasksRepository = {
    findProjectStatus: jest.fn(),
    userExists: jest.fn(),
    findManyByProject: jest.fn(),
    findDetailById: jest.fn(),
    findStateContextById: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    updateStatus: jest.fn(),
    softDelete: jest.fn(),
  };
  const eventsService = {
    publish: jest.fn(),
  };

  beforeEach(async () => {
    jest.clearAllMocks();
    const moduleRef = await Test.createTestingModule({
      providers: [
        TasksService,
        { provide: TasksRepository, useValue: tasksRepository },
        { provide: EventsService, useValue: eventsService },
      ],
    }).compile();

    tasksService = moduleRef.get(TasksService);
  });

  it('lists tasks for an existing project', async () => {
    const response = { data: [{ id: 'task-1' }], meta: { total: 1, page: 1, limit: 20 } };
    tasksRepository.findProjectStatus.mockResolvedValue('ACTIVE');
    tasksRepository.findManyByProject.mockResolvedValue(response);

    await expect(tasksService.findAllByProject('project-1', { page: 1, limit: 20 })).resolves.toEqual(response);
  });

  it('rejects task listing for missing projects', async () => {
    tasksRepository.findProjectStatus.mockResolvedValue(null);

    await expect(tasksService.findAllByProject('missing-project', { page: 1, limit: 20 })).rejects.toBeInstanceOf(NotFoundException);
  });

  it('creates a task and publishes an event', async () => {
    const createdTask = { id: 'task-1', project_id: 'project-1' };
    tasksRepository.findProjectStatus.mockResolvedValue('ACTIVE');
    tasksRepository.userExists.mockResolvedValue(true);
    tasksRepository.create.mockResolvedValue(createdTask);

    await expect(
      tasksService.create('project-1', { title: 'Implement API', assignee_id: 'user-2' }, 'user-1'),
    ).resolves.toEqual(createdTask);

    expect(eventsService.publish).toHaveBeenCalledWith('task.events', {
      type: 'task.created',
      payload: {
        taskId: 'task-1',
        projectId: 'project-1',
        reporterId: 'user-1',
      },
    });
  });

  it('rejects task creation when the assignee is missing', async () => {
    tasksRepository.findProjectStatus.mockResolvedValue('ACTIVE');
    tasksRepository.userExists.mockResolvedValue(false);

    await expect(
      tasksService.create('project-1', { title: 'Implement API', assignee_id: 'missing-user' }, 'user-1'),
    ).rejects.toBeInstanceOf(NotFoundException);
  });

  it('returns task details', async () => {
    const taskDetail = { id: 'task-1', comments: [] };
    tasksRepository.findDetailById.mockResolvedValue(taskDetail);

    await expect(tasksService.findOne('task-1')).resolves.toEqual(taskDetail);
  });

  it('transitions task status and publishes an event', async () => {
    const updatedTask = { id: 'task-1', status: 'IN_PROGRESS' };
    tasksRepository.findStateContextById.mockResolvedValue({
      status: 'TODO',
      project_id: 'project-1',
      assignee_id: 'user-1',
      reporter_id: 'user-2',
    });
    tasksRepository.updateStatus.mockResolvedValue(updatedTask);

    await expect(
      tasksService.transitionStatus('task-1', { status: 'IN_PROGRESS' }, { id: 'user-1', email: 'user@test.com', role: 'MEMBER' }),
    ).resolves.toEqual(updatedTask);

    expect(eventsService.publish).toHaveBeenCalledWith('task.events', {
      type: 'task.status_changed',
      payload: {
        taskId: 'task-1',
        projectId: 'project-1',
        previousStatus: 'TODO',
        status: 'IN_PROGRESS',
      },
    });
  });

  it('soft deletes an existing task', async () => {
    tasksRepository.findStateContextById.mockResolvedValue({
      status: 'TODO',
      project_id: 'project-1',
      assignee_id: null,
      reporter_id: 'user-2',
    });
    tasksRepository.softDelete.mockResolvedValue({ id: 'task-1', deleted: true });

    await expect(tasksService.remove('task-1')).resolves.toEqual({ id: 'task-1', deleted: true });
  });

  it('rejects deleting a missing task', async () => {
    tasksRepository.findStateContextById.mockResolvedValue(null);

    await expect(tasksService.remove('missing-task')).rejects.toBeInstanceOf(NotFoundException);
  });
});
