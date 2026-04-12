import { Injectable, NotFoundException, Logger } from '@nestjs/common';
import { CommentRepository } from '../repositories/comment.repository';
import { TaskRepository } from '../repositories/task.repository';
import { EventsService } from '../events/events.service';
import { CreateCommentDto } from './dto/create-comment.dto';
import { PaginationQueryDto } from '../common/dto/pagination-query.dto';
import { PaginatedResponseDto } from '../common/dto/paginated-response.dto';

@Injectable()
export class CommentsService {
  private readonly logger = new Logger(CommentsService.name);

  constructor(
    private readonly commentRepository: CommentRepository,
    private readonly taskRepository: TaskRepository,
    private readonly eventsService: EventsService,
  ) {}

  async findAllByTask(taskId: string, query: PaginationQueryDto) {
    const { page = 1, limit = 20 } = query;

    // Verify task exists
    const task = await this.taskRepository.findById(taskId);
    if (!task) {
      throw new NotFoundException('Task not found');
    }

    const skip = (page - 1) * limit;

    const [comments, total] = await Promise.all([
      this.commentRepository.findAll({
        skip,
        take: limit,
        where: { taskId },
        orderBy: { createdAt: 'desc' },
      }),
      this.commentRepository.count({ taskId }),
    ]);

    return new PaginatedResponseDto(comments, total, page, limit);
  }

  async create(taskId: string, dto: CreateCommentDto, authorId: string) {
    // Verify task exists
    const task = await this.taskRepository.findById(taskId);
    if (!task) {
      throw new NotFoundException('Task not found');
    }

    const comment = await this.commentRepository.create({
      content: dto.content,
      task: { connect: { id: taskId } },
      author: { connect: { id: authorId } },
    });

    this.logger.log(`Comment created: ${comment.id} on task ${taskId}`);
    await this.eventsService.publish('comment.created', {
      commentId: comment.id,
      taskId,
      authorId,
    });

    return comment;
  }
}
