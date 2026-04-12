import {
  Injectable,
  NotFoundException,
  Logger,
} from '@nestjs/common';
import { PrismaService } from '../common/prisma/prisma.service';
import { PaginationQueryDto, PaginatedResponseDto } from '../common/dto/pagination.dto';

@Injectable()
export class UsersService {
  private readonly logger = new Logger(UsersService.name);

  constructor(private readonly prisma: PrismaService) {}

  async findAll(
    query: PaginationQueryDto,
  ): Promise<PaginatedResponseDto<Record<string, unknown>>> {
    const { page, limit } = query;
    const skip = (page - 1) * limit;

    const [users, total] = await Promise.all([
      this.prisma.user.findMany({
        skip,
        take: limit,
        orderBy: { name: 'asc' },
        select: {
          id: true,
          email: true,
          name: true,
          role: true,
          avatar_url: true,
          created_at: true,
          _count: {
            select: {
              assigned_tasks: {
                where: {
                  deleted_at: null,
                  status: { not: 'DONE' },
                },
              },
            },
          },
        },
      }),
      this.prisma.user.count(),
    ]);

    const data = users.map((user) => ({
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
      avatar_url: user.avatar_url,
      open_task_count: user._count.assigned_tasks,
      created_at: user.created_at,
    }));

    return {
      data,
      meta: { total, page, limit },
    };
  }

  async findOne(id: string): Promise<Record<string, unknown>> {
    const user = await this.prisma.user.findUnique({
      where: { id },
      select: {
        id: true,
        email: true,
        name: true,
        role: true,
        avatar_url: true,
        created_at: true,
      },
    });

    if (!user) {
      throw new NotFoundException('User not found');
    }

    const taskStats = await this.prisma.task.groupBy({
      by: ['status'],
      where: {
        assignee_id: id,
        deleted_at: null,
      },
      _count: true,
    });

    const stats = taskStats.reduce(
      (acc, item) => {
        acc[item.status] = item._count;
        return acc;
      },
      {} as Record<string, number>,
    );

    const totalAssigned = taskStats.reduce((sum, item) => sum + item._count, 0);

    return {
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
      avatar_url: user.avatar_url,
      task_stats: {
        total: totalAssigned,
        by_status: stats,
      },
      created_at: user.created_at,
    };
  }
}
