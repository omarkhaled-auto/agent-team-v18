import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Param, ParseUUIDPipe, Patch, Post, Query } from '@nestjs/common';
import { ApiBadRequestResponse, ApiBearerAuth, ApiForbiddenResponse, ApiNotFoundResponse, ApiOperation, ApiTags } from '@nestjs/swagger';
import { CurrentUser, CurrentUserPayload } from '../common/decorators/current-user.decorator';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { ApiDataResponse } from '../common/swagger/api-data-response.decorator';
import { TasksService } from './tasks.service';
import { CreateTaskDto } from './dto/create-task.dto';
import { TaskQueryDto } from './dto/task-query.dto';
import { TaskDeleteResponseDto, TaskDetailResponseDto, TaskResponseDto } from './dto/task-response.dto';
import { TransitionStatusDto } from './dto/transition-status.dto';
import { UpdateTaskDto } from './dto/update-task.dto';

@ApiTags('Tasks')
@ApiBearerAuth()
@Controller()
export class TasksController {
  constructor(private readonly tasksService: TasksService) {}

  @Get('projects/:projectId/tasks')
  @ApiOperation({ summary: 'List tasks for a project' })
  @ApiDataResponse(TaskResponseDto, { description: 'Paginated list of tasks', isArray: true, paginated: true })
  @ApiNotFoundResponse({ description: 'Project not found' })
  async findAllByProject(
    @Param('projectId', ParseUUIDPipe) projectId: string,
    @Query() query: TaskQueryDto,
  ): Promise<PaginatedResponseDto<TaskResponseDto>> {
    return this.tasksService.findAllByProject(projectId, query);
  }

  @Post('projects/:projectId/tasks')
  @HttpCode(HttpStatus.CREATED)
  @ApiOperation({ summary: 'Create a task in a project' })
  @ApiDataResponse(TaskResponseDto, { description: 'Task created successfully', status: 201 })
  @ApiNotFoundResponse({ description: 'Project or assignee not found' })
  async create(
    @Param('projectId', ParseUUIDPipe) projectId: string,
    @Body() dto: CreateTaskDto,
    @CurrentUser() user: CurrentUserPayload,
  ): Promise<TaskResponseDto> {
    return this.tasksService.create(projectId, dto, user.id);
  }

  @Get('tasks/:id')
  @ApiOperation({ summary: 'Get a task with comments' })
  @ApiDataResponse(TaskDetailResponseDto, { description: 'Task details with comments' })
  @ApiNotFoundResponse({ description: 'Task not found' })
  async findOne(@Param('id', ParseUUIDPipe) id: string): Promise<TaskDetailResponseDto> {
    return this.tasksService.findOne(id);
  }

  @Patch('tasks/:id')
  @ApiOperation({ summary: 'Update task fields' })
  @ApiDataResponse(TaskResponseDto, { description: 'Task updated successfully' })
  @ApiNotFoundResponse({ description: 'Task or assignee not found' })
  async update(@Param('id', ParseUUIDPipe) id: string, @Body() dto: UpdateTaskDto): Promise<TaskResponseDto> {
    return this.tasksService.update(id, dto);
  }

  @Patch('tasks/:id/status')
  @ApiOperation({ summary: 'Transition task status' })
  @ApiDataResponse(TaskResponseDto, { description: 'Task status updated successfully' })
  @ApiBadRequestResponse({ description: 'Invalid transition' })
  @ApiForbiddenResponse({ description: 'Forbidden' })
  @ApiNotFoundResponse({ description: 'Task not found' })
  async transitionStatus(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: TransitionStatusDto,
    @CurrentUser() user: CurrentUserPayload,
  ): Promise<TaskResponseDto> {
    return this.tasksService.transitionStatus(id, dto, user);
  }

  @Delete('tasks/:id')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: 'Soft delete a task' })
  @ApiDataResponse(TaskDeleteResponseDto, { description: 'Task deleted successfully' })
  @ApiNotFoundResponse({ description: 'Task not found' })
  async remove(@Param('id', ParseUUIDPipe) id: string): Promise<TaskDeleteResponseDto> {
    return this.tasksService.remove(id);
  }
}
