import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { TaskPriority, TaskStatus } from '@prisma/client';
import { UserSummaryDto } from '../../common/dto/user.dto';
import { CommentResponseDto } from '../../comments/dto/comment-response.dto';

export class TaskResponseDto {
  @ApiProperty()
  id!: string;

  @ApiProperty()
  title!: string;

  @ApiPropertyOptional({ nullable: true })
  description!: string | null;

  @ApiProperty({ enum: TaskStatus })
  status!: TaskStatus;

  @ApiProperty({ enum: TaskPriority })
  priority!: TaskPriority;

  @ApiPropertyOptional({ nullable: true })
  due_date!: string | null;

  @ApiProperty()
  project_id!: string;

  @ApiPropertyOptional({ nullable: true })
  assignee_id!: string | null;

  @ApiProperty()
  reporter_id!: string;

  @ApiPropertyOptional({ type: UserSummaryDto, nullable: true })
  assignee!: UserSummaryDto | null;

  @ApiProperty({ type: UserSummaryDto })
  reporter!: UserSummaryDto;

  @ApiProperty()
  created_at!: string;

  @ApiProperty()
  updated_at!: string;
}

export class TaskDetailResponseDto extends TaskResponseDto {
  @ApiProperty({ type: [CommentResponseDto] })
  comments!: CommentResponseDto[];
}

export class TaskDeleteResponseDto {
  @ApiProperty()
  id!: string;

  @ApiProperty()
  deleted!: boolean;
}
