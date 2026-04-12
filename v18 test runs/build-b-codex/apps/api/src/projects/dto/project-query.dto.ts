import { IsOptional, IsEnum } from 'class-validator';
import { ApiPropertyOptional } from '@nestjs/swagger';
import { PaginationQueryDto } from '../../common/dto/pagination.dto';

enum ProjectStatusFilter {
  ACTIVE = 'ACTIVE',
  ARCHIVED = 'ARCHIVED',
}

export class ProjectQueryDto extends PaginationQueryDto {
  @ApiPropertyOptional({ enum: ProjectStatusFilter })
  @IsOptional()
  @IsEnum(ProjectStatusFilter)
  status?: ProjectStatusFilter;
}
