import {
  Controller,
  Get,
  Post,
  Body,
  Param,
  Query,
  UseGuards,
  ParseUUIDPipe,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import { ApiTags, ApiOperation, ApiBearerAuth, ApiResponse } from '@nestjs/swagger';
import { CommentsService } from './comments.service';
import { CreateCommentDto } from './dto/create-comment.dto';
import { PaginationQueryDto } from '../common/dto/pagination.dto';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import { CurrentUser, CurrentUserPayload } from '../common/decorators/current-user.decorator';

@ApiTags('Comments')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard)
@Controller('api/tasks/:taskId/comments')
export class CommentsController {
  constructor(private readonly commentsService: CommentsService) {}

  @Get()
  @ApiOperation({ summary: 'List comments for a task (paginated)' })
  @ApiResponse({ status: 200, description: 'Paginated list of comments' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async findAll(
    @Param('taskId', ParseUUIDPipe) taskId: string,
    @Query() query: PaginationQueryDto,
  ) {
    return this.commentsService.findAllByTask(taskId, query);
  }

  @Post()
  @HttpCode(HttpStatus.CREATED)
  @ApiOperation({ summary: 'Add a comment to a task' })
  @ApiResponse({ status: 201, description: 'Comment created successfully' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async create(
    @Param('taskId', ParseUUIDPipe) taskId: string,
    @Body() dto: CreateCommentDto,
    @CurrentUser() user: CurrentUserPayload,
  ) {
    return this.commentsService.create(taskId, dto, user.id);
  }
}
