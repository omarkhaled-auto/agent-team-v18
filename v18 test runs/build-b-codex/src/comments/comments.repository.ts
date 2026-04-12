import { Injectable } from '@nestjs/common';
import { PrismaService } from '../common/prisma/prisma.service';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { mapComment } from '../common/utils/response-mappers';
import { CommentQueryDto } from './dto/comment-query.dto';
import { CommentResponseDto } from './dto/comment-response.dto';

const userSummarySelect = {
  id: true,
  name: true,
  avatar_url: true,
} as const;

@Injectable()
export class CommentsRepository {
  constructor(private readonly prisma: PrismaService) {}

  async taskExists(taskId: string): Promise<boolean> {
    const task = await this.prisma.task.findFirst({ where: { id: taskId }, select: { id: true } });
    return Boolean(task);
  }

  async findManyByTask(taskId: string, query: CommentQueryDto): Promise<PaginatedResponseDto<CommentResponseDto>> {
    const page = query.page;
    const limit = query.limit;
    const skip = (page - 1) * limit;

    const [comments, total] = await Promise.all([
      this.prisma.comment.findMany({
        where: { task_id: taskId },
        skip,
        take: limit,
        orderBy: { created_at: 'asc' },
        include: { author: { select: userSummarySelect } },
      }),
      this.prisma.comment.count({ where: { task_id: taskId } }),
    ]);

    return {
      data: comments.map((comment) => mapComment(comment)),
      meta: { total, page, limit },
    };
  }

  async create(taskId: string, authorId: string, content: string): Promise<CommentResponseDto> {
    const comment = await this.prisma.comment.create({
      data: {
        task_id: taskId,
        author_id: authorId,
        content,
      },
      include: { author: { select: userSummarySelect } },
    });

    return mapComment(comment);
  }
}
