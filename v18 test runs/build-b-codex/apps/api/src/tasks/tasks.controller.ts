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
import { ApiTags, ApiOperation, ApiBearerAuth, ApiResponse } from '@nestjs/swagger';
import { TasksService } from './tasks.service';
import { CreateTaskDto } from './dto/create-task.dto';
import { UpdateTaskDto } from './dto/update-task.dto';
import { TransitionStatusDto } from './dto/transition-status.dto';
import { TaskQueryDto } from './dto/task-query.dto';
import { JwtAuthGuard } from '../auth/guards/jwt-auth.guard';
import { CurrentUser, CurrentUserPayload } from '../common/decorators/current-user.decorator';

@ApiTags('Tasks')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard)
@Controller('api')
export class TasksController {
  constructor(private readonly tasksService: TasksService) {}

  @Get('projects/:projectId/tasks')
  @ApiOperation({ summary: 'List tasks for a project (paginated, filterable, sortable)' })
  @ApiResponse({ status: 200, description: 'Paginated list of tasks' })
  @ApiResponse({ status: 404, description: 'Project not found' })
  async findAllByProject(
    @Param('projectId', ParseUUIDPipe) projectId: string,
    @Query() query: TaskQueryDto,
  ) {
    return this.tasksService.findAllByProject(projectId, query);
  }

  @Post('projects/:projectId/tasks')
  @HttpCode(HttpStatus.CREATED)
  @ApiOperation({ summary: 'Create a task in a project' })
  @ApiResponse({ status: 201, description: 'Task created successfully' })
  @ApiResponse({ status: 404, description: 'Project not found' })
  async create(
    @Param('projectId', ParseUUIDPipe) projectId: string,
    @Body() dto: CreateTaskDto,
    @CurrentUser() user: CurrentUserPayload,
  ) {
    return this.tasksService.create(projectId, dto, user.id);
  }

  @Get('tasks/:id')
  @ApiOperation({ summary: 'Get task with comments' })
  @ApiResponse({ status: 200, description: 'Task details with comments' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async findOne(@Param('id', ParseUUIDPipe) id: string) {
    return this.tasksService.findOne(id);
  }

  @Patch('tasks/:id')
  @ApiOperation({ summary: 'Update task fields' })
  @ApiResponse({ status: 200, description: 'Task updated successfully' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async update(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateTaskDto,
  ) {
    return this.tasksService.update(id, dto);
  }

  @Patch('tasks/:id/status')
  @ApiOperation({ summary: 'Transition task status (validated against state machine)' })
  @ApiResponse({ status: 200, description: 'Task status transitioned successfully' })
  @ApiResponse({ status: 400, description: 'Invalid status transition' })
  @ApiResponse({ status: 403, description: 'Not authorized for this transition' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async transitionStatus(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: TransitionStatusDto,
    @CurrentUser() user: CurrentUserPayload,
  ) {
    return this.tasksService.transitionStatus(id, dto.status as any, {
      id: user.id,
      role: user.role,
    });
  }

  @Delete('tasks/:id')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: 'Soft delete a task' })
  @ApiResponse({ status: 200, description: 'Task deleted successfully' })
  @ApiResponse({ status: 404, description: 'Task not found' })
  async remove(@Param('id', ParseUUIDPipe) id: string) {
    return this.tasksService.softDelete(id);
  }
}
