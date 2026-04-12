import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { BaseRepository } from './base.repository';
import { Project, Prisma } from '@prisma/client';

@Injectable()
export class ProjectRepository extends BaseRepository<Project> {
  constructor(prisma: PrismaService) {
    super(prisma);
  }

  async findById(id: string): Promise<Project | null> {
    return this.prisma.project.findUnique({ where: { id } });
  }

  async findAll(params?: {
    skip?: number;
    take?: number;
    where?: Prisma.ProjectWhereInput;
    orderBy?: Prisma.ProjectOrderByWithRelationInput;
  }): Promise<Project[]> {
    return this.prisma.project.findMany(params);
  }

  async create(data: Prisma.ProjectCreateInput): Promise<Project> {
    return this.prisma.project.create({ data });
  }

  async update(id: string, data: Prisma.ProjectUpdateInput): Promise<Project> {
    return this.prisma.project.update({ where: { id }, data });
  }

  async count(where?: Prisma.ProjectWhereInput): Promise<number> {
    return this.prisma.project.count({ where });
  }
}
