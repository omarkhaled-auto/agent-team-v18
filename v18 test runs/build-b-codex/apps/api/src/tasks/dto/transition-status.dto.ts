import { IsEnum } from 'class-validator';
import { ApiProperty } from '@nestjs/swagger';

enum TaskStatusEnum {
  TODO = 'TODO',
  IN_PROGRESS = 'IN_PROGRESS',
  IN_REVIEW = 'IN_REVIEW',
  DONE = 'DONE',
}

export class TransitionStatusDto {
  @ApiProperty({ enum: TaskStatusEnum, example: 'IN_PROGRESS' })
  @IsEnum(TaskStatusEnum)
  status!: TaskStatusEnum;
}
