import { ApiProperty } from '@nestjs/swagger';
import { TaskStatus } from '@prisma/client';
import { IsEnum } from 'class-validator';

export class TransitionStatusDto {
  @ApiProperty({ enum: TaskStatus })
  @IsEnum(TaskStatus)
  status!: TaskStatus;
}
