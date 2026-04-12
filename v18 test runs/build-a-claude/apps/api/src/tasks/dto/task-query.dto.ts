import { IsOptional, IsEnum, IsUUID, IsIn } from 'class-validator';
import { ApiPropertyOptional } from '@nestjs/swagger';
import { TaskStatus, TaskPriority } from '@prisma/client';
import { PaginationQueryDto } from '../../common/dto/pagination-query.dto';

export class TaskQueryDto extends PaginationQueryDto {
  @ApiPropertyOptional({ enum: TaskStatus })
  @IsOptional()
  @IsEnum(TaskStatus)
  status?: TaskStatus;

  @ApiPropertyOptional({ enum: TaskPriority })
  @IsOptional()
  @IsEnum(TaskPriority)
  priority?: TaskPriority;

  @ApiPropertyOptional({ description: 'Filter by assignee UUID' })
  @IsOptional()
  @IsUUID()
  assigneeId?: string;

  @ApiPropertyOptional({
    enum: ['due_date', 'priority', 'created_at'],
    default: 'created_at',
  })
  @IsOptional()
  @IsIn(['due_date', 'priority', 'created_at'])
  sortBy?: 'due_date' | 'priority' | 'created_at' = 'created_at';

  @ApiPropertyOptional({ enum: ['asc', 'desc'], default: 'desc' })
  @IsOptional()
  @IsIn(['asc', 'desc'])
  sortOrder?: 'asc' | 'desc' = 'desc';
}
