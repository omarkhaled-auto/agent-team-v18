import { ApiPropertyOptional, PartialType } from '@nestjs/swagger';
import { ProjectStatus } from '@prisma/client';
import { IsEnum, IsOptional } from 'class-validator';
import { CreateProjectDto } from './create-project.dto';

export class UpdateProjectDto extends PartialType(CreateProjectDto) {
  @ApiPropertyOptional({ enum: ProjectStatus })
  @IsOptional()
  @IsEnum(ProjectStatus)
  status?: ProjectStatus;
}
