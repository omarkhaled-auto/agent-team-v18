import { ApiProperty } from '@nestjs/swagger';
import { IsString, MaxLength, MinLength } from 'class-validator';

export class CreateCommentDto {
  @ApiProperty({ example: 'This looks great, good work!', maxLength: 1000 })
  @IsString()
  @MinLength(1)
  @MaxLength(1000)
  content!: string;
}
