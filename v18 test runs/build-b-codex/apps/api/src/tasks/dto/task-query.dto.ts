import { IsOptional, IsEnum, IsUUID, IsIn } from 'class-validator';
import { ApiPropertyOptional } from '@nestjs/swagger';
import { PaginationQueryDto } from '../../common/dto/pagination.dto';

enum TaskStatusFilter {
  TODO = 'TODO',
  IN_PROGRESS = 'IN_PROGRESS',
  IN_REVIEW = 'IN_REVIEW',
  DONE = 'DONE',
}

enum TaskPriorityFilter {
  LOW = 'LOW',
  MEDIUM = 'MEDIUM',
  HIGH = 'HIGH',
  URGENT = 'URGENT',
}

export class TaskQueryDto extends PaginationQueryDto {
  @ApiPropertyOptional({ enum: TaskStatusFilter })
  @IsOptional()
  @IsEnum(TaskStatusFilter)
  status?: TaskStatusFilter;

  @ApiPropertyOptional({ enum: TaskPriorityFilter })
  @IsOptional()
  @IsEnum(TaskPriorityFilter)
  priority?: TaskPriorityFilter;

  @ApiPropertyOptional({ example: '550e8400-e29b-41d4-a716-446655440000' })
  @IsOptional()
  @IsUUID()
  assignee_id?: string;

  @ApiPropertyOptional({
    enum: ['due_date', 'priority', 'created_at'],
    default: 'created_at',
  })
  @IsOptional()
  @IsIn(['due_date', 'priority', 'created_at'])
  sort_by?: 'due_date' | 'priority' | 'created_at';

  @ApiPropertyOptional({ enum: ['asc', 'desc'], default: 'desc' })
  @IsOptional()
  @IsIn(['asc', 'desc'])
  sort_order?: 'asc' | 'desc';
}
