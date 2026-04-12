import { Body, Controller, Get, HttpCode, HttpStatus, Param, ParseUUIDPipe, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiNotFoundResponse, ApiOperation, ApiTags } from '@nestjs/swagger';
import { CurrentUser, CurrentUserPayload } from '../common/decorators/current-user.decorator';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { ApiDataResponse } from '../common/swagger/api-data-response.decorator';
import { CommentsService } from './comments.service';
import { CommentQueryDto } from './dto/comment-query.dto';
import { CommentResponseDto } from './dto/comment-response.dto';
import { CreateCommentDto } from './dto/create-comment.dto';

@ApiTags('Comments')
@ApiBearerAuth()
@Controller('tasks/:taskId/comments')
export class CommentsController {
  constructor(private readonly commentsService: CommentsService) {}

  @Get()
  @ApiOperation({ summary: 'List comments for a task' })
  @ApiDataResponse(CommentResponseDto, { description: 'Paginated list of comments', isArray: true, paginated: true })
  @ApiNotFoundResponse({ description: 'Task not found' })
  async findAll(
    @Param('taskId', ParseUUIDPipe) taskId: string,
    @Query() query: CommentQueryDto,
  ): Promise<PaginatedResponseDto<CommentResponseDto>> {
    return this.commentsService.findAllByTask(taskId, query);
  }

  @Post()
  @HttpCode(HttpStatus.CREATED)
  @ApiOperation({ summary: 'Add a comment to a task' })
  @ApiDataResponse(CommentResponseDto, { description: 'Comment created successfully', status: 201 })
  @ApiNotFoundResponse({ description: 'Task not found' })
  async create(
    @Param('taskId', ParseUUIDPipe) taskId: string,
    @Body() dto: CreateCommentDto,
    @CurrentUser() user: CurrentUserPayload,
  ): Promise<CommentResponseDto> {
    return this.commentsService.create(taskId, dto, user.id);
  }
}
