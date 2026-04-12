import { Injectable, NotFoundException, Optional } from '@nestjs/common';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { EventsService } from '../events/events.service';
import { CommentsRepository } from './comments.repository';
import { CommentQueryDto } from './dto/comment-query.dto';
import { CommentResponseDto } from './dto/comment-response.dto';
import { CreateCommentDto } from './dto/create-comment.dto';

@Injectable()
export class CommentsService {
  constructor(
    private readonly commentsRepository: CommentsRepository,
    @Optional() private readonly eventsService?: EventsService,
  ) {}

  async findAllByTask(taskId: string, query: CommentQueryDto): Promise<PaginatedResponseDto<CommentResponseDto>> {
    if (!(await this.commentsRepository.taskExists(taskId))) {
      throw new NotFoundException('Task not found');
    }

    return this.commentsRepository.findManyByTask(taskId, query);
  }

  async create(taskId: string, dto: CreateCommentDto, authorId: string): Promise<CommentResponseDto> {
    if (!(await this.commentsRepository.taskExists(taskId))) {
      throw new NotFoundException('Task not found');
    }

    const comment = await this.commentsRepository.create(taskId, authorId, dto.content);

    await this.eventsService?.publish('comment.events', {
      type: 'comment.created',
      payload: {
        commentId: comment.id,
        taskId,
        authorId,
      },
    });

    return comment;
  }
}
