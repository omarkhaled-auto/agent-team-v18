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
import {
  ApiTags,
  ApiBearerAuth,
  ApiOperation,
  ApiParam,
  ApiResponse,
} from '@nestjs/swagger';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import { CurrentUser } from '../auth/decorators/current-user.decorator';
import { JwtPayload } from '../auth/interfaces/jwt-payload.interface';
import { CommentsService } from './comments.service';
import { CreateCommentDto } from './dto/create-comment.dto';
import { PaginationQueryDto } from '../common/dto/pagination-query.dto';

@ApiTags('Comments')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard)
@Controller('tasks/:taskId/comments')
export class CommentsController {
  constructor(private readonly commentsService: CommentsService) {}

  @Get()
  @ApiOperation({ summary: 'List comments for a task (paginated)' })
  @ApiParam({ name: 'taskId', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 200, description: 'Paginated list of comments' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async findAll(
    @Param('taskId', ParseUUIDPipe) taskId: string,
    @Query() query: PaginationQueryDto,
  ) {
    return this.commentsService.findAllByTask(taskId, query);
  }

  @Post()
  @ApiOperation({ summary: 'Add a comment to a task' })
  @ApiParam({ name: 'taskId', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 201, description: 'Comment created' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  @HttpCode(HttpStatus.CREATED)
  async create(
    @Param('taskId', ParseUUIDPipe) taskId: string,
    @Body() dto: CreateCommentDto,
    @CurrentUser() user: JwtPayload,
  ) {
    return this.commentsService.create(taskId, dto, user.sub);
  }
}
