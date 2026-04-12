import { Injectable } from '@nestjs/common';
import { TaskStatus } from '@prisma/client';
import { UserResponseDto } from '../common/dto/user.dto';
import { emptyUserTaskStats, mapUser, mapUserDetail } from '../common/utils/response-mappers';
import { PrismaService } from '../common/prisma/prisma.service';
import { UserDetailResponseDto, UserTaskStatsDto } from './dto/user-response.dto';

@Injectable()
export class UsersRepository {
  constructor(private readonly prisma: PrismaService) {}

  async findAll(): Promise<UserResponseDto[]> {
    const users = await this.prisma.user.findMany({
      orderBy: { name: 'asc' },
      select: {
        id: true,
        email: true,
        name: true,
        role: true,
        avatar_url: true,
        created_at: true,
        updated_at: true,
      },
    });

    return users.map((user) => mapUser(user));
  }

  async findById(id: string): Promise<UserResponseDto | null> {
    const user = await this.prisma.user.findUnique({
      where: { id },
      select: {
        id: true,
        email: true,
        name: true,
        role: true,
        avatar_url: true,
        created_at: true,
        updated_at: true,
      },
    });

    return user ? mapUser(user) : null;
  }

  async findByIdWithStats(id: string): Promise<UserDetailResponseDto | null> {
    const user = await this.prisma.user.findUnique({
      where: { id },
      select: {
        id: true,
        email: true,
        name: true,
        role: true,
        avatar_url: true,
        created_at: true,
        updated_at: true,
      },
    });

    if (!user) {
      return null;
    }

    const groups = await this.prisma.task.groupBy({
      by: ['status'],
      where: { assignee_id: id },
      _count: { status: true },
    });

    const stats = emptyUserTaskStats();
    groups.forEach((group) => {
      if (group.status === TaskStatus.TODO) {
        stats.todo = group._count.status;
      }
      if (group.status === TaskStatus.IN_PROGRESS) {
        stats.in_progress = group._count.status;
      }
      if (group.status === TaskStatus.IN_REVIEW) {
        stats.in_review = group._count.status;
      }
      if (group.status === TaskStatus.DONE) {
        stats.done = group._count.status;
      }
      stats.assigned += group._count.status;
    });

    return mapUserDetail(user, stats as UserTaskStatsDto);
  }
}
