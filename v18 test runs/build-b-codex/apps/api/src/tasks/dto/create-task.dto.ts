import {
  IsString,
  MinLength,
  MaxLength,
  IsOptional,
  IsEnum,
  IsUUID,
  IsDateString,
} from 'class-validator';
import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';

enum TaskPriorityEnum {
  LOW = 'LOW',
  MEDIUM = 'MEDIUM',
  HIGH = 'HIGH',
  URGENT = 'URGENT',
}

export class CreateTaskDto {
  @ApiProperty({ example: 'Implement login page', maxLength: 200 })
  @IsString()
  @MinLength(1)
  @MaxLength(200)
  title!: string;

  @ApiPropertyOptional({ example: 'Build the login page with email/password form', maxLength: 2000 })
  @IsOptional()
  @IsString()
  @MaxLength(2000)
  description?: string;

  @ApiPropertyOptional({ enum: TaskPriorityEnum, default: 'MEDIUM' })
  @IsOptional()
  @IsEnum(TaskPriorityEnum)
  priority?: TaskPriorityEnum;

  @ApiPropertyOptional({ example: '2026-05-01' })
  @IsOptional()
  @IsDateString()
  due_date?: string;

  @ApiPropertyOptional({ example: '550e8400-e29b-41d4-a716-446655440000' })
  @IsOptional()
  @IsUUID()
  assignee_id?: string;
}
