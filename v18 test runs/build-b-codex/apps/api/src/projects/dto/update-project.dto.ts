import { IsString, MinLength, MaxLength, IsOptional, IsEnum } from 'class-validator';
import { ApiPropertyOptional } from '@nestjs/swagger';

enum ProjectStatusEnum {
  ACTIVE = 'ACTIVE',
  ARCHIVED = 'ARCHIVED',
}

export class UpdateProjectDto {
  @ApiPropertyOptional({ example: 'Updated Project Name', maxLength: 100 })
  @IsOptional()
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  name?: string;

  @ApiPropertyOptional({ example: 'Updated description', maxLength: 500 })
  @IsOptional()
  @IsString()
  @MaxLength(500)
  description?: string;

  @ApiPropertyOptional({ enum: ProjectStatusEnum })
  @IsOptional()
  @IsEnum(ProjectStatusEnum)
  status?: ProjectStatusEnum;
}
