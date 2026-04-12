import { IsNotEmpty, IsString, MaxLength } from 'class-validator';
import { ApiProperty } from '@nestjs/swagger';

export class CreateCommentDto {
  @ApiProperty({ example: 'This looks great!', maxLength: 1000 })
  @IsString()
  @IsNotEmpty()
  @MaxLength(1000)
  content: string;
}
