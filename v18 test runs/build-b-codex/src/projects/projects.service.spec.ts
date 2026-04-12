import { ForbiddenException, NotFoundException } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { EventsService } from '../events/events.service';
import { ProjectsRepository } from './projects.repository';
import { ProjectsService } from './projects.service';

describe('ProjectsService', () => {
  let projectsService: ProjectsService;
  const projectsRepository = {
    findMany: jest.fn(),
    findById: jest.fn(),
    getTaskCounts: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    archive: jest.fn(),
  };
  const eventsService = {
    publish: jest.fn(),
  };

  beforeEach(async () => {
    jest.clearAllMocks();
    const moduleRef = await Test.createTestingModule({
      providers: [
        ProjectsService,
        { provide: ProjectsRepository, useValue: projectsRepository },
        { provide: EventsService, useValue: eventsService },
      ],
    }).compile();

    projectsService = moduleRef.get(ProjectsService);
  });

  it('returns project details with task counts', async () => {
    projectsRepository.findById.mockResolvedValue({ id: 'project-1', owner_id: 'user-1' });
    projectsRepository.getTaskCounts.mockResolvedValue({ total: 2, todo: 1, in_progress: 1, in_review: 0, done: 0 });

    await expect(projectsService.findOne('project-1')).resolves.toEqual({
      id: 'project-1',
      owner_id: 'user-1',
      taskCounts: { total: 2, todo: 1, in_progress: 1, in_review: 0, done: 0 },
    });
  });

  it('throws when a project is missing', async () => {
    projectsRepository.findById.mockResolvedValue(null);
    await expect(projectsService.findOne('missing-project')).rejects.toBeInstanceOf(NotFoundException);
  });

  it('updates a project for the owner', async () => {
    projectsRepository.findById.mockResolvedValue({ id: 'project-1', owner_id: 'user-1' });
    projectsRepository.update.mockResolvedValue({ id: 'project-1', name: 'Updated Project' });

    await expect(projectsService.update('project-1', { name: 'Updated Project' }, 'user-1', 'MEMBER')).resolves.toEqual({
      id: 'project-1',
      name: 'Updated Project',
    });
  });

  it('rejects updates from non-owners', async () => {
    projectsRepository.findById.mockResolvedValue({ id: 'project-1', owner_id: 'owner-1' });
    await expect(projectsService.update('project-1', { name: 'Updated Project' }, 'user-2', 'MEMBER')).rejects.toBeInstanceOf(ForbiddenException);
  });

  it('archives a project for admins', async () => {
    projectsRepository.findById.mockResolvedValue({ id: 'project-1', owner_id: 'owner-1' });
    projectsRepository.archive.mockResolvedValue({ id: 'project-1', status: 'ARCHIVED' });

    await expect(projectsService.remove('project-1', 'admin-1', 'ADMIN')).resolves.toEqual({
      id: 'project-1',
      status: 'ARCHIVED',
    });
    expect(eventsService.publish).toHaveBeenCalledWith('project.events', {
      type: 'project.archived',
      payload: {
        projectId: 'project-1',
        archivedBy: 'admin-1',
      },
    });
  });
});
