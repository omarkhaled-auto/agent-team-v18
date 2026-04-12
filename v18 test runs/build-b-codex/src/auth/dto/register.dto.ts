import { ApiProperty } from '@nestjs/swagger';
import { IsEmail, IsString, MaxLength, MinLength } from 'class-validator';

export class RegisterDto {
  @ApiProperty({ example: 'newuser@taskflow.com' })
  @IsEmail()
  email!: string;

  @ApiProperty({ example: 'New User' })
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  name!: string;

  @ApiProperty({ example: 'password123' })
  @IsString()
  @MinLength(8)
  @MaxLength(128)
  password!: string;
}
