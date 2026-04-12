import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { ProjectStatus } from '@prisma/client';
import { UserSummaryDto } from '../../common/dto/user.dto';

export class ProjectResponseDto {
  @ApiProperty()
  id!: string;

  @ApiProperty()
  name!: string;

  @ApiPropertyOptional({ nullable: true })
  description!: string | null;

  @ApiProperty({ enum: ProjectStatus })
  status!: ProjectStatus;

  @ApiProperty()
  owner_id!: string;

  @ApiProperty({ type: UserSummaryDto })
  owner!: UserSummaryDto;

  @ApiProperty()
  created_at!: string;

  @ApiProperty()
  updated_at!: string;
}

export class ProjectTaskCountsDto {
  @ApiProperty()
  todo!: number;

  @ApiProperty()
  in_progress!: number;

  @ApiProperty()
  in_review!: number;

  @ApiProperty()
  done!: number;

  @ApiProperty()
  total!: number;
}

export class ProjectDetailResponseDto extends ProjectResponseDto {
  @ApiProperty({ type: ProjectTaskCountsDto })
  taskCounts!: ProjectTaskCountsDto;
}

export class ProjectArchiveResponseDto {
  @ApiProperty()
  id!: string;

  @ApiProperty({ enum: ['ARCHIVED'] })
  status!: 'ARCHIVED';
}
