import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Param, ParseUUIDPipe, Patch, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiForbiddenResponse, ApiNotFoundResponse, ApiOperation, ApiTags } from '@nestjs/swagger';
import { CurrentUser, CurrentUserPayload } from '../common/decorators/current-user.decorator';
import { PaginatedResponseDto } from '../common/dto/pagination.dto';
import { ApiDataResponse } from '../common/swagger/api-data-response.decorator';
import { CreateProjectDto } from './dto/create-project.dto';
import { ProjectArchiveResponseDto, ProjectDetailResponseDto, ProjectResponseDto } from './dto/project-response.dto';
import { ProjectQueryDto } from './dto/project-query.dto';
import { UpdateProjectDto } from './dto/update-project.dto';
import { ProjectsService } from './projects.service';

@ApiTags('Projects')
@ApiBearerAuth()
@Controller('projects')
export class ProjectsController {
  constructor(private readonly projectsService: ProjectsService) {}

  @Get()
  @ApiOperation({ summary: 'List all projects' })
  @ApiDataResponse(ProjectResponseDto, { description: 'Paginated list of projects', isArray: true, paginated: true })
  async findAll(@Query() query: ProjectQueryDto): Promise<PaginatedResponseDto<ProjectResponseDto>> {
    return this.projectsService.findAll(query);
  }

  @Post()
  @HttpCode(HttpStatus.CREATED)
  @ApiOperation({ summary: 'Create a new project' })
  @ApiDataResponse(ProjectResponseDto, { description: 'Project created successfully', status: 201 })
  async create(@Body() dto: CreateProjectDto, @CurrentUser() user: CurrentUserPayload): Promise<ProjectResponseDto> {
    return this.projectsService.create(dto, user.id);
  }

  @Get(':id')
  @ApiOperation({ summary: 'Get project with task count summary' })
  @ApiDataResponse(ProjectDetailResponseDto, { description: 'Project details with task counts' })
  @ApiNotFoundResponse({ description: 'Project not found' })
  async findOne(@Param('id', ParseUUIDPipe) id: string): Promise<ProjectDetailResponseDto> {
    return this.projectsService.findOne(id);
  }

  @Patch(':id')
  @ApiOperation({ summary: 'Update a project' })
  @ApiDataResponse(ProjectResponseDto, { description: 'Project updated successfully' })
  @ApiForbiddenResponse({ description: 'Forbidden' })
  @ApiNotFoundResponse({ description: 'Project not found' })
  async update(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateProjectDto,
    @CurrentUser() user: CurrentUserPayload,
  ): Promise<ProjectResponseDto> {
    return this.projectsService.update(id, dto, user.id, user.role);
  }

  @Delete(':id')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: 'Archive a project' })
  @ApiDataResponse(ProjectArchiveResponseDto, { description: 'Project archived successfully' })
  @ApiForbiddenResponse({ description: 'Forbidden' })
  @ApiNotFoundResponse({ description: 'Project not found' })
  async remove(
    @Param('id', ParseUUIDPipe) id: string,
    @CurrentUser() user: CurrentUserPayload,
  ): Promise<ProjectArchiveResponseDto> {
    return this.projectsService.remove(id, user.id, user.role);
  }
}
