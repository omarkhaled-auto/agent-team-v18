import { IsEnum } from 'class-validator';
import { ApiProperty } from '@nestjs/swagger';
import { TaskStatus } from '@prisma/client';

export class UpdateTaskStatusDto {
  @ApiProperty({ enum: TaskStatus, example: TaskStatus.IN_PROGRESS })
  @IsEnum(TaskStatus)
  status: TaskStatus;
}
