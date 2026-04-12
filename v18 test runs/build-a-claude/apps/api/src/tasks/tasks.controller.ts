import {
  Controller,
  Get,
  Post,
  Patch,
  Delete,
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
import { TasksService } from './tasks.service';
import { CreateTaskDto } from './dto/create-task.dto';
import { UpdateTaskDto } from './dto/update-task.dto';
import { UpdateTaskStatusDto } from './dto/update-task-status.dto';
import { TaskQueryDto } from './dto/task-query.dto';

@ApiTags('Tasks')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard)
@Controller()
export class TasksController {
  constructor(private readonly tasksService: TasksService) {}

  @Get('projects/:projectId/tasks')
  @ApiOperation({ summary: 'List tasks for a project (paginated, filterable, sortable)' })
  @ApiParam({ name: 'projectId', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 200, description: 'Paginated list of tasks' })
  @ApiResponse({ status: 404, description: 'Project not found' })
  async findAllByProject(
    @Param('projectId', ParseUUIDPipe) projectId: string,
    @Query() query: TaskQueryDto,
  ) {
    return this.tasksService.findAllByProject(projectId, query);
  }

  @Post('projects/:projectId/tasks')
  @ApiOperation({ summary: 'Create a task in a project' })
  @ApiParam({ name: 'projectId', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 201, description: 'Task created' })
  @ApiResponse({ status: 404, description: 'Project not found' })
  @HttpCode(HttpStatus.CREATED)
  async create(
    @Param('projectId', ParseUUIDPipe) projectId: string,
    @Body() dto: CreateTaskDto,
    @CurrentUser() user: JwtPayload,
  ) {
    return this.tasksService.create(projectId, dto, user.sub);
  }

  @Get('tasks/:id')
  @ApiOperation({ summary: 'Get task with comments' })
  @ApiParam({ name: 'id', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 200, description: 'Task with comments, assignee, reporter' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async findById(@Param('id', ParseUUIDPipe) id: string) {
    return this.tasksService.findById(id);
  }

  @Patch('tasks/:id')
  @ApiOperation({ summary: 'Update task fields' })
  @ApiParam({ name: 'id', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 200, description: 'Task updated' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async update(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateTaskDto,
  ) {
    return this.tasksService.update(id, dto);
  }

  @Patch('tasks/:id/status')
  @ApiOperation({ summary: 'Transition task status (validated against state machine)' })
  @ApiParam({ name: 'id', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 200, description: 'Task status transitioned' })
  @ApiResponse({ status: 400, description: 'Invalid status transition' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async transitionStatus(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateTaskStatusDto,
  ) {
    return this.tasksService.transitionStatus(id, dto);
  }

  @Delete('tasks/:id')
  @ApiOperation({ summary: 'Soft delete a task' })
  @ApiParam({ name: 'id', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 204, description: 'Task deleted' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  @HttpCode(HttpStatus.NO_CONTENT)
  async delete(@Param('id', ParseUUIDPipe) id: string) {
    await this.tasksService.softDelete(id);
  }
}
