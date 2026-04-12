import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { BaseRepository } from './base.repository';
import { Task, Prisma } from '@prisma/client';

@Injectable()
export class TaskRepository extends BaseRepository<Task> {
  constructor(prisma: PrismaService) {
    super(prisma);
  }

  async findById(id: string): Promise<Task | null> {
    return this.prisma.task.findUnique({
      where: { id },
      include: { comments: true, assignee: true, reporter: true },
    });
  }

  async findAll(params?: {
    skip?: number;
    take?: number;
    where?: Prisma.TaskWhereInput;
    orderBy?: Prisma.TaskOrderByWithRelationInput;
  }): Promise<Task[]> {
    return this.prisma.task.findMany({
      ...params,
      include: { assignee: true, reporter: true },
    });
  }

  async create(data: Prisma.TaskCreateInput): Promise<Task> {
    return this.prisma.task.create({ data });
  }

  async update(id: string, data: Prisma.TaskUpdateInput): Promise<Task> {
    return this.prisma.task.update({ where: { id }, data });
  }

  async count(where?: Prisma.TaskWhereInput): Promise<number> {
    return this.prisma.task.count({ where });
  }
}
