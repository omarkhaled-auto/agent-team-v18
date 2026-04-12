import {
  Injectable,
  NotFoundException,
  Logger,
} from '@nestjs/common';
import { PrismaService } from '../common/prisma/prisma.service';
import { CreateCommentDto } from './dto/create-comment.dto';
import { PaginationQueryDto, PaginatedResponseDto } from '../common/dto/pagination.dto';

@Injectable()
export class CommentsService {
  private readonly logger = new Logger(CommentsService.name);

  constructor(private readonly prisma: PrismaService) {}

  async findAllByTask(
    taskId: string,
    query: PaginationQueryDto,
  ): Promise<PaginatedResponseDto<Record<string, unknown>>> {
    const task = await this.prisma.task.findFirst({
      where: { id: taskId, deleted_at: null },
      select: { id: true },
    });

    if (!task) {
      throw new NotFoundException('Task not found');
    }

    const { page, limit } = query;
    const skip = (page - 1) * limit;

    const [comments, total] = await Promise.all([
      this.prisma.comment.findMany({
        where: { task_id: taskId },
        skip,
        take: limit,
        orderBy: { created_at: 'asc' },
        include: {
          author: {
            select: { id: true, name: true, email: true, avatar_url: true },
          },
        },
      }),
      this.prisma.comment.count({ where: { task_id: taskId } }),
    ]);

    const data = comments.map((comment) => ({
      id: comment.id,
      content: comment.content,
      author: comment.author,
      created_at: comment.created_at,
    }));

    return {
      data,
      meta: { total, page, limit },
    };
  }

  async create(
    taskId: string,
    dto: CreateCommentDto,
    authorId: string,
  ): Promise<Record<string, unknown>> {
    const task = await this.prisma.task.findFirst({
      where: { id: taskId, deleted_at: null },
      select: { id: true },
    });

    if (!task) {
      throw new NotFoundException('Task not found');
    }

    const comment = await this.prisma.comment.create({
      data: {
        content: dto.content,
        task_id: taskId,
        author_id: authorId,
      },
      include: {
        author: {
          select: { id: true, name: true, email: true, avatar_url: true },
        },
      },
    });

    this.logger.log(`Comment created: ${comment.id} on task ${taskId}`);

    return {
      id: comment.id,
      content: comment.content,
      author: comment.author,
      created_at: comment.created_at,
    };
  }
}
