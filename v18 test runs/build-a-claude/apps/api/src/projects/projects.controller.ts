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
import { ProjectsService } from './projects.service';
import { CreateProjectDto } from './dto/create-project.dto';
import { UpdateProjectDto } from './dto/update-project.dto';
import { ProjectQueryDto } from './dto/project-query.dto';

@ApiTags('Projects')
@ApiBearerAuth()
@UseGuards(JwtAuthGuard)
@Controller('projects')
export class ProjectsController {
  constructor(private readonly projectsService: ProjectsService) {}

  @Get()
  @ApiOperation({ summary: 'List all projects (paginated, filterable by status)' })
  @ApiResponse({ status: 200, description: 'Paginated list of projects' })
  async findAll(@Query() query: ProjectQueryDto) {
    return this.projectsService.findAll(query);
  }

  @Post()
  @ApiOperation({ summary: 'Create a new project' })
  @ApiResponse({ status: 201, description: 'Project created' })
  @HttpCode(HttpStatus.CREATED)
  async create(
    @Body() dto: CreateProjectDto,
    @CurrentUser() user: JwtPayload,
  ) {
    return this.projectsService.create(dto, user.sub);
  }

  @Get(':id')
  @ApiOperation({ summary: 'Get project with task count summary' })
  @ApiParam({ name: 'id', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 200, description: 'Project with task summary' })
  @ApiResponse({ status: 404, description: 'Project not found' })
  async findById(@Param('id', ParseUUIDPipe) id: string) {
    return this.projectsService.findById(id);
  }

  @Patch(':id')
  @ApiOperation({ summary: 'Update a project' })
  @ApiParam({ name: 'id', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 200, description: 'Project updated' })
  @ApiResponse({ status: 403, description: 'Only owner can update' })
  @ApiResponse({ status: 404, description: 'Project not found' })
  async update(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateProjectDto,
    @CurrentUser() user: JwtPayload,
  ) {
    return this.projectsService.update(id, dto, user.sub);
  }

  @Delete(':id')
  @ApiOperation({ summary: 'Soft delete a project (set ARCHIVED)' })
  @ApiParam({ name: 'id', type: 'string', format: 'uuid' })
  @ApiResponse({ status: 204, description: 'Project deleted' })
  @ApiResponse({ status: 403, description: 'Only owner can delete' })
  @ApiResponse({ status: 404, description: 'Project not found' })
  @HttpCode(HttpStatus.NO_CONTENT)
  async delete(
    @Param('id', ParseUUIDPipe) id: string,
    @CurrentUser() user: JwtPayload,
  ) {
    await this.projectsService.softDelete(id, user.sub);
  }
}
