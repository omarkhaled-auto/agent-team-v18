import { IsEmail, IsString, MinLength, MaxLength } from 'class-validator';
import { ApiProperty } from '@nestjs/swagger';

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
  @MinLength(6)
  @MaxLength(128)
  password!: string;
}
